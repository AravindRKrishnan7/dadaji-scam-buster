"""Dadaji passes the phone to Bunty on the second push for phone/app steps. Run with: pytest"""
import asyncio

import pytest
from fastapi.testclient import TestClient

from backend import analyst, evidence, guardrail, orchestrator
from backend.analyst import phone_step
from backend.guardrail import check_output
from backend.main import app, new_session
from backend.personas import PASS_LINE, PASS_NOTE, PERSONAS


@pytest.mark.parametrize("text", [
    "Sir aapke phone pe OTP aaya hoga, woh jaldi bata dijiye",
    "Accha OTP nahi mil raha toh YONO app kholo",  # the "nahi" next to OTP doesn't hide this
    "abhi jo code aaya woh bolo",
    "Play Store se AnyDesk app download kijiye",
    "YONO app kholo uncle",
    "please install the app now",
    "Main link bhej raha hoon, us link pe click karo",
    "screen share kijiye",
])
def test_phone_steps_are_pushes(text):
    assert phone_step(text)


@pytest.mark.parametrize("text", [
    "OTP kisi ko mat batana",            # a warning (scammers say it too), not a push
    "never share your OTP with anyone",
    "main SBI head office se bol raha hoon",
    "Uncle, OTP aaya hai kya?",          # asking whether it came isn't asking for it
    "apna pin code bataiye",             # an address, not a code
    "phone pe baat kar rahe hain",
])
def test_other_lines_are_not_pushes(text):
    assert phone_step(text) is None


# Turn 2 is the first push (Dadaji stalls), turn 3 the second (he passes the phone).
SCRIPT = [
    "Namaste uncle, main SBI head office se bol raha hoon. Aapka KYC aaj expire ho raha hai.",
    "Abhi aapke phone pe 6 digit OTP aaya hoga, jaldi batao warna account block ho jayega.",
    "Accha OTP nahi mil raha toh YONO app kholo, main bataata hoon kya karna hai.",
    "Haan beta, app khul gaya?",
]


def stub_llms(monkeypatch, calls: list):
    async def fake_analyst(history, previous, recent):
        return analyst.Analysis(scam_type="bank_kyc", risk_score=80)

    async def no_prompt_guard(text):
        return None

    async def no_evidence(text):
        return evidence.Findings()

    async def fake_reply(persona, history, notes=None):
        calls.append((persona, notes))
        return "Uncle, chocolate wala bank hai kya?" if persona == "bunty" else "Arre beta, ruko."

    monkeypatch.setattr(analyst, "run", fake_analyst)
    monkeypatch.setattr(guardrail, "prompt_guard_score", no_prompt_guard)
    monkeypatch.setattr(evidence, "run", no_evidence)
    monkeypatch.setattr(orchestrator, "dadaji_reply", fake_reply)


def test_second_push_passes_the_phone(monkeypatch):
    calls = []
    stub_llms(monkeypatch, calls)

    async def call():
        _, session = new_session("grumpy")
        replies = [await orchestrator.handle_turn(session, text) for text in SCRIPT]
        return session, replies

    session, replies = asyncio.run(call())
    case = session["case"]
    assert replies[1] == "Arre beta, ruko."        # the first push: Dadaji still stalls
    assert replies[2] == PASS_LINE                  # the second: the fixed line, no LLM
    assert [p for p, _ in calls] == ["grumpy", "grumpy", "bunty"]
    assert replies[3] == "Uncle, chocolate wala bank hai kya?"
    assert PASS_NOTE in calls[-1][1][0]             # Bunty knows the earlier replies were Dadaji's

    assert session["persona"] == case.persona == "bunty"
    assert case.phone_passed == {"turn": 3, "source": "rule", "detail": "app kholo", "from": "grumpy"}
    lines = [(m.get("speaker", "Dadaji"), m["text"]) for m in case.transcript if m["role"] == "dadaji"]
    assert lines[2:] == [("Dadaji", PASS_LINE), ("Bunty", PERSONAS["bunty"].pass_greeting),
                         ("Bunty", "Uncle, chocolate wala bank hai kya?")]


def test_bunty_from_the_start_has_no_one_to_pass_to(monkeypatch):
    calls = []
    stub_llms(monkeypatch, calls)

    async def call():
        _, session = new_session("bunty")
        return [await orchestrator.handle_turn(session, text) for text in SCRIPT], session

    replies, session = asyncio.run(call())
    assert PASS_LINE not in replies and session["case"].phone_passed is None


def test_pass_to_bunty_button():
    client = TestClient(app)
    sid = client.post("/api/call/start", json={"persona": "sweet"}).json()["session_id"]
    passed = client.post("/api/call/pass", json={"session_id": sid})
    assert passed.json() == {"persona": "bunty", "line": PASS_LINE,
                             "greeting": PERSONAS["bunty"].pass_greeting}
    case = client.get(f"/api/cases/{sid}").json()["case"]
    assert case["persona"] == "bunty" and case["phone_passed"]["source"] == "button"
    assert client.post("/api/call/pass", json={"session_id": sid}).status_code == 409  # already Bunty
    finale = client.post("/api/call/end", json={"session_id": sid}).json()["case"]["transcript"][-1]
    assert finale["text"] == PERSONAS["bunty"].finale and finale["speaker"] == "Bunty"
    assert client.post("/api/call/pass", json={"session_id": sid}).status_code == 409  # ended


def test_pass_lines_pass_the_guardrail():
    for line in (PASS_LINE, PERSONAS["bunty"].pass_greeting):
        assert check_output(line).problems == [], line
