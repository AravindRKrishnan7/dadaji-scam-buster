"""The awareness card after the call: a static map from scam type to tips. Run with: pytest"""
import re

import pytest
from fastapi.testclient import TestClient

from backend.analyst import SCAM_TYPES
from backend.awareness import CARDS, REPORT_LINE, card_for
from backend.main import app

EMOJI = re.compile("[\U0001F000-\U0001FFFF☀-➿]")


@pytest.mark.parametrize("key", CARDS)
def test_every_card_is_short_and_clean(key):
    card = CARDS[key]
    assert card["title"] and card["how"]
    assert 3 <= len(card["tips"]) <= 4
    for text in (card["title"], card["how"], *card["tips"]):
        assert not EMOJI.search(text), text
        assert len(text) < 260, text


@pytest.mark.parametrize("scam_type,key", [
    ("bank_kyc", "bank_kyc"), ("otp_fraud", "otp_fraud"), ("fake_fine_threat", "fake_fine_threat"),
    ("digital_arrest", "digital_arrest"), ("upi_refund", "upi_refund"),
    ("courier_customs", "digital_arrest"), ("electricity_bill", "fake_fine_threat"),
    ("lottery_prize", "other"), ("not_scam", "other"), ("unknown", "other"),
])
def test_scam_type_picks_a_card(scam_type, key):
    card = card_for(scam_type)
    assert card["key"] == key and card["report"] == REPORT_LINE
    assert "1930" in card["report"] and "cybercrime.gov.in" in card["report"]


def test_every_scam_type_gets_a_card():
    for scam_type in SCAM_TYPES:
        assert card_for(scam_type)["tips"]


def test_end_of_call_includes_the_card():
    client = TestClient(app)
    sid = client.post("/api/call/start", json={"persona": "sweet"}).json()["session_id"]
    ended = client.post("/api/call/end", json={"session_id": sid}).json()
    assert ended["awareness"] == card_for("unknown")  # no scammer turns: the general card
    assert client.get(f"/api/cases/{sid}").json()["awareness"]["key"] == "other"
