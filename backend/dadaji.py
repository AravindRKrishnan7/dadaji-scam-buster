"""Dadaji agent: turns the conversation so far into his next reply."""
import re

from backend.llm import chat
from backend.personas import PERSONAS

# Only the most recent messages are sent, to keep prompts small and fast.
MAX_HISTORY = 20
MAX_SENTENCES = 3
# Asking the caller to repeat / speak up. Fine once, tiresome twice in a row.
REPEAT_ASK = re.compile(r"\b(?:phir\s*se|fir\s*se|dobara|repeat|dhee?re|zor\s+se|sunai|awaaz)\b", re.I)


def recent_replies(history: list[dict], n: int) -> list[str]:
    return [m["content"] for m in history if m["role"] == "assistant"][-n:]


def asked_to_repeat(history: list[dict]) -> bool:
    """Did either of Dadaji's last 2 replies ask the caller to repeat or speak up?"""
    return any(REPEAT_ASK.search(r) for r in recent_replies(history, 2))


def variety_note(history: list[dict]) -> str | None:
    """Show him how his last 3 replies began, so he doesn't start the same way again."""
    openings = [" ".join(r.split()[:6]) for r in recent_replies(history, 3)]
    if not openings:
        return None
    return "Your last replies began: " + " | ".join(f'"{o}"' for o in openings) + \
        ". Don't reuse those openings or phrases."


def trim_reply(text: str) -> str:
    """Keep replies phone-short. The model sometimes writes several turns glued together
    ("...khaya?Arey beta..."), so cut at the first such seam, then keep 3 sentences."""
    text = re.split(r"(?<=[.?!…])(?=[A-Z])", text.strip(), maxsplit=1)[0]
    sentences = re.split(r"(?<=[.?!…])\s+", text)
    return " ".join(sentences[:MAX_SENTENCES]).strip()


async def dadaji_reply(persona_key: str, history: list[dict], notes: list[str] | None = None) -> str:
    """history uses OpenAI roles: "user" = scammer, "assistant" = Dadaji.

    notes are one-off instructions for this reply only (a stalling tactic, guardrail feedback),
    sent after the conversation so the model weighs them most.
    """
    persona = PERSONAS[persona_key]
    messages = [{"role": "system", "content": persona.system_prompt}, *history[-MAX_HISTORY:]]
    notes = [*(notes or []), *filter(None, [variety_note(history), persona.reminder])]
    if notes:
        messages.append({"role": "system", "content": "For your next reply only (in your own "
                         "personality): " + " ".join(notes)})
    return trim_reply(await chat(messages, role="dadaji"))
