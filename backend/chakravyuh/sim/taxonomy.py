"""Shared vocabulary for Chakravyuh: tactics, kill-chain stages, scam families, event types.

Every component (simulator, models, API, frontend) uses these exact strings.
"""

TACTICS = [
    "authority",          # claims to be police, bank, government, company
    "urgency",            # act now, deadline, account will be blocked
    "fear",               # arrest, legal action, loss
    "greed",              # profit, returns, bonus, prize
    "secrecy",            # don't tell anyone, stay on the call
    "trust_building",     # small wins, friendly chat, testimonials
    "social_proof",       # others are earning, group members
    "isolation",          # keep the victim away from family/bank
    "payment_request",    # asks to send money
    "credential_request", # asks for OTP, PIN, card details
    "remote_access",      # asks to install app / share screen
    "link_click",         # asks to open a link / install APK
    "reciprocity",        # "I helped you, now you help me"
]

STAGES = ["contact", "hook", "trust", "pressure", "payment_ask", "payment", "cashout"]
STAGE_INDEX = {s: i for i, s in enumerate(STAGES)}

SCAM_FAMILIES = [
    "investment_group",
    "task_job",
    "mule_recruitment",
    "digital_arrest",
    "fake_kyc",
    "fake_support",
    "refund_qr",
    "echallan_link",     # held out by default to test "emerging" detection
]

BENIGN_FAMILIES = [
    "family_urgent",
    "bank_genuine",
    "investment_genuine",
    "merchant_payment",
    "friend_split",
    "genuine_support",
    "big_purchase",
    "new_number_family",
    "investment_tip_friend",
]

FAMILIES = SCAM_FAMILIES + BENIGN_FAMILIES

LANGUAGES = ["en", "hi", "hinglish"]

CHANNELS = ["sms", "whatsapp", "telegram", "call", "email"]

EVENT_TYPES = [
    "MSG_RECV",
    "MSG_SENT",
    "CALL",
    "SCREEN_SHARE",
    "REMOTE_APP",
    "LINK_OPEN",
    "APK_INSTALL",
    "UPI_OPEN",
    "PAYEE_NEW",
    "FD_BREAK",
    "PAY",
    "RECV",        # money received (relevant for mule recruitment)
]
EVENT_INDEX = {e: i for i, e in enumerate(EVENT_TYPES)}

# Escalation ladder used by the alert policy.
ALERT_LEVELS = {
    0: "silent_log",
    1: "nudge",
    2: "interactive_check",
    3: "cooling_off",
    4: "trusted_contact_hold",
}
