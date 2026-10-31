from backend.dadaji import trim_reply


def test_trim_cuts_glued_turns_and_caps_sentences():
    assert trim_reply("Kaun sa KYC? Khana khaya?Arey, battery low hai.") == "Kaun sa KYC? Khana khaya?"
    assert trim_reply("Ek. Do? Teen! Char.") == "Ek. Do? Teen!"
    assert trim_reply("Ruko beta... chashma kahan gaya.") == "Ruko beta... chashma kahan gaya."


from backend.analyst import ROTATION, pick_tactic
import pytest

from backend.dadaji import REPEAT_ASK, asked_to_repeat, variety_note


def chat(*replies):
    return [m for r in replies for m in ({"role": "user", "content": "OTP batao"},
                                          {"role": "assistant", "content": r})]


def test_asked_to_repeat_covers_the_whole_call():
    assert asked_to_repeat(chat("Thoda phir se boliye beta?", "Chai pi lo pehle."))
    assert asked_to_repeat(chat("Zor se bolo, sunai nahi diya."))
    # the real call: he asked again 3 replies later, which the old 2-reply window let through
    assert asked_to_repeat(chat("Beta dheere se, thoda zor se boliye.", "Chai pi lo.",
                                "Railway mein 1965 mein..."))
    assert not asked_to_repeat(chat("Chai pi lo.", "Railway mein 1965 mein..."))


@pytest.mark.parametrize("reply", [
    "Beta dheere se, thoda zor se boliye.",
    "Kya kaha? Awaaz kat rahi hai.",
    "Ek baar aur bolo beta, saaf nahi suna.",
    "Can you say that again, slowly?",
])
def test_repeat_asks_are_caught(reply):
    assert REPEAT_ASK.search(reply)


@pytest.mark.parametrize("reply", [
    "Dheere dheere chalta hoon beta, ghutne dukhte hain.",
    "Phir baat karte hain, chai aa gayi.",
    "Pappu, tu itna badal gaya, awaaz bhi nahi pehchani.",
    "Ruko, chashma kahan gaya?",
])
def test_other_lines_are_not_repeat_asks(reply):
    assert not REPEAT_ASK.search(reply)


def test_pick_tactic_avoids_repeats():
    assert pick_tactic("lost_glasses", [], False) == "lost_glasses"
    # used in the last 2 turns: rotate instead
    assert pick_tactic("lost_glasses", ["lost_glasses"], False) != "lost_glasses"
    # he already asked them to repeat this call: no hard_of_hearing, even if the analyst wants it
    assert pick_tactic("hard_of_hearing", [], True) != "hard_of_hearing"


def test_pick_tactic_rotates_when_the_analyst_fails():
    picks = [pick_tactic(None, ["x"] * n, False) for n in range(len(ROTATION))]
    assert picks == list(ROTATION)


def test_variety_note_lists_recent_openings():
    assert variety_note([]) is None
    note = variety_note(chat("Arre beta, thoda phir se boliye na, kuch sunai nahi diya."))
    assert '"Arre beta, thoda phir se boliye"' in note
