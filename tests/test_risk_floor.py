"""The risk floor rule: authority claim + demand/threat. Run with: pytest  (LIVE=1 also runs Groq)"""
import asyncio
import os

import pytest

from backend import analyst, evidence, guardrail, orchestrator
from backend.analyst import FLOOR_SIGNAL, Analysis, risk_floor
from backend.main import new_session

# SBI claim -> bank account request -> ₹10 lakh fine.
SCRIPT = [
    "Hello, main SBI se bol raha hoon, aapke account mein problem hai.",
    "Apna bank account number aur details bataiye verification ke liye.",
    "Agar abhi details nahi di toh aap pe 10 lakh rupaye ka fine lagega.",
]
# An analyst that badly underrates it: "other", low risk, every turn.
WEAK_ANALYST = [Analysis(scam_type="other", risk_score=r) for r in (20, 25, 40)]


def run_script(monkeypatch=None):
    if monkeypatch:
        answers = iter(WEAK_ANALYST)

        async def fake_analyst(*a):
            return next(answers)

        async def none(*a, **k):
            return None

        async def no_evidence(text):
            return evidence.Findings()

        async def fake_dadaji(*a, **k):
            return "Arre beta, chashma kahan gaya?"

        monkeypatch.setattr(analyst, "run", fake_analyst)
        monkeypatch.setattr(guardrail, "prompt_guard_score", none)
        monkeypatch.setattr(evidence, "run", no_evidence)
        monkeypatch.setattr(orchestrator, "dadaji_reply", fake_dadaji)

    async def call():
        _, session = new_session("sweet")
        types = []
        for text in SCRIPT:
            await orchestrator.handle_turn(session, text)
            types.append(session["case"].scam_type)
        return session["case"], types

    return asyncio.run(call())


def assert_floor(case, types):
    assert case.risk_history[1] >= 75 and case.risk_history[2] >= 75, case.risk_history
    assert "other" not in types[1:], types
    assert FLOOR_SIGNAL in case.signals


def test_sbi_account_fine_call_hits_the_floor(monkeypatch):
    case, types = run_script(monkeypatch)
    assert_floor(case, types)
    assert case.risk_history == [20, 75, 75]       # turn 1 is only a claim: no floor yet
    assert types == ["other", "bank_kyc", "bank_kyc"]


@pytest.mark.skipif(not os.getenv("LIVE"), reason="calls Groq; run with LIVE=1")
def test_sbi_account_fine_call_live():
    assert_floor(*run_script())


@pytest.mark.parametrize("texts, expected", [
    (SCRIPT[:1], None),                                          # a claim alone
    (["Apna account number bataiye."], None),                    # a demand alone
    (SCRIPT[:2], ("bank", "account", None)),
    (SCRIPT, ("bank", "account", "fine")),
    (["Main HDFC bank se bol raha hoon.", "OTP bata dijiye."], ("bank", "otp", None)),
    (["CBI officer bol raha hoon, aapke naam warrant hai."], ("government", None, "arrest")),
    (["Income tax department se call hai, 50,000 jurmana bharna padega."], ("government", None, "fine")),
    (["namaste main pulis vibhaag se bol raha hoon, aapko giraftaar kiya jaayega"],
     ("government", None, "arrest")),                            # romanised Devanagari
    (["Customs office se bol rahe hain, parcel ke liye 5000 transfer kariye."], ("government", "money", None)),
])
def test_risk_floor_rule(texts, expected):
    hit = risk_floor(texts)
    assert (hit and (hit.authority, hit.demand, hit.threat)) == (expected or None)


@pytest.mark.parametrize("text", [
    "main fine hoon beta, aap kaise ho?",      # "fine" as in okay
    "mera bank SBI hai, Bunty ne khulwaya tha", # a bank mentioned, not claimed
    "Paytm pe 500 bhejo",                       # a demand, but no authority claim
    "fir se bolo, OTP batao",                   # Hinglish "fir" (again) isn't an FIR
])
def test_no_false_alarms(text):
    assert risk_floor([text]) is None


@pytest.mark.parametrize("threat, demand, authority, scam_type", [
    ("arrest", None, "government", "digital_arrest"),
    ("fine", "account", "bank", "fake_fine_threat"),
    (None, "otp", "bank", "otp_fraud"),
    (None, "account", "bank", "bank_kyc"),
    (None, "money", "government", "fake_fine_threat"),
])
def test_floor_type(threat, demand, authority, scam_type):
    assert analyst.FloorHit(authority, demand, threat).scam_type == scam_type


def test_floor_beats_an_innocent_verdict():
    from backend.case_file import CaseFile
    case = CaseFile(session_id="t", persona="sweet")
    case.apply_analysis(Analysis(scam_type="not_scam", risk_score=5), floor=risk_floor(SCRIPT))
    assert case.risk_score == 75 and case.scam_type == "fake_fine_threat"
