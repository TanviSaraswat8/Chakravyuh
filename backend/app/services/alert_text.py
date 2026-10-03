"""Vetted alert templates. The models pick a reason code; only these fixed texts reach users.

No free-form generated advice is ever shown to a user, so a manipulated model cannot
tell someone their scam is safe.
"""

from __future__ import annotations

TEMPLATES: dict[str, dict[str, tuple[str, str]]] = {
    "R_AUTHORITY_PAYMENT": {
        "en": ("Police and banks never ask for money on a call",
               "No police officer, court, RBI or bank will ask you to transfer money or stay on a video call. "
               "Hang up and call 1930 if you feel threatened."),
        "hi": ("पुलिस और बैंक कभी कॉल पर पैसे नहीं मांगते",
               "कोई पुलिस, अदालत, RBI या बैंक आपसे पैसे ट्रांसफर करने या वीडियो कॉल पर रहने को नहीं कहेगा। "
               "कॉल काटें और डर लगे तो 1930 पर कॉल करें।"),
        "hinglish": ("Police aur bank kabhi call pe paise nahi maangte",
                     "Koi police, court, RBI ya bank aapse paise transfer karne ya video call pe rehne ko nahi kahega. "
                     "Call kaato aur dar lage to 1930 pe call karo."),
    },
    "R_INVESTMENT": {
        "en": ("Guaranteed high returns are a classic scam sign",
               "Groups promising fixed daily profit, then asking for a 'tax' or 'fee' to withdraw, are scams. "
               "Invest only through SEBI-registered apps you installed yourself."),
        "hi": ("पक्का ऊँचा मुनाफा ठगी का संकेत है",
               "रोज़ तय मुनाफे का वादा और निकालने के लिए 'टैक्स' या 'फीस' माँगना ठगी है। "
               "सिर्फ़ SEBI-पंजीकृत ऐप से निवेश करें।"),
        "hinglish": ("Pakka high return scam ka sign hai",
                     "Roz fixed profit ka vaada aur withdraw ke liye 'tax' ya 'fee' maangna scam hai. "
                     "Sirf SEBI-registered app se invest karo."),
    },
    "R_TASK": {
        "en": ("Jobs never ask you to pay to earn",
               "Paying a deposit to unlock 'tasks' or 'frozen earnings' is how task scams take your money."),
        "hi": ("कोई असली नौकरी कमाने के लिए पैसे नहीं माँगती",
               "'टास्क' या 'फ्रीज़ कमाई' खोलने के लिए जमा राशि माँगना टास्क स्कैम है।"),
        "hinglish": ("Asli job kamane ke liye paise nahi maangti",
                     "'Task' ya 'frozen earning' unlock karne ke liye deposit maangna task scam hai."),
    },
    "R_MULE": {
        "en": ("Receiving and forwarding money for strangers is illegal",
               "Your account may be used to move stolen money. You can be held responsible. Stop and contact your bank."),
        "hi": ("अजनबियों के लिए पैसे लेना और आगे भेजना अपराध है",
               "आपके खाते से चोरी का पैसा घुमाया जा सकता है और ज़िम्मेदारी आपकी होगी। रुकें और बैंक से बात करें।"),
        "hinglish": ("Strangers ke liye paise lena aur aage bhejna illegal hai",
                     "Aapke account se chori ka paisa ghumaya ja sakta hai, zimmedari aapki hogi. Ruko aur bank se baat karo."),
    },
    "R_REMOTE_ACCESS": {
        "en": ("Someone may be controlling your screen",
               "Never pay or enter your PIN while sharing your screen with a caller you don't know. End the screen share."),
        "hi": ("कोई आपकी स्क्रीन देख या चला रहा हो सकता है",
               "अनजान कॉलर के साथ स्क्रीन शेयर करते हुए कभी पेमेंट या PIN न डालें। स्क्रीन शेयर बंद करें।"),
        "hinglish": ("Koi aapki screen dekh ya chala raha ho sakta hai",
                     "Anjaan caller ke saath screen share karte hue kabhi payment ya PIN mat daalo. Screen share band karo."),
    },
    "R_RECEIVE_PIN": {
        "en": ("You never enter a PIN to receive money",
               "If someone says you will 'receive' money by scanning a QR or entering your PIN, money will leave your account."),
        "hi": ("पैसे पाने के लिए कभी PIN नहीं डालना होता",
               "QR स्कैन या PIN डालने से पैसे 'मिलेंगे', यह कहने वाला आपके खाते से पैसे निकालेगा।"),
        "hinglish": ("Paise receive karne ke liye kabhi PIN nahi daalna hota",
                     "QR scan ya PIN se paise 'milenge' bolne wala aapke account se paise nikalega."),
    },
    "R_LINK_KYC": {
        "en": ("This link may be fake",
               "Banks, traffic police and investment firms don't send payment, KYC or app links in messages. "
               "Install apps only from the Play Store and pay only through apps you already trust."),
        "hi": ("यह लिंक नकली हो सकता है",
               "बैंक, ट्रैफिक पुलिस या निवेश कंपनियाँ मैसेज में पेमेंट, KYC या ऐप लिंक नहीं भेजतीं। "
               "ऐप सिर्फ़ Play Store से इंस्टॉल करें।"),
        "hinglish": ("Ye link fake ho sakta hai",
                     "Bank, traffic police ya investment firm message me payment, KYC ya app link nahi bhejte. "
                     "App sirf Play Store se install karo."),
    },
    "R_GENERIC": {
        "en": ("This looks like a scam pattern",
               "Pause before paying a new contact. Check with someone you trust, or call 1930."),
        "hi": ("यह ठगी जैसा लग रहा है",
               "नए व्यक्ति को पैसे देने से पहले रुकें। किसी भरोसेमंद से पूछें या 1930 पर कॉल करें।"),
        "hinglish": ("Ye scam jaisa lag raha hai",
                     "Naye contact ko paise dene se pehle ruko. Kisi bharosemand se poocho ya 1930 pe call karo."),
    },
}

LEVEL_PREFIX = {
    1: {"en": "", "hi": "", "hinglish": ""},
    2: {"en": "Is someone on a call telling you to make this payment? ",
        "hi": "क्या कोई कॉल पर आपसे यह पेमेंट करवा रहा है? ",
        "hinglish": "Kya koi call pe aapse ye payment karwa raha hai? "},
    3: {"en": "We've paused this payment for 30 minutes to keep you safe. ",
        "hi": "आपकी सुरक्षा के लिए यह पेमेंट 30 मिनट के लिए रोका गया है। ",
        "hinglish": "Aapki safety ke liye ye payment 30 minute ke liye roka gaya hai. "},
    4: {"en": "This payment is on hold until your trusted contact or bank confirms. ",
        "hi": "आपके भरोसेमंद व्यक्ति या बैंक की पुष्टि तक यह पेमेंट रुका है। ",
        "hinglish": "Trusted contact ya bank confirm kare tab tak ye payment hold pe hai. "},
}

FAMILY_REASON = {
    "digital_arrest": "R_AUTHORITY_PAYMENT", "investment_group": "R_INVESTMENT", "task_job": "R_TASK",
    "mule_recruitment": "R_MULE", "fake_support": "R_REMOTE_ACCESS", "refund_qr": "R_RECEIVE_PIN",
    "fake_kyc": "R_LINK_KYC", "echallan_link": "R_LINK_KYC",
}


def reason_code(tactics: set[str], flags: dict, family_guess: str | None, events: list[dict]) -> str:
    """Most specific explanation first: authority threats, investment bait, remote access, mule, links."""
    types = {e["type"] for e in events}
    if "authority" in tactics and ("fear" in tactics or "isolation" in tactics):
        return "R_AUTHORITY_PAYMENT"
    if "greed" in tactics and ("social_proof" in tactics or "trust_building" in tactics):
        return "R_TASK" if family_guess == "task_job" or "reciprocity" in tactics else "R_INVESTMENT"
    if flags.get("screen_share") or flags.get("remote_app") or "remote_access" in tactics:
        return "R_REMOTE_ACCESS"
    if sum(1 for e in events if e["type"] == "RECV") >= 2 and family_guess in (None, "mule_recruitment"):
        return "R_MULE"
    if "LINK_OPEN" in types or "APK_INSTALL" in types or "link_click" in tactics or "credential_request" in tactics:
        return "R_LINK_KYC"
    if family_guess in FAMILY_REASON:
        return FAMILY_REASON[family_guess]
    return "R_GENERIC"


def render(code: str, level: int, language: str) -> tuple[str, str]:
    lang = language if language in ("en", "hi", "hinglish") else "en"
    title, body = TEMPLATES.get(code, TEMPLATES["R_GENERIC"])[lang]
    return title, LEVEL_PREFIX.get(level, LEVEL_PREFIX[1])[lang] + body
