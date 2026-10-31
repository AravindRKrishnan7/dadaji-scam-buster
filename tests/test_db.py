"""SQLite storage and the end-of-call route. Run with: pytest"""
from fastapi.testclient import TestClient

from backend import db
from backend.case_file import CaseFile


def sample_case(session_id="s1", started=1000.0, ended=None, turns=3) -> CaseFile:
    case = CaseFile(session_id=session_id, persona="sweet", started_at=started, ended_at=ended,
                    turns=turns, scam_type="otp_fraud", risk_score=85, risk_history=[20, 85])
    case.evidence["upi_ids"].append({"value": "refund.desk@okaxis", "source": "tool", "turn": 3})
    case.add_message("scammer", "OTP batao jaldi")
    return case


def test_round_trip():
    case = sample_case()
    db.save_sync(case)
    loaded, report = db.load_sync("s1")
    assert loaded == case
    assert report is None
    assert db.load_sync("missing") is None


def test_update_keeps_report_unless_replaced():
    case = sample_case()
    db.save_sync(case, {"title": "complaint"})
    case.turns = 4
    db.save_sync(case)  # a later save without a report must not wipe it
    loaded, report = db.load_sync("s1")
    assert loaded.turns == 4
    assert report == {"title": "complaint"}


def test_stats_count_only_ended_calls_with_turns():
    db.save_sync(sample_case("a", started=1000, ended=1250))           # 250 s
    db.save_sync(sample_case("b", started=2000, ended=2090))           # 90 s
    db.save_sync(sample_case("c", started=3000, ended=None))           # still going
    db.save_sync(sample_case("d", started=4000, ended=4500, turns=0))  # scammer never spoke
    assert db.stats_sync() == {"calls": 2, "seconds": 340}


def test_end_call_route():
    from backend.main import app
    client = TestClient(app)
    sid = client.post("/api/call/start", json={}).json()["session_id"]
    first = client.post("/api/call/end", json={"session_id": sid}).json()
    again = client.post("/api/call/end", json={"session_id": sid}).json()
    assert first["case"]["ended_at"] is not None
    assert again["case"]["ended_at"] == first["case"]["ended_at"]  # ending twice changes nothing
    assert client.post("/api/chat", json={"message": "hello", "session_id": sid}).status_code == 409
    assert db.load_sync(sid)[0].ended_at == first["case"]["ended_at"]
    assert client.get(f"/api/cases/{sid}").json()["case"]["session_id"] == sid
    assert client.post("/api/call/end", json={"session_id": "nope"}).status_code == 404
