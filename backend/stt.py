"""Speech-to-text with Groq Whisper.

Always uses the Groq client because Ollama has no Whisper: even in offline LLM mode,
voice needs a Groq key (otherwise the UI falls back to typing).

The language is fixed to Hindi: left to guess, Whisper sometimes wrote Hinglish in Urdu
script. Hindi it may write in Devanagari, so transcripts are romanised (translit.py).
"""
import re

from backend import config
from backend.llm import get_groq_client
from backend.translit import to_roman

LANGUAGE = "hi"
# Whisper reads the prompt as "the transcript so far", so it's written the way we want the
# output: Roman Hinglish, with the scam words it should spell right.
PROMPT_HINT = ("Hello Dadaji, main bank se bol raha hoon. Aapka KYC, OTP, UPI, account, "
               "fine sab check karna hai. Haan beta.")
MIN_CHARS = 3  # shorter than this ("ha", "hm") is noise, not a turn
# Whisper invents these for silence or noise. Groq's no_speech_prob is always 0, so we match
# the whole transcript against known phrases instead. The browser also skips quiet clips.
HALLUCINATIONS = {
    "thank you", "thank you very much", "thanks for watching", "thank you for watching",
    "you", "please subscribe", "subtitles by the amara.org community",
}


async def transcribe(audio: bytes, filename: str, content_type: str) -> str:
    resp = await get_groq_client().audio.transcriptions.create(
        model=config.STT_MODEL,
        file=(filename, audio, content_type),
        language=LANGUAGE,
        prompt=PROMPT_HINT,
        temperature=0,
    )
    return clean_transcript(resp.text or "")


def clean_transcript(text: str) -> str:
    """Romanise, then drop Whisper's silence phrases and anything too short to be a turn."""
    text = to_roman(text).strip()
    if re.sub(r"[^\w\s.]", "", text).strip(" .").lower() in HALLUCINATIONS:
        return ""
    if len(re.sub(r"\s", "", text)) < MIN_CHARS:
        return ""
    return text
