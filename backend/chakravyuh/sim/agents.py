"""Attacker, victim and benign agents, and the session runner.

A *session* is everything between first contact and money leaving the account.
`run_session` turns a genome (the scam's structure) and a victim profile into
a labelled event sequence, and moves money in the payment sandbox.
"""

from __future__ import annotations

import copy
import math
import random
import uuid
from dataclasses import asdict, dataclass, field

from .library import SCRIPTS, SLOTS
from .llm import LLMClient
from .mutations import mutate_text
from .sandbox import PaymentSandbox
from .taxonomy import BENIGN_FAMILIES, SCAM_FAMILIES, TACTICS

# How big the main payment is relative to the victim's usual payment (min, max multiplier).
AMOUNT_RATIO = {
    "investment_group": (20, 200), "task_job": (5, 40), "mule_recruitment": (5, 30),
    "digital_arrest": (50, 500), "fake_kyc": (2, 20), "fake_support": (2, 25),
    "refund_qr": (1, 10), "echallan_link": (1, 3),
    "family_urgent": (2, 40), "bank_genuine": (0, 0), "investment_genuine": (1, 60),
    "merchant_payment": (0.3, 3), "friend_split": (0.5, 3),
    "genuine_support": (0.5, 6), "big_purchase": (10, 150), "new_number_family": (2, 20),
    "investment_tip_friend": (1, 10),
}
# Typical gap between script steps, in hours (min, max).
PACE_HOURS = {
    "investment_group": (6, 72), "task_job": (1, 24), "mule_recruitment": (2, 48),
    "digital_arrest": (0.05, 0.5), "fake_kyc": (0.02, 0.3), "fake_support": (0.02, 0.2),
    "refund_qr": (0.05, 1), "echallan_link": (0.05, 6),
    "family_urgent": (0.02, 0.3), "bank_genuine": (0.1, 1), "investment_genuine": (1, 24),
    "merchant_payment": (0.01, 0.2), "friend_split": (1, 48),
    "genuine_support": (0.02, 0.3), "big_purchase": (0.5, 24), "new_number_family": (0.05, 2),
    "investment_tip_friend": (2, 72),
}
REPLIES = {
    "en": ["ok", "how?", "is this safe?", "ok sir", "what should I do", "I will try"],
    "hi": ["ठीक है", "कैसे?", "क्या यह सुरक्षित है?", "जी", "मुझे क्या करना है"],
    "hinglish": ["ok", "kaise?", "safe hai na?", "theek hai sir", "kya karna hai", "try karta hoon"],
}
KNOWN_SENDER = {"family_urgent", "bank_genuine", "investment_genuine", "friend_split", "investment_tip_friend"}
# Small talk both scammers and real contacts send. Shared across classes on purpose.
FILLER = {
    "en": ["Hello?", "Are you there?", "Please reply", "Ok noted", "Good morning 🙏", "Call me when free",
           "Send screenshot once done", "Thank you", "Did you see my message?", "I am waiting"],
    "hi": ["हैलो?", "आप हैं?", "जवाब दीजिए", "ठीक है", "सुप्रभात 🙏", "फ्री होकर कॉल करना", "धन्यवाद"],
    "hinglish": ["Hello?", "Aap ho?", "Reply karo plz", "Ok noted", "Good morning ji 🙏", "Free hoke call karna",
                 "Done hone ke baad screenshot bhejna", "Thank you", "Message dekha?", "Wait kar raha hoon"],
}
NOISE_OPS = ["synonym", "code_mix", "emoji", "typos"]


@dataclass
class Genome:
    family: str
    language: str = "en"
    channel: str = "whatsapp"
    text_ops: list[str] = field(default_factory=list)        # surface mutations
    extra_tactics: list[str] = field(default_factory=list)   # injected persuasion tactics
    borrow_contact: str | None = None                        # crossover: contact step from another family
    swap_trust_pressure: bool = False                        # reordered kill chain
    drop_stages: list[str] = field(default_factory=list)     # skip steps to leave fewer signals
    amount_scale: float = 1.0
    pace_scale: float = 1.0
    generation: int = 0
    parent: str | None = None
    genome_id: str = field(default_factory=lambda: uuid.uuid4().hex[:10])

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Victim:
    vpa: str
    age_band: str
    literacy: float          # 0..1 digital literacy
    stress: float            # 0..1 financial stress
    authority_trust: float   # 0..1
    language: str
    median_txn: float

    @staticmethod
    def sample(rng: random.Random, vpa: str, language: str) -> Victim:
        return Victim(
            vpa=vpa,
            age_band=rng.choice(["18-25", "26-40", "41-60", "60+"]),
            literacy=rng.betavariate(3, 2),
            stress=rng.betavariate(2, 3),
            authority_trust=rng.betavariate(3, 2),
            language=language,
            median_txn=round(rng.lognormvariate(6.8, 0.6), 2),
        )

    def pay_probability(self, tactics_so_far: list[str], warned: int = 0) -> float:
        """P(pay) = sigma(b0 + b_v . v + sum_k b_k tactic_k - gamma * warning)."""
        z = 0.2
        z += -1.6 * self.literacy + 1.2 * self.stress + 0.9 * self.authority_trust
        z += 0.6 if self.age_band == "60+" else 0.0
        weights = {"urgency": 0.25, "fear": 0.35, "authority": 0.3, "greed": 0.25,
                   "trust_building": 0.3, "social_proof": 0.2, "isolation": 0.35, "secrecy": 0.25}
        z += sum(weights.get(t, 0.05) for t in tactics_so_far)
        z -= [0.0, 0.8, 1.4, 2.2, 3.0][min(warned, 4)]
        return 1 / (1 + math.exp(-z))


def _fill(text: str, rng: random.Random, ctx: dict) -> str:
    vals = {k: rng.choice(v) for k, v in SLOTS.items()}
    vals.update(ctx)
    try:
        return text.format(**vals)
    except (KeyError, IndexError):
        return text


def build_script(genome: Genome) -> list[dict]:
    script = copy.deepcopy(SCRIPTS[genome.family])
    if genome.borrow_contact and genome.borrow_contact in SCRIPTS:
        donor = SCRIPTS[genome.borrow_contact][0]
        if donor["stage"] == "contact":
            script[0] = copy.deepcopy(donor)
            if genome.borrow_contact in BENIGN_FAMILIES:
                script[0]["tactics"] = list(donor["tactics"])   # disguised as an ordinary opener
                script[0]["disguise"] = True
    if genome.drop_stages:
        script = [st for st in script if st["stage"] not in genome.drop_stages
                  or st["stage"] in ("payment", "payment_ask", "cashout")]
    if genome.swap_trust_pressure:
        idx = {s["stage"]: i for i, s in enumerate(script)}
        if "trust" in idx and "pressure" in idx:
            i, j = idx["trust"], idx["pressure"]
            script[i], script[j] = script[j], script[i]
    if genome.extra_tactics:
        for step in script:
            if step.get("msg"):
                step["tactics"] = sorted(set(step["tactics"]) | set(genome.extra_tactics))
    return script


def run_session(genome: Genome, victim: Victim, sandbox: PaymentSandbox, rng: random.Random,
                t_start: float, llm: LLMClient | None = None, llm_rate: float = 0.0,
                warn_fn=None, variant_pool: str = "train") -> dict:
    """Play one session. `warn_fn(events) -> level` lets a defender intervene live (used in evolution)."""
    is_scam = genome.family in SCAM_FAMILIES
    sid = uuid.uuid4().hex[:12]
    script = build_script(genome)
    lo, hi = AMOUNT_RATIO[genome.family]
    main_amount = round(victim.median_txn * rng.uniform(lo, hi) * genome.amount_scale, -1) or 100.0
    small = round(victim.median_txn * rng.uniform(1, 4), -1)

    if genome.family in ("family_urgent", "friend_split", "new_number_family"):
        payee = sandbox.family_payee(400)
        sandbox._pairs.add((victim.vpa, payee))
    elif genome.family in ("merchant_payment", "investment_genuine", "investment_tip_friend", "genuine_support"):
        payee = rng.choice(sandbox.merchants())
    elif genome.family == "big_purchase":
        payee = sandbox.open_account("merchant", 400 - rng.randint(3, 900))
    elif genome.family == "mule_recruitment":
        ring = rng.choice(sandbox.rings)
        payee = rng.choice(ring["l2"])
    else:
        payee = sandbox.scam_payee()

    ctx = {"amount": f"{int(main_amount):,}", "small": f"{int(small):,}",
           "small_x2": f"{int(small * 1.8):,}", "vpa": payee, "link": "hxxp://short.link/x" + sid[:4]}
    pace_lo, pace_hi = PACE_HOURS[genome.family]

    events: list[dict] = []
    tactics_seen: list[str] = []
    t = t_start
    paid = False
    loss = 0.0
    max_warn = 0
    known = genome.family in KNOWN_SENDER

    disguise = False

    def add(etype: str, stage: str, tactics=None, text: str | None = None, **attrs) -> None:
        if disguise:
            attrs["disguise"] = True     # label metadata only: never read by the models as an input
        events.append({"t": round(t - t_start, 1), "type": etype, "stage": stage,
                       "tactics": tactics or [], "text": text, "channel": genome.channel, "attrs": attrs})

    for step in script:
        t += rng.uniform(pace_lo, pace_hi) * 3600 * genome.pace_scale
        stage, tactics = step["stage"], step["tactics"]
        disguise = bool(step.get("disguise"))
        variants = step.get("msg", {}).get(genome.language) or step.get("msg", {}).get("en")
        if variants and len(variants) >= 2:
            # Wording hold-out: the last variant of each step is only ever used in test sessions.
            variants = variants[-1:] if variant_pool == "test" else variants[:-1]
        if variants:
            text = _fill(rng.choice(variants), rng, ctx)
            if llm and llm.enabled and rng.random() < llm_rate:
                text = llm.rewrite(text, genome.language, tactics, stage, ",".join(genome.text_ops)) or text
            if genome.text_ops:
                text = mutate_text(text, genome.text_ops, rng)
            elif rng.random() < 0.35:   # everyday noise, applied to scams and legit alike
                text = mutate_text(text, [rng.choice(NOISE_OPS)], rng)
            if rng.random() < 0.3:
                add("MSG_RECV", stage, [], rng.choice(FILLER[genome.language]), known_sender=known)
                t += rng.uniform(10, 300)
            add("MSG_RECV", stage, tactics, text, known_sender=known)
            tactics_seen.extend(tactics)
            if rng.random() < 0.5:
                t += rng.uniform(20, 600)
                add("MSG_SENT", stage, [], rng.choice(REPLIES[genome.language]))

        for etype, attrs in step.get("events", []):
            t += rng.uniform(5, 300)
            if warn_fn is not None:
                max_warn = max(max_warn, warn_fn(events))
            if etype == "CALL":
                add("CALL", stage, known=attrs.get("known", known),
                    minutes=attrs.get("minutes", 5) * rng.uniform(0.6, 1.5))
            elif etype == "PAYEE_NEW":
                acct = sandbox.accounts.get(payee)
                age = (400 - acct.created_day) if acct else 365
                if (victim.vpa, payee) not in sandbox._pairs:
                    add("PAYEE_NEW", stage, payee=payee, payee_age_days=age)
            elif etype == "RECV":
                amt = small * (1.8 if attrs.get("kind") == "fake_profit" else 0.3) \
                    if attrs.get("kind") != "mule_in" else main_amount / 3
                src = rng.choice(sandbox.users())
                sandbox.pay(src, victim.vpa, amt, t, sid)
                add("RECV", stage, amount=round(amt, 2), from_known=False, kind=attrs.get("kind"))
            elif etype == "PAY":
                kind = attrs.get("kind", "main")
                amount = small if kind == "test" else main_amount
                first = (victim.vpa, payee) not in sandbox._pairs
                if is_scam and kind != "test":
                    p = victim.pay_probability(tactics_seen, warned=max_warn)
                    if rng.random() > p:
                        add("PAY", stage, amount=amount, payee=payee, cancelled=True,
                            amount_ratio=round(amount / victim.median_txn, 2), first_time=first)
                        break
                sandbox.pay(victim.vpa, payee, amount, t, sid)
                add("PAY", stage, amount=amount, payee=payee, cancelled=False,
                    amount_ratio=round(amount / victim.median_txn, 2), first_time=first)
                if kind != "test":
                    paid = True
                    loss = amount if is_scam else 0.0
            else:
                add(etype, stage)

    return {
        "session_id": sid,
        "label": int(is_scam),
        "family": genome.family,
        "language": genome.language,
        "channel": genome.channel,
        "generation": genome.generation,
        "genome": genome.to_dict(),
        "victim": asdict(victim),
        "events": events,
        "paid": paid,
        "loss": loss,
        "max_warning": max_warn,
        "duration_hours": round((t - t_start) / 3600, 2),
        "variant_pool": variant_pool,
    }


def random_genome(rng: random.Random, families: list[str], generation: int = 0) -> Genome:
    fam = rng.choice(families)
    return Genome(
        family=fam,
        language=rng.choices(["en", "hi", "hinglish"], weights=[0.4, 0.2, 0.4])[0],
        channel="sms" if fam in ("fake_kyc", "echallan_link", "bank_genuine") else
        rng.choice(["whatsapp", "telegram", "sms"]),
        text_ops=rng.sample(["synonym", "code_mix", "emoji"], k=rng.randint(0, 1)),
        generation=generation,
    )


def benign_families() -> list[str]:
    return list(BENIGN_FAMILIES)


def all_tactics() -> list[str]:
    return list(TACTICS)
