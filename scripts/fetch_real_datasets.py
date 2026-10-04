#!/usr/bin/env python3
"""Fetch, register and check real datasets. Raw files are copied, never edited.

    python scripts/fetch_real_datasets.py status                      # access + licence + on-disk state
    python scripts/fetch_real_datasets.py fetch imc25_smishing        # GitHub release at the pinned commit
    python scripts/fetch_real_datasets.py fetch uci_sms_spam --mirror # third-party copy, audit only
    python scripts/fetch_real_datasets.py register moz_smishing --from ~/Downloads/moz  # after a local download
    python scripts/fetch_real_datasets.py verify imc25_smishing       # SHA-256 of every raw file

`fetch` refuses if a downloaded file's SHA-256 differs from the manifest. `--pin` records digests the
first time a dataset is acquired; review the files before pinning.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from chakravyuh.realdata import registry  # noqa: E402


def _git_checkout(repo: str, commit: str, dest: Path) -> None:
    env = {"GIT_LFS_SKIP_SMUDGE": "1", "GIT_TERMINAL_PROMPT": "0", "PATH": "/usr/bin:/bin:/usr/local/bin"}
    subprocess.run(["git", "init", "-q", str(dest)], check=True, env=env)
    subprocess.run(["git", "-C", str(dest), "fetch", "-q", "--depth", "1", repo, commit], check=True, env=env)
    subprocess.run(["git", "-C", str(dest), "checkout", "-q", "FETCH_HEAD"], check=True, env=env)
    head = subprocess.run(["git", "-C", str(dest), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    if not head.startswith(commit):
        raise SystemExit(f"checked out {head}, expected {commit}")


def _is_lfs_pointer(p: Path) -> bool:
    with open(p, "rb") as f:
        return f.read(64).startswith(b"version https://git-lfs.github.com/spec/")


def _install(m: dict, files: dict[str, Path], provenance: dict, pin: bool, key: str = "sha256") -> None:
    raw = registry.raw_dir(m)
    expected = m.get(key) or {}
    if not pin and not expected:
        raise SystemExit(f"{m['dataset_id']}: no digests registered under '{key}'. Inspect the files, then rerun with --pin.")
    for dest, src in files.items():
        if _is_lfs_pointer(src):
            raise SystemExit(f"{src.name} is a Git LFS pointer, not data")
        digest = registry.sha256_file(src)
        if not pin and expected.get(dest) != digest:
            raise SystemExit(f"SHA-256 mismatch for {dest}: expected {expected.get(dest)}, got {digest}. Not installed.")
        expected[dest] = digest
    raw.mkdir(parents=True, exist_ok=True)
    for dest, src in files.items():
        target = raw / dest
        if target.exists():
            target.chmod(0o644)
        shutil.copyfile(src, target)
        target.chmod(0o444)                      # raw data is read-only from here on
    (raw / ".provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    if pin:
        m[key] = dict(sorted(expected.items()))
        if provenance.get("kind") != "mirror":
            m["download_date"] = provenance["fetched_at"][:10]
        registry.save(m)
    print(f"{m['dataset_id']}: installed {len(files)} file(s) into {raw.relative_to(registry.REPO)}")


def _url_download(url: str, dest: Path, max_bytes: int = 50_000_000) -> None:
    import urllib.request
    with urllib.request.urlopen(url, timeout=60) as r, open(dest, "wb") as out:   # noqa: S310 - pinned https URL
        data = r.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise SystemExit(f"{url}: larger than {max_bytes} bytes")
        out.write(data)


def fetch(dataset_id: str, mirror: bool, pin: bool) -> None:
    m = registry.load(dataset_id)
    spec = m["fetch"].get("mirror") if mirror else m["fetch"]
    if spec and spec.get("method") == "url":
        # Files at an immutable revision URL (e.g. a Hugging Face commit); refused unless SHA-256 matches.
        with tempfile.TemporaryDirectory() as tmp:
            files = {}
            for f in spec["files"]:
                files[f["dest"]] = Path(tmp) / f["dest"]
                _url_download(f["url"], files[f["dest"]])
            prov = {"kind": "original", "urls": [f["url"] for f in spec["files"]], "revision": spec.get("revision"),
                    "fetched_at": datetime.now(UTC).isoformat(timespec="seconds")}
            _install(m, files, prov, pin)
        return
    if not spec or spec.get("method") != "git":
        raise SystemExit(f"{dataset_id}: no {'mirror' if mirror else 'GitHub'} source. "
                         f"Access status {m['access_status']}: {m['fetch'].get('instructions', '')}")
    with tempfile.TemporaryDirectory() as tmp:
        _git_checkout(spec["repo"], spec["commit"], Path(tmp))
        files = {f["dest"]: Path(tmp) / f["src"] for f in spec["files"]}
        prov = {"kind": "mirror" if mirror else "original", "repo": spec["repo"], "commit": spec["commit"],
                "fetched_at": datetime.now(UTC).isoformat(timespec="seconds")}
        _install(m, files, prov, pin, "mirror_sha256" if mirror else "sha256")


def register(dataset_id: str, src: Path, pin: bool) -> None:
    m = registry.load(dataset_id)
    names = [f["dest"] for f in m["fetch"].get("files", [])]
    files = {}
    for n in names:
        hits = list(src.rglob(n)) if src.is_dir() else ([src] if src.name == n else [])
        if not hits:
            raise SystemExit(f"{n} not found under {src}")
        files[n] = hits[0]
    _install(m, files, {"kind": "local_download", "from": str(src),
                        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds")}, pin)


def verify(dataset_id: str) -> bool:
    m = registry.load(dataset_id)
    raw = registry.raw_dir(m)
    prov = json.loads((raw / ".provenance.json").read_text()) if (raw / ".provenance.json").exists() else {}
    expected = m.get("mirror_sha256" if prov.get("kind") == "mirror" else "sha256") or {}
    ok = bool(expected)
    for name, digest in expected.items():
        p = raw / name
        good = p.exists() and registry.sha256_file(p) == digest
        ok &= good
        print(f"  {'ok  ' if good else 'FAIL'} {name}")
    return ok


def status() -> None:
    print(f"{'dataset':28} {'access':24} {'licence':15} {'type':10} {'on disk':10} train?")
    for i in registry.all_ids():
        m = registry.load(i)
        raw = registry.raw_dir(m)
        prov = json.loads((raw / ".provenance.json").read_text())["kind"] if (raw / ".provenance.json").exists() else "-"
        print(f"{i:28} {m['access_status']:24} {m['license_status']:15} {m['real_or_synthetic'][:10]:10} "
              f"{prov:10} {'yes' if m['training_allowed'] else 'no'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status")
    f = sub.add_parser("fetch")
    f.add_argument("dataset_id", nargs="+")
    f.add_argument("--mirror", action="store_true")
    f.add_argument("--pin", action="store_true")
    r = sub.add_parser("register")
    r.add_argument("dataset_id")
    r.add_argument("--from", dest="src", required=True, type=Path)
    r.add_argument("--pin", action="store_true")
    v = sub.add_parser("verify")
    v.add_argument("dataset_id", nargs="+")
    a = ap.parse_args()
    if a.cmd == "status":
        status()
    elif a.cmd == "fetch":
        for d in a.dataset_id:
            fetch(d, a.mirror, a.pin)
    elif a.cmd == "register":
        register(a.dataset_id, a.src.expanduser(), a.pin)
    else:
        return 0 if all(verify(d) for d in a.dataset_id) else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
