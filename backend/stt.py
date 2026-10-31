"""Speech-to-text with Groq Whisper.

Uses its own client because Ollama has no Whisper: even in offline LLM mode,
voice needs a Groq key (otherwise the UI falls back to typing).
"""
import os
import re

from openai import AsyncOpenAI

from backend import config

# A hint nudges Whisper towards Romanized Hinglish and scam vocabulary.
PROMPT_HINT = "Phone call in Hinglish about bank, KYC, OTP, UPI, Paytm, account, card."
# Whisper invents these for silence or noise. Groq's no_speech_prob is always 0, so we match
# the whole transcript against known phrases instead. The browser also skips quiet clips.
HALLUCINATIONS = {
    "thank you", "thank you very much", "thanks for watching", "thank you for watching",
    "you", "please subscribe", "subtitles by the amara.org community",
}

_client: AsyncOpenAI | None = None


class STTUnavailable(RuntimeError):
    pass


def get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        key = os.getenv("GROQ_API_KEY")
        if not key:
            raise STTUnavailable("Voice needs GROQ_API_KEY in .env. You can still type.")
        _client = AsyncOpenAI(base_url=config.STT_BASE_URL, api_key=key)
    return _client


async def transcribe(audio: bytes, filename: str, content_type: str) -> str:
    resp = await get_client().audio.transcriptions.create(
        model=config.STT_MODEL,
        file=(filename, audio, content_type),
        prompt=PROMPT_HINT,
        temperature=0,
    )
    text = (resp.text or "").strip()
    if re.sub(r"[^\w\s.]", "", text).strip(" .").lower() in HALLUCINATIONS:
        return ""
    return text
