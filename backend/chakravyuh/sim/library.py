"""Offline message library for Chakravyuh.

Each family is a script: an ordered list of steps. A step has a kill-chain stage,
the tactics it uses, message variants per language, and side-events (calls,
screen share, payee creation, payments) that happen at that step.

These templates are deliberately tactic-level and generic. They let the simulator
run with no LLM at all; with an LLM configured, the attacker agent rewrites them.
"""

from __future__ import annotations

# Slot values filled at generation time.
SLOTS = {
    "org": ["SEBI", "Mumbai Cyber Cell", "CBI", "TRAI", "Customs Department", "RBI"],
    "bank": ["SBI", "HDFC Bank", "ICICI Bank", "Axis Bank", "Punjab National Bank"],
    "app": ["AnyDesk", "QuickSupport", "ScreenMate"],
    "platform": ["Telegram", "WhatsApp"],
    "stock": ["IPO allotment", "block deal", "F&O tips", "crypto arbitrage"],
    "company": ["StarGlobal Media", "AdBoost Digital", "Prime Reviews Ltd"],
    "relation": ["beta", "didi", "bhaiya", "mummy"],
    "shop": ["Sharma General Store", "FreshMart", "City Pharmacy"],
}

S = "stage"
T = "tactics"
M = "msg"
E = "events"   # side events: list of (type, attrs)

SCRIPTS: dict[str, list[dict]] = {
    # ---------------------------------------------------------------- scams
    "investment_group": [
        {S: "contact", T: ["social_proof", "greed"], M: {
            "en": ["You have been added to {platform} group 'Smart Investors Club'. Members made 30% this week on {stock}.",
                   "Hi! Our mentor shares free {stock} calls daily. 4,000 members already earning. Join now."],
            "hi": ["आपको 'स्मार्ट इन्वेस्टर्स क्लब' ग्रुप में जोड़ा गया है। सदस्यों ने इस हफ्ते {stock} में 30% कमाया।"],
            "hinglish": ["Aapko Smart Investors Club group me add kiya gaya hai. Is hafte members ne {stock} pe 30% kamaya."]}},
        {S: "hook", T: ["greed", "trust_building"], M: {
            "en": ["Today's tip gave 12% profit. Download our institutional app to get access to {stock}: {link}",
                   "Sir/Madam, start with just Rs 5,000 to test. Profit is credited daily in the app."],
            "hi": ["आज की टिप में 12% मुनाफा हुआ। {stock} के लिए हमारा ऐप डाउनलोड करें: {link}"],
            "hinglish": ["Aaj ki tip me 12% profit hua. {stock} access ke liye hamara app download karo: {link}"]},
         E: [("LINK_OPEN", {}), ("APK_INSTALL", {})]},
        {S: "trust", T: ["trust_building", "social_proof"], M: {
            "en": ["Congratulations, your Rs {small} test investment is now Rs {small_x2}. See screenshot from other members too.",
                   "Withdraw small profit anytime. Many members withdrew today, check group."],
            "hi": ["बधाई हो, आपका {small} रुपये का निवेश अब {small_x2} रुपये हो गया है।"],
            "hinglish": ["Congratulations, aapka Rs {small} ka test investment ab Rs {small_x2} ho gaya hai."]},
         E: [("PAYEE_NEW", {}), ("PAY", {"kind": "test"}), ("RECV", {"kind": "fake_profit"})]},
        {S: "pressure", T: ["urgency", "greed"], M: {
            "en": ["Special {stock} slot closes in 2 hours. Minimum Rs {amount} for VIP allotment. Only 5 seats left.",
                   "Mentor recommends increasing capital now, market window is short."],
            "hi": ["स्पेशल {stock} स्लॉट 2 घंटे में बंद होगा। VIP के लिए न्यूनतम {amount} रुपये।"],
            "hinglish": ["Special {stock} slot 2 ghante me band ho jayega. VIP ke liye minimum Rs {amount} lagao."]}},
        {S: "payment_ask", T: ["payment_request", "urgency"], M: {
            "en": ["Transfer Rs {amount} to our settlement account {vpa} to lock your allotment.",
                   "To withdraw your profit you must first pay 18% tax of Rs {amount} to {vpa}."],
            "hi": ["अपना आवंटन लॉक करने के लिए {vpa} पर {amount} रुपये भेजें।"],
            "hinglish": ["Allotment lock karne ke liye {vpa} pe Rs {amount} transfer karo."]},
         E: [("UPI_OPEN", {}), ("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "main"})]},
    ],
    "task_job": [
        {S: "contact", T: ["greed"], M: {
            "en": ["Part-time job from home! Earn Rs 3,000/day by liking YouTube videos. Reply YES.",
                   "Hello, I am HR from {company}. Simple online tasks, daily payment. Interested?"],
            "hi": ["घर से पार्ट-टाइम जॉब! यूट्यूब वीडियो लाइक करके रोज़ 3,000 रुपये कमाएं।"],
            "hinglish": ["Ghar se part time job! YouTube videos like karke roz Rs 3000 kamao. YES reply karo."]}},
        {S: "hook", T: ["reciprocity", "trust_building"], M: {
            "en": ["Task 1 done, Rs 150 credited to you. Join our {platform} for more tasks.",
                   "Great work! Your first commission has been sent."],
            "hi": ["टास्क 1 पूरा, 150 रुपये आपको भेजे गए।"],
            "hinglish": ["Task 1 complete, Rs 150 aapko bhej diye. Aur tasks ke liye {platform} join karo."]},
         E: [("RECV", {"kind": "bait"})]},
        {S: "trust", T: ["social_proof", "greed"], M: {
            "en": ["Prepaid tasks give 40% more. Deposit Rs {small} and get Rs {small_x2} back in 1 hour.",
                   "Merchant tasks are premium. Other members completed and earned double."],
            "hi": ["प्रीपेड टास्क में 40% ज्यादा कमाई। {small} जमा करें, एक घंटे में {small_x2} वापस।"],
            "hinglish": ["Prepaid task me 40% zyada milta hai. Rs {small} deposit karo, 1 ghante me Rs {small_x2} wapas."]},
         E: [("PAYEE_NEW", {}), ("PAY", {"kind": "test"}), ("RECV", {"kind": "fake_profit"})]},
        {S: "pressure", T: ["urgency", "fear"], M: {
            "en": ["Your task is incomplete. Complete combo task with Rs {amount} or previous earnings will be frozen.",
                   "System error: account frozen. Pay Rs {amount} to unlock and withdraw everything."],
            "hi": ["आपका टास्क अधूरा है। {amount} रुपये से कॉम्बो टास्क पूरा करें वरना कमाई फ्रीज़ हो जाएगी।"],
            "hinglish": ["Task incomplete hai. Rs {amount} se combo task complete karo warna earning freeze ho jayegi."]}},
        {S: "payment_ask", T: ["payment_request"], M: {
            "en": ["Send Rs {amount} to {vpa} now to finish the task."],
            "hi": ["टास्क खत्म करने के लिए अभी {vpa} पर {amount} रुपये भेजें।"],
            "hinglish": ["Task khatam karne ke liye abhi {vpa} pe Rs {amount} bhejo."]},
         E: [("UPI_OPEN", {}), ("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "main"})]},
    ],
    "mule_recruitment": [
        {S: "contact", T: ["greed"], M: {
            "en": ["Earn Rs 10,000/week by receiving payments for our export company. Students welcome.",
                   "Easy commission job: you receive client payments in your account and forward them."],
            "hi": ["हमारी कंपनी के लिए पेमेंट रिसीव करके हर हफ्ते 10,000 रुपये कमाएं।"],
            "hinglish": ["Hamari company ke liye payment receive karke har hafte Rs 10,000 kamao. Students welcome."]}},
        {S: "hook", T: ["trust_building", "greed"], M: {
            "en": ["You keep 5% of every payment. Just share your UPI ID and bank account.",
                   "We are a registered firm, just tax issue so we use partner accounts."],
            "hi": ["हर पेमेंट का 5% आपका। बस अपना UPI ID और बैंक खाता शेयर करें।"],
            "hinglish": ["Har payment ka 5% aapka. Bas apna UPI ID aur bank account share karo."]}},
        {S: "trust", T: ["secrecy", "isolation"], M: {
            "en": ["Don't tell your bank this is commission, they create problems. Say it is from friends.",
                   "Keep this job private, many people are jealous."],
            "hi": ["बैंक को कमीशन मत बताना, वो दिक्कत करते हैं। बोलना दोस्तों से आया है।"],
            "hinglish": ["Bank ko commission mat batana, problem karte hain. Bolna friends se aaya hai."]},
         E: [("RECV", {"kind": "mule_in"}), ("RECV", {"kind": "mule_in"}), ("RECV", {"kind": "mule_in"})]},
        {S: "payment_ask", T: ["payment_request", "urgency"], M: {
            "en": ["Forward Rs {amount} to {vpa} within 30 minutes, keep your commission.",
                   "Client payment received, transfer it immediately to {vpa}."],
            "hi": ["30 मिनट में {vpa} पर {amount} रुपये भेजें, अपना कमीशन रख लें।"],
            "hinglish": ["30 minute me {vpa} pe Rs {amount} forward karo, apna commission rakh lo."]},
         E: [("UPI_OPEN", {}), ("PAYEE_NEW", {})]},
        {S: "cashout", T: [], M: {}, E: [("PAY", {"kind": "main"})]},
    ],
    "digital_arrest": [
        {S: "contact", T: ["authority", "fear"], M: {
            "en": ["This is {org}. A parcel in your name contains illegal items. Stay on the line.",
                   "Your Aadhaar is linked to a money laundering case. Officer will call you now."],
            "hi": ["यह {org} है। आपके नाम के पार्सल में अवैध सामान मिला है। लाइन पर बने रहें।"],
            "hinglish": ["Main {org} se bol raha hoon. Aapke naam ke parcel me illegal items mile hain."]},
         E: [("CALL", {"known": False, "minutes": 25})]},
        {S: "pressure", T: ["authority", "fear", "secrecy", "isolation"], M: {
            "en": ["You are under digital arrest. Do not disconnect the video call or tell anyone, including family.",
                   "If you inform anyone, arrest warrant will be executed today."],
            "hi": ["आप डिजिटल अरेस्ट में हैं। वीडियो कॉल न काटें और किसी को न बताएं।"],
            "hinglish": ["Aap digital arrest me ho. Video call mat kaato aur family ko kuch mat batao."]},
         E: [("CALL", {"known": False, "minutes": 120}), ("SCREEN_SHARE", {})]},
        {S: "payment_ask", T: ["payment_request", "authority", "urgency"], M: {
            "en": ["Transfer Rs {amount} to RBI verification account {vpa}. It will be refunded after verification.",
                   "Break your FD and deposit Rs {amount} to {vpa} for fund verification."],
            "hi": ["सत्यापन के लिए {vpa} पर {amount} रुपये भेजें, बाद में वापस मिलेंगे।"],
            "hinglish": ["Verification ke liye {vpa} pe Rs {amount} transfer karo, baad me refund ho jayega."]},
         E: [("FD_BREAK", {}), ("UPI_OPEN", {}), ("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "main"})]},
    ],
    "fake_kyc": [
        {S: "contact", T: ["authority", "urgency", "fear"], M: {
            "en": ["Dear customer, your {bank} account will be blocked today. Update KYC: {link}",
                   "{bank}: PAN not updated. Account suspended in 24 hrs. Click {link}"],
            "hi": ["प्रिय ग्राहक, आपका {bank} खाता आज बंद हो जाएगा। KYC अपडेट करें: {link}"],
            "hinglish": ["Dear customer, aapka {bank} account aaj block ho jayega. KYC update karo: {link}"]},
         E: [("LINK_OPEN", {})]},
        {S: "pressure", T: ["credential_request", "remote_access"], M: {
            "en": ["Please install {app} so our executive can complete KYC. Share the OTP you receive.",
                   "Enter the OTP sent to your phone to verify. Do not share with anyone else."],
            "hi": ["KYC पूरा करने के लिए {app} इंस्टॉल करें और OTP बताएं।"],
            "hinglish": ["KYC complete karne ke liye {app} install karo aur OTP batao."]},
         E: [("REMOTE_APP", {}), ("SCREEN_SHARE", {}), ("CALL", {"known": False, "minutes": 15})]},
        {S: "payment_ask", T: ["payment_request"], M: {
            "en": ["A refundable verification charge of Rs {amount} is required. Pay to {vpa}."],
            "hi": ["{amount} रुपये का रिफंडेबल शुल्क {vpa} पर भरें।"],
            "hinglish": ["Rs {amount} ka refundable verification charge {vpa} pe pay karo."]},
         E: [("UPI_OPEN", {}), ("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "main"})]},
    ],
    "fake_support": [
        {S: "contact", T: ["trust_building"], M: {
            "en": ["Thank you for calling customer care. Your refund of Rs 1,499 is pending.",
                   "Hello, I am from the delivery company support. Your order refund is stuck."],
            "hi": ["कस्टमर केयर पर कॉल करने के लिए धन्यवाद। आपका 1,499 रुपये का रिफंड पेंडिंग है।"],
            "hinglish": ["Customer care me call karne ke liye thanks. Aapka Rs 1499 ka refund pending hai."]},
         E: [("CALL", {"known": False, "minutes": 20})]},
        {S: "pressure", T: ["remote_access", "urgency"], M: {
            "en": ["To process refund, install {app} and open your UPI app. I will guide you.",
                   "Share your screen so I can see the error."],
            "hi": ["रिफंड के लिए {app} इंस्टॉल करें और UPI ऐप खोलें।"],
            "hinglish": ["Refund ke liye {app} install karo aur UPI app kholo, main guide karunga."]},
         E: [("REMOTE_APP", {}), ("SCREEN_SHARE", {}), ("UPI_OPEN", {})]},
        {S: "payment_ask", T: ["payment_request", "credential_request"], M: {
            "en": ["Enter Rs {amount} and your PIN to receive the refund.",
                   "Type the amount {amount} and approve, the refund will come to you."],
            "hi": ["रिफंड पाने के लिए {amount} डालें और PIN दर्ज करें।"],
            "hinglish": ["Refund paane ke liye Rs {amount} daalo aur PIN enter karo."]},
         E: [("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "main"})]},
    ],
    "refund_qr": [
        {S: "contact", T: ["greed", "trust_building"], M: {
            "en": ["I want to buy your item on the marketplace. I will pay advance via QR.",
                   "Interested in your sofa. Sending payment QR now."],
            "hi": ["मुझे आपका सामान खरीदना है। QR से एडवांस भेज रहा हूँ।"],
            "hinglish": ["Aapka item khareedna hai. QR se advance bhej raha hoon."]}},
        {S: "payment_ask", T: ["payment_request", "urgency"], M: {
            "en": ["Scan this QR and enter Rs {amount} to receive the money.",
                   "Just scan and enter PIN, money will come to your account."],
            "hi": ["पैसे पाने के लिए यह QR स्कैन करें और {amount} डालें।"],
            "hinglish": ["Paise receive karne ke liye QR scan karke Rs {amount} daalo."]},
         E: [("UPI_OPEN", {}), ("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "main"})]},
    ],
    "echallan_link": [
        {S: "contact", T: ["authority", "fear", "urgency"], M: {
            "en": ["Traffic e-challan of Rs 500 issued for your vehicle. Pay within 24 hrs to avoid court: {link}",
                   "Your vehicle challan is pending. Licence will be suspended. View: {link}"],
            "hi": ["आपके वाहन पर 500 रुपये का ई-चालान है। कोर्ट से बचने के लिए 24 घंटे में भरें: {link}"],
            "hinglish": ["Aapki gaadi pe Rs 500 ka e-challan hai. 24 ghante me bharo warna court: {link}"]},
         E: [("LINK_OPEN", {}), ("APK_INSTALL", {})]},
        {S: "payment_ask", T: ["payment_request", "credential_request"], M: {
            "en": ["Pay Rs {amount} including late fee to {vpa} and enter OTP to confirm."],
            "hi": ["लेट फीस सहित {amount} रुपये {vpa} पर भरें और OTP डालें।"],
            "hinglish": ["Late fee ke saath Rs {amount} {vpa} pe bharo aur OTP daalo."]},
         E: [("UPI_OPEN", {}), ("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "main"})]},
    ],
    # --------------------------------------------------------------- benign
    "family_urgent": [
        {S: "contact", T: ["urgency"], M: {
            "en": ["{relation}, my phone battery is dying, please send Rs {amount} for hostel fees urgently today.",
                   "Need Rs {amount} urgently for hospital bill, will explain at home."],
            "hi": ["{relation}, हॉस्टल फीस के लिए आज ही {amount} रुपये भेज दो, बहुत ज़रूरी है।"],
            "hinglish": ["{relation}, hostel fees ke liye aaj hi Rs {amount} bhej do, bahut urgent hai."]},
         E: [("CALL", {"known": True, "minutes": 4})]},
        {S: "payment_ask", T: ["payment_request", "urgency"], M: {
            "en": ["Send to my usual UPI please, fast."],
            "hi": ["मेरे वाले UPI पर भेज दो, जल्दी।"],
            "hinglish": ["Mere usual UPI pe bhej do, jaldi."]},
         E: [("UPI_OPEN", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "known"})]},
    ],
    "bank_genuine": [
        {S: "contact", T: ["authority", "urgency"], M: {
            "en": ["{bank}: Your KYC is due. Visit your branch or update in the official app. We never ask for OTP or PIN.",
                   "{bank}: Rs 2,340 debited for electricity bill. Not you? Call the number on your card.",
                   "{bank}: Your account will be restricted after 31st if KYC is not updated. Visit the nearest branch with PAN.",
                   "{bank}: Suspicious login blocked on your account. If this was not you, call the number on the back of your card urgently."],
            "hi": ["{bank}: आपका KYC बाकी है। शाखा जाएं या आधिकारिक ऐप में अपडेट करें। हम कभी OTP नहीं मांगते।"],
            "hinglish": ["{bank}: Aapka KYC due hai. Branch jao ya official app me update karo. Hum kabhi OTP nahi maangte."]}},
    ],
    "investment_genuine": [
        {S: "contact", T: ["greed"], M: {
            "en": ["Your SIP of Rs {amount} in index fund is scheduled for tomorrow. Manage it in the app.",
                   "Market update: NIFTY closed up 1.2%. Review your portfolio in the app."],
            "hi": ["इंडेक्स फंड में आपका {amount} रुपये का SIP कल है।"],
            "hinglish": ["Index fund me aapka Rs {amount} ka SIP kal hai. App me manage karo."]},
         E: [("UPI_OPEN", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "known"})]},
    ],
    "merchant_payment": [
        {S: "contact", T: [], M: {
            "en": ["Your order at {shop} is ready. Total Rs {amount}. Pay at counter or via QR.",
                   "Thanks for shopping at {shop}! Bill amount Rs {amount}."],
            "hi": ["{shop} पर आपका ऑर्डर तैयार है। कुल {amount} रुपये।"],
            "hinglish": ["{shop} pe aapka order ready hai. Total Rs {amount}."]},
         E: [("UPI_OPEN", {}), ("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "merchant"})]},
    ],
    # Hard negatives: legitimate sessions that look scary on purpose.
    "genuine_support": [
        {S: "contact", T: ["urgency"], M: {
            "en": ["{relation}, my UPI app is showing an error and the bill is due today. Can you help me on a call?",
                   "Hi, this is your {bank} relationship manager. Your card renewal is pending, you can complete it in the app."],
            "hi": ["{relation}, मेरा UPI ऐप एरर दिखा रहा है और बिल आज भरना है। कॉल पर मदद करोगे?"],
            "hinglish": ["{relation}, mera UPI app error de raha hai, bill aaj bharna hai. Call pe help karoge?"]},
         E: [("CALL", {"known": False, "minutes": 30}), ("SCREEN_SHARE", {}), ("UPI_OPEN", {})]},
        {S: "payment_ask", T: ["payment_request"], M: {
            "en": ["Ok now enter Rs {amount} for the electricity bill and confirm.",
                   "Add the biller as a new payee and pay Rs {amount}."],
            "hi": ["अब बिजली बिल के लिए {amount} रुपये डालो और कन्फर्म करो।"],
            "hinglish": ["Ab electricity bill ke liye Rs {amount} daalo aur confirm karo."]},
         E: [("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "merchant"})]},
    ],
    "big_purchase": [
        {S: "contact", T: ["urgency", "payment_request"], M: {
            "en": ["Hi, the flat is yours. Please transfer the security deposit of Rs {amount} today so I can hold it.",
                   "Your laptop order is confirmed. Pay Rs {amount} to the dealer account before 6 pm to get delivery tomorrow.",
                   "Admission confirmed. Fee of Rs {amount} must be paid within 48 hours or the seat goes to waitlist."],
            "hi": ["फ्लैट आपका है। आज ही {amount} रुपये सिक्योरिटी डिपॉज़िट भेज दें।"],
            "hinglish": ["Flat aapka hai. Aaj hi Rs {amount} security deposit bhej do taaki hold kar sakoon."]},
         E: [("CALL", {"known": False, "minutes": 8})]},
        {S: "payment_ask", T: ["payment_request"], M: {
            "en": ["Account details: {vpa}. Send screenshot after payment."],
            "hi": ["खाता: {vpa}। पेमेंट के बाद स्क्रीनशॉट भेजें।"],
            "hinglish": ["Account details: {vpa}. Payment ke baad screenshot bhejna."]},
         E: [("UPI_OPEN", {}), ("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "merchant"})]},
    ],
    "new_number_family": [
        {S: "contact", T: ["urgency", "trust_building"], M: {
            "en": ["Hi {relation}, this is my new number, old phone got water damaged. Save this one.",
                   "{relation} it's me, using a friend's phone, mine is in repair."],
            "hi": ["{relation}, यह मेरा नया नंबर है, पुराना फोन खराब हो गया।"],
            "hinglish": ["{relation}, ye mera naya number hai, purana phone kharab ho gaya. Save kar lo."]}},
        {S: "payment_ask", T: ["payment_request", "urgency"], M: {
            "en": ["Can you send Rs {amount}? I need to pay for the new phone, will return on Sunday.",
                   "Please send Rs {amount} for the cab, my cards are in the other phone."],
            "hi": ["क्या {amount} रुपये भेज दोगे? नए फोन के लिए चाहिए, रविवार को लौटा दूंगा।"],
            "hinglish": ["Rs {amount} bhej doge? Naye phone ke liye chahiye, Sunday ko lauta dunga."]},
         E: [("CALL", {"known": False, "minutes": 3}), ("UPI_OPEN", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "known"})]},
    ],
    "investment_tip_friend": [
        {S: "contact", T: ["greed", "social_proof"], M: {
            "en": ["Bro I made 20% on that small-cap fund this year, everyone in office is buying. You should start a SIP.",
                   "Our office group is putting money in the new NFO, returns look great. Join in?"],
            "hi": ["भाई, उस स्मॉल-कैप फंड में इस साल 20% मिला, ऑफिस में सब खरीद रहे हैं।"],
            "hinglish": ["Bhai small-cap fund me is saal 20% mila, office me sab le rahe hain. SIP start kar."]}},
        {S: "trust", T: ["trust_building"], M: {
            "en": ["Use the official app of the fund house, not any link. Start with Rs {small}."],
            "hi": ["फंड हाउस का आधिकारिक ऐप इस्तेमाल करो, किसी लिंक से नहीं।"],
            "hinglish": ["Fund house ka official app use karna, kisi link se nahi. Rs {small} se start karo."]},
         E: [("UPI_OPEN", {}), ("PAYEE_NEW", {})]},
        {S: "payment", T: [], M: {}, E: [("PAY", {"kind": "merchant"})]},
    ],
    "friend_split": [
        {S: "contact", T: ["payment_request"], M: {
            "en": ["Dinner was Rs {amount} per head, send when you can :)",
                   "Your share for the Goa trip is Rs {amount}. No rush!"],
            "hi": ["डिनर का हर किसी का {amount} रुपये, जब हो सके भेज देना।"],
            "hinglish": ["Dinner ka per head Rs {amount} hua, jab ho sake bhej dena :)"]}},
        {S: "payment", T: [], M: {}, E: [("UPI_OPEN", {}), ("PAY", {"kind": "known"})]},
    ],
}
