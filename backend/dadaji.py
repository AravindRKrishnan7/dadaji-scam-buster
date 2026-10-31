"""Dadaji agent: turns the conversation so far into his next reply."""
import re

from backend.llm import chat
from backend.personas import PERSONAS

# Only the most recent messages are sent, to keep prompts small and fast.
MAX_HISTORY = 20
MAX_SENTENCES = 3


def trim_reply(text: str) -> str:
    """Keep replies phone-short. The model sometimes writes several turns glued together
    ("...khaya?Arey beta..."), so cut at the first such seam, then keep 3 sentences."""
    text = re.split(r"(?<=[.?!…])(?=[A-Z])", text.strip(), maxsplit=1)[0]
    sentences = re.split(r"(?<=[.?!…])\s+", text)
    return " ".join(sentences[:MAX_SENTENCES]).strip()


async def dadaji_reply(persona_key: str, history: list[dict]) -> str:
    """history uses OpenAI roles: "user" = scammer, "assistant" = Dadaji."""
    persona = PERSONAS[persona_key]
    messages = [{"role": "system", "content": persona.system_prompt}, *history[-MAX_HISTORY:]]
    return trim_reply(await chat(messages))
