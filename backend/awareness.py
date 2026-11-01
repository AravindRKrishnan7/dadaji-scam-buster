"""Awareness card: how the detected scam works and how to stay safe. A static map, no LLM.

Shown under the complaint after the call ends. Every scam type the analyst can return maps to
one of six cards; anything without its own card gets the general one.
"""

REPORT_LINE = "Report at 1930 (the national cyber fraud helpline) or cybercrime.gov.in"

CARDS = {
    "bank_kyc": {
        "title": "Fake bank KYC call",
        "how": "The caller pretends to be from your bank and says your KYC has expired or your "
               "account will be blocked, to rush you into sharing details or an OTP, or into "
               "installing an app.",
        "tips": [
            "Banks never ask for your OTP, PIN or password over a phone call.",
            "Hang up and call the number printed on your card or passbook.",
            "Update KYC only at your branch or in the bank's official app.",
            "Never install an app or open a link a caller sends you.",
        ],
    },
    "otp_fraud": {
        "title": "OTP fraud",
        "how": "The caller gets you to read out a one-time password. That code lets them log in "
               "to your account or approve a payment from it.",
        "tips": [
            "An OTP is for you alone: no bank, company or officer ever needs it.",
            "Read the whole SMS: it says what the code will approve.",
            "Never read out a code to someone who called you.",
            "If you shared one, call your bank at once to block the account or card.",
        ],
    },
    "fake_fine_threat": {
        "title": "Fake fine or threat",
        "how": "The caller claims there is a fine, penalty or unpaid bill (a traffic challan, "
               "electricity, tax) and threatens action unless you pay right away.",
        "tips": [
            "Real fines and bills come in writing and can be checked on the official website.",
            "Government offices don't take payments to a personal UPI ID.",
            "Pressure to pay right now is the scam: take your time.",
            "Hang up and call the department on its official number.",
        ],
    },
    "digital_arrest": {
        "title": "Digital arrest",
        "how": "The caller poses as police, CBI, customs or a court, says you are linked to a "
               "crime or a seized parcel, and keeps you on the call \"under arrest\" until you pay "
               "to clear your name.",
        "tips": [
            "There is no such thing as a digital arrest: police don't arrest anyone by phone or video call.",
            "No officer will ask you to transfer money to verify or clear your name.",
            "Don't stay on the call: hang up and tell a family member.",
            "Check with your local police station in person.",
        ],
    },
    "upi_refund": {
        "title": "UPI refund trick",
        "how": "The caller says they sent you money or a refund by mistake and asks you to return "
               "it, or sends a collect request or QR code that takes money from you instead.",
        "tips": [
            "You never need your UPI PIN or a QR code to receive money.",
            "Check your balance in your own bank app, not a screenshot they send.",
            "Decline collect requests from people you don't know.",
        ],
    },
    "other": {
        "title": "Phone scam",
        "how": "The caller uses a believable story and pressure (urgency, fear or a reward) to get "
               "money, codes or personal details from you.",
        "tips": [
            "Never share an OTP, PIN, password or card details on a call.",
            "Hang up and call back on a number you look up yourself.",
            "Don't install apps or open links a stranger sends you.",
            "Real organisations don't rush you: take your time.",
        ],
    },
}

# Scam types without a card of their own, mapped to the closest one.
CLOSEST = {
    "courier_customs": "digital_arrest",   # "your parcel has drugs" leads to the same threats
    "electricity_bill": "fake_fine_threat",
}


def card_for(scam_type: str) -> dict:
    """The awareness card for a detected scam type: {key, title, how, tips, report}."""
    key = scam_type if scam_type in CARDS else CLOSEST.get(scam_type, "other")
    return {"key": key, **CARDS[key], "report": REPORT_LINE}
