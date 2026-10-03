"""Model artifact integrity: SHA-256 digests registered in a manifest, checked before any file is loaded.

    artifact file -> SHA-256 -> compare with the digest registered in manifest.json -> load only on match

Pickle files (tagger.pkl, fusion.pkl) can run code when unpickled, so a file whose digest is missing or
different is never opened for loading. The manifest is written by the code paths that legitimately
produce artifacts (training, the defender update, the co-evolution CLI).

What this protects against: corrupted or partially written files, a file swapped in without going
through a registered save, and artifacts copied from somewhere else. What it does NOT protect against:
someone who can write to the artifacts directory can also rewrite manifest.json. Closing that gap needs
signed manifests (a private key held outside the server); `ArtifactVerifier` is the seam for that, and no
signature scheme is implemented here.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

MANIFEST = "manifest.json"
ALGORITHM = "sha256"


class IntegrityError(RuntimeError):
    """An artifact is missing from the manifest or does not match its registered digest."""


def sha256_file(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_write_bytes(path: str | Path, data: bytes) -> None:
    """Write via a temp file in the same directory and rename, so readers never see a half-written file."""
    path = Path(path)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


class ArtifactVerifier(Protocol):
    """Checks one artifact before it is loaded. Raise IntegrityError to refuse it."""

    def verify(self, directory: Path, name: str) -> None: ...


class Sha256Manifest:
    """Digests stored in <directory>/manifest.json: {"algorithm": "sha256", "files": {name: {sha256, bytes}}}."""

    def __init__(self, directory: str | Path) -> None:
        self.directory = Path(directory)
        self.path = self.directory / MANIFEST

    def read(self) -> dict:
        if not self.path.exists():
            raise IntegrityError(f"no {MANIFEST} in {self.directory}; refusing to load unregistered artifacts")
        try:
            data = json.loads(self.path.read_text())
        except (OSError, ValueError) as e:
            raise IntegrityError(f"{MANIFEST} is unreadable: {e}") from e
        if data.get("algorithm") != ALGORITHM or not isinstance(data.get("files"), dict):
            raise IntegrityError(f"{MANIFEST} has an unsupported format")
        return data

    def verify(self, directory: Path, name: str) -> None:
        entry = self.read()["files"].get(name)
        if not entry or not isinstance(entry.get("sha256"), str):
            raise IntegrityError(f"{name} is not registered in {MANIFEST}")
        f = Path(directory) / name
        if not f.exists():
            raise IntegrityError(f"{name} is registered but missing")
        actual = sha256_file(f)
        if actual != entry["sha256"]:
            raise IntegrityError(f"{name} does not match its registered SHA-256 "
                                 f"(expected {entry['sha256'][:12]}..., got {actual[:12]}...)")

    def register(self, names: list[str], replace: bool = False) -> dict:
        """Record the current digests of `names`. replace=True drops entries for files not listed."""
        files = {} if replace or not self.path.exists() else self.read()["files"]
        for n in names:
            p = self.directory / n
            files[n] = {"sha256": sha256_file(p), "bytes": p.stat().st_size}
        data = {"algorithm": ALGORITHM, "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "files": dict(sorted(files.items()))}
        atomic_write_bytes(self.path, (json.dumps(data, indent=2) + "\n").encode())
        return data


def verify_all(directory: str | Path, names: list[str], verifier: ArtifactVerifier | None = None) -> None:
    directory = Path(directory)
    verifier = verifier or Sha256Manifest(directory)
    for n in names:
        verifier.verify(directory, n)
