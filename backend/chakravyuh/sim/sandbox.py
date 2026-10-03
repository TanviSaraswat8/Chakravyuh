"""Simulated payment rail (UPI-style) with a mule network.

Records every transfer in a ledger so the payee-risk model can be trained on
realistic fan-in / pass-through patterns.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field


@dataclass
class Account:
    vpa: str
    kind: str              # user | merchant | family | mule_l1 | mule_l2 | exchange
    created_day: int       # day index when the account was opened
    devices: int = 1


@dataclass
class Txn:
    src: str
    dst: str
    amount: float
    t: float               # seconds since sandbox epoch
    first_time: bool
    session_id: str | None = None


@dataclass
class PaymentSandbox:
    rng: random.Random
    accounts: dict[str, Account] = field(default_factory=dict)
    ledger: list[Txn] = field(default_factory=list)
    _pairs: set[tuple[str, str]] = field(default_factory=set)
    _seq: int = 0

    # ------------------------------------------------------------ accounts
    def _new_vpa(self, prefix: str, handle: str) -> str:
        self._seq += 1
        return f"{prefix}{self._seq:05d}@{handle}"

    def open_account(self, kind: str, day: int, devices: int = 1) -> str:
        handles = {"user": "okbank", "family": "okbank", "merchant": "paytm",
                   "mule_l1": "ybl", "mule_l2": "ibl", "exchange": "axl"}
        prefixes = {"user": "user", "family": "fam", "merchant": "shop",
                    "mule_l1": "acc", "mule_l2": "acc", "exchange": "xchg"}
        vpa = self._new_vpa(prefixes[kind], handles[kind])
        self.accounts[vpa] = Account(vpa=vpa, kind=kind, created_day=day, devices=devices)
        return vpa

    def build_world(self, n_users: int = 300, n_merchants: int = 60, n_mule_rings: int = 12,
                    day: int = 400) -> None:
        for _ in range(n_users):
            self.open_account("user", self.rng.randint(0, day - 30))
        for _ in range(n_merchants):
            self.open_account("merchant", self.rng.randint(0, day - 60))
        self.exchanges = [self.open_account("exchange", self.rng.randint(0, 100)) for _ in range(3)]
        self.rings: list[dict] = []
        for _ in range(n_mule_rings):
            l1 = [self.open_account("mule_l1", day - self.rng.randint(1, 25), devices=self.rng.randint(2, 6))
                  for _ in range(self.rng.randint(3, 6))]
            l2 = [self.open_account("mule_l2", day - self.rng.randint(5, 60), devices=self.rng.randint(1, 4))
                  for _ in range(self.rng.randint(1, 3))]
            self.rings.append({"l1": l1, "l2": l2})

    def users(self) -> list[str]:
        return [a.vpa for a in self.accounts.values() if a.kind == "user"]

    def merchants(self) -> list[str]:
        return [a.vpa for a in self.accounts.values() if a.kind == "merchant"]

    def scam_payee(self) -> str:
        ring = self.rng.choice(self.rings)
        return self.rng.choice(ring["l1"])

    def family_payee(self, day: int) -> str:
        return self.open_account("family", day - self.rng.randint(200, 900))

    # ------------------------------------------------------------ transfers
    def pay(self, src: str, dst: str, amount: float, t: float, session_id: str | None = None) -> Txn:
        first = (src, dst) not in self._pairs
        self._pairs.add((src, dst))
        txn = Txn(src, dst, round(amount, 2), t, first, session_id)
        self.ledger.append(txn)
        acct = self.accounts.get(dst)
        if acct and acct.kind == "mule_l1":
            self._forward(dst, amount, t)
        return txn

    def _forward(self, mule: str, amount: float, t: float) -> None:
        """Mules pass money on fast: layer 1 -> layer 2 -> exchange."""
        ring = next(r for r in self.rings if mule in r["l1"])
        delay = self.rng.uniform(120, 2400)
        l2 = self.rng.choice(ring["l2"])
        kept = amount * self.rng.uniform(0.02, 0.06)
        self.ledger.append(Txn(mule, l2, round(amount - kept, 2), t + delay, (mule, l2) not in self._pairs))
        self._pairs.add((mule, l2))
        ex = self.rng.choice(self.exchanges)
        self.ledger.append(Txn(l2, ex, round((amount - kept) * 0.98, 2), t + delay + self.rng.uniform(300, 3600),
                               (l2, ex) not in self._pairs))
        self._pairs.add((l2, ex))

    def background_traffic(self, n: int, t0: float, t1: float) -> None:
        users, merchants = self.users(), self.merchants()
        for _ in range(n):
            src = self.rng.choice(users)
            if self.rng.random() < 0.7:
                dst = self.rng.choice(merchants)
                amt = self.rng.lognormvariate(5.5, 1.0)
            else:
                dst = self.rng.choice(users)
                amt = self.rng.lognormvariate(6.5, 1.1)
            if src != dst:
                self.pay(src, dst, amt, self.rng.uniform(t0, t1))

    def labels(self) -> dict[str, int]:
        return {v: int(a.kind.startswith("mule")) for v, a in self.accounts.items()}
