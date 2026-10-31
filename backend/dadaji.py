"""Dadaji agent: turns the conversation so far into his next reply."""
from backend.llm import chat
from backend.personas import PERSONAS

# Only the most recent messages are sent, to keep prompts small and fast.
MAX_HISTORY = 20


async def dadaji_reply(persona_key: str, history: list[dict]) -> str:
    """history uses OpenAI roles: "user" = scammer, "assistant" = Dadaji."""
    persona = PERSONAS[persona_key]
    messages = [{"role": "system", "content": persona.system_prompt}, *history[-MAX_HISTORY:]]
    return await chat(messages)
