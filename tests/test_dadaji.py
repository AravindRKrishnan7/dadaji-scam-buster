from backend.dadaji import trim_reply


def test_trim_cuts_glued_turns_and_caps_sentences():
    assert trim_reply("Kaun sa KYC? Khana khaya?Arey, battery low hai.") == "Kaun sa KYC? Khana khaya?"
    assert trim_reply("Ek. Do? Teen! Char.") == "Ek. Do? Teen!"
    assert trim_reply("Ruko beta... chashma kahan gaya.") == "Ruko beta... chashma kahan gaya."
