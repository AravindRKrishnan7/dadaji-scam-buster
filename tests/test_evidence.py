"""Evidence regex extractors. Run with: pytest"""
from backend.evidence import Findings, find_banks, find_links, find_phones, find_upi_ids, normalise


def test_phones():
    text = normalise("Call me on +91 98765-43210 or 9123456789, toll free 1800 123 4567.")
    assert find_phones(text) == ["+919876543210", "+919123456789", "18001234567"]


def test_spoken_phone_number():
    text = normalise("number hai nine eight seven six five four three two one zero")
    assert find_phones(text) == ["+919876543210"]


def test_upi_spoken_and_written_but_not_email():
    text = normalise("Send 1 rupee to refund dot desk at the rate okaxis, or pay@ybl. Mail kyc@sbi-help.com")
    assert find_upi_ids(text) == ["refund.desk@okaxis", "pay@ybl"]


def test_links_spoken_and_written():
    text = normalise("Open sbi-kyc dot in or https://bit.ly/x9Kz now, also www.rbi-refund.xyz.")
    assert find_links(text) == ["sbi-kyc.in", "https://bit.ly/x9kz", "www.rbi-refund.xyz"]


def test_links_ignore_email_domains():
    assert find_links(normalise("Mail kyc@sbi-help.com")) == []


def test_banks():
    assert find_banks("SBI head office, PhonePe ya Google Pay se bhejo") == ["SBI", "PhonePe", "Google Pay"]
    assert find_banks("Main abhi bas stand pe hoon") == []
    assert find_banks("Aapke phone pe OTP aaya hoga") == []  # "on your phone", not the app
    assert find_banks("PhonePe se bhejo") == ["PhonePe"]


def test_placeholder_context_values_are_ignored():
    from backend.evidence import EMPTY_VALUES
    assert all(EMPTY_VALUES.match(v) for v in ["None mentioned", "N/A", "unknown", "not specified."])
    assert not EMPTY_VALUES.match("UPI")


def test_findings_dedupe_keeps_first_source():
    f = Findings()
    f.add("phones", ["+919876543210"], "tool")
    f.add("phones", ["+919876543210", "+919123456789"], "regex")
    assert f.phones == [{"value": "+919876543210", "source": "tool"},
                        {"value": "+919123456789", "source": "regex"}]
