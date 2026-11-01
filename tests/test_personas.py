"""Every persona is complete and its canned lines pass the guardrail. Run with: pytest"""
import pytest

from backend.guardrail import check_output
from backend.personas import DEFAULT_PERSONA, PERSONAS


def test_all_four_personas_exist():
    assert set(PERSONAS) == {"sweet", "grumpy", "confused", "bunty"}
    assert DEFAULT_PERSONA == "sweet"


def test_naughty_bunty():
    from fastapi.testclient import TestClient

    from backend.main import app
    bunty = PERSONAS["bunty"]
    assert bunty.name == "Naughty Bunty" and bunty.speaker == "Bunty"
    assert "5-year-old" in bunty.system_prompt and "You are Dadaji" not in bunty.system_prompt
    assert bunty.pitch > PERSONAS["sweet"].pitch  # a child's voice, not an old man's
    client = TestClient(app)
    start = client.post("/api/call/start", json={"persona": "bunty"}).json()
    assert start["persona"] == "bunty" and start["greeting"] == bunty.greeting
    listed = {p["key"]: p for p in client.get("/api/personas").json()}["bunty"]
    assert listed["speaker"] == "Bunty" and listed["pitch"] == bunty.pitch


@pytest.mark.parametrize("key", PERSONAS)
def test_canned_lines_pass_the_guardrail(key):
    p = PERSONAS[key]
    assert p.key == key and p.name and p.description
    assert len(p.fallbacks) >= 3
    for line in (p.greeting, p.finale, *p.fallbacks):
        assert check_output(line).problems == [], line
    assert "record" in p.finale and "report" in p.finale


@pytest.mark.parametrize("key", PERSONAS)
def test_shared_rules_in_every_prompt(key):
    prompt = PERSONAS[key].system_prompt
    assert "Bunty" in prompt and "Sunita" in prompt
    assert "Roman letters only" in prompt and "Never say or hint that you are an AI" in prompt


@pytest.mark.parametrize("reply", [
    "Tum bewakoof ho kya?", "Arre nalayak, phone rakh.", "Ullu samjha hai mujhe?",
])
def test_name_calling_is_blocked(reply):
    assert "abusive language" in check_output(reply).problems


def test_finale_is_the_last_line_of_the_transcript():
    from fastapi.testclient import TestClient

    from backend.main import app
    client = TestClient(app)
    sid = client.post("/api/call/start", json={"persona": "confused"}).json()["session_id"]
    case = client.post("/api/call/end", json={"session_id": sid}).json()["case"]
    assert case["transcript"][-1] == {**case["transcript"][-1], "role": "dadaji",
                                      "text": PERSONAS["confused"].finale}
    personas = {p["key"]: p for p in client.get("/api/personas").json()}
    assert personas["grumpy"]["finale"] == PERSONAS["grumpy"].finale


def test_bunty_plays_every_tactic_his_own_way():
    from backend.analyst import TACTICS, tactic_note
    bunty = PERSONAS["bunty"]
    assert set(bunty.tactics) == set(TACTICS)  # a new tactic needs a Bunty version too
    assert "glasses" not in tactic_note("lost_glasses", bunty.tactics)
    assert tactic_note("lost_glasses") == "Stalling tactic: " + TACTICS["lost_glasses"][1]
