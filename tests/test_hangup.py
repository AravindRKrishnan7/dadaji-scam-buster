"""Auto-finale: the scammer giving up (a phrase, or the analyst's flag) ends the call."""
import asyncio

import pytest

from backend import analyst, evidence, guardrail, orchestrator
from backend.analyst import HANGUP_SIGNAL, Analysis, hangup_phrase
from backend.main import new_session

# The real call that should have ended itself (Whisper's spelling kept as it came out).
REAL_LINES = [
    "Aray yaar, bevaku fora, main phone cut kar raha hoon",
    "TK, bye bye, you are stupid, bye",
]


@pytest.mark.parametrize("text", REAL_LINES + [
    "Main phone rakh raha hoon.",
    "Chhodo yaar!",
    "Aap mera time waste kar rahe ho",
    "Bewakoof buddhe, timepass mat karo",
    "Ok I'm hanging up now",
])
def test_giving_up_is_detected(text):
    assert hangup_phrase(text)


@pytest.mark.parametrize("text", [
    "Namaste uncle, main SBI head office se bol raha hoon.",
    "Call cut mat karna, warna account block ho jayega.",
    "Phone band mat kijiye sir, ek minute.",
    "Main aapko hold pe rakh raha hoon.",
    "Time waste mat karo, jaldi OTP batao.",
    "Chhodo yeh sab, OTP batao.",
    "Please don't hang up sir, this is urgent.",
])
def test_scam_talk_is_not_giving_up(text):
    assert not hangup_phrase(text)


def test_analyst_flag_is_strict():
    assert Analysis(hanging_up=True).hanging_up
    assert Analysis(hanging_up="true").hanging_up
    assert not Analysis(hanging_up="maybe").hanging_up
    assert not Analysis(hanging_up=None).hanging_up


def run_call(monkeypatch, script, flags):
    """Stub every LLM call; flags[i] is the analyst's hanging_up answer for turn i."""
    answers = iter(flags)
    dadaji_calls = []

    async def fake_analyst(*a):
        return Analysis(scam_type="bank_kyc", risk_score=60, hanging_up=next(answers))

    async def none(*a, **k):
        return None

    async def no_evidence(text):
        return evidence.Findings()

    async def fake_dadaji(*a, **k):
        dadaji_calls.append(a)
        return "Arre beta, chashma kahan gaya?"

    monkeypatch.setattr(analyst, "run", fake_analyst)
    monkeypatch.setattr(guardrail, "prompt_guard_score", none)
    monkeypatch.setattr(evidence, "run", no_evidence)
    monkeypatch.setattr(orchestrator, "dadaji_reply", fake_dadaji)

    async def call():
        _, session = new_session("sweet")
        replies = [await orchestrator.handle_turn(session, text) for text in script]
        await orchestrator.end_call(session)
        return session, replies, dadaji_calls

    return asyncio.run(call())


@pytest.mark.parametrize("line", REAL_LINES)
def test_real_lines_trigger_the_finale(monkeypatch, line):
    script = ["Main SBI se bol raha hoon, aapka KYC expire ho gaya hai.", line]
    session, replies, dadaji_calls = run_call(monkeypatch, script, [False, False])
    case = session["case"]
    assert replies[0] and replies[1] is None  # no Dadaji reply: straight to the finale
    assert len(dadaji_calls) == 1
    assert case.hangup["turn"] == 2 and case.hangup["source"] == "phrase"
    assert HANGUP_SIGNAL in case.signals
    # end_call() still runs as for End call: finale line, complaint, ended_at
    assert case.transcript[-1]["text"].startswith("Beta, ek baat bataun?")
    assert case.ended_at and session["report"]


def test_analyst_flag_triggers_the_finale(monkeypatch):
    script = ["Main SBI se bol raha hoon.", "Theek hai uncle, aap rehne do, main kal dekhta hoon."]
    session, replies, _ = run_call(monkeypatch, script, [False, True])
    assert replies[1] is None and session["case"].hangup["source"] == "analyst"


def test_second_repeat_ask_is_blocked(monkeypatch):
    """Once he has asked them to repeat, a draft asking again is blocked and retried."""
    drafts = iter(["Beta dheere se, thoda zor se boliye.",   # turn 1: the one allowed ask
                   "Kya kaha? Phir se bolo beta.",            # turn 2: blocked
                   "Arre, chai ubal gayi, ek minute ruko."])   # turn 2, retry
    run_call(monkeypatch, [], [])  # install the stubs, then swap in scripted drafts

    async def scripted(*a, **k):
        return next(drafts)

    monkeypatch.setattr(orchestrator, "dadaji_reply", scripted)
    monkeypatch.setattr(analyst, "run", lambda *a: asyncio.sleep(0, Analysis()))

    async def call():
        _, session = new_session("sweet")
        replies = [await orchestrator.handle_turn(session, t) for t in ("KYC update karo", "OTP batao")]
        return session["case"], replies

    case, replies = asyncio.run(call())
    assert replies[1] == "Arre, chai ubal gayi, ek minute ruko."
    assert case.guardrail_blocks[0]["problems"] == ["asked them to repeat again"]
