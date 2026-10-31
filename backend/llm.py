"""Shared OpenAI-compatible clients, used by every agent."""
from openai import AsyncOpenAI

from backend import config

_llm_client: AsyncOpenAI | None = None
_groq_client: AsyncOpenAI | None = None


class GroqUnavailable(RuntimeError):
    pass


def get_groq_client() -> AsyncOpenAI:
    """Always Groq, whatever LLM_PROVIDER says: Whisper and Prompt Guard only exist there."""
    global _groq_client
    if _groq_client is None:
        if not config.GROQ_API_KEY:
            raise GroqUnavailable("GROQ_API_KEY is not set in .env.")
        _groq_client = AsyncOpenAI(base_url=config.GROQ_BASE_URL, api_key=config.GROQ_API_KEY)
    return _groq_client


def get_client() -> AsyncOpenAI:
    # Created lazily so the server can start (and show a clear error) without a key.
    global _llm_client
    if config.LLM_PROVIDER == "groq":
        return get_groq_client()
    if _llm_client is None:
        _llm_client = AsyncOpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
    return _llm_client


async def chat_message(messages: list[dict], role: str = "dadaji", temperature: float = 0.8,
                       max_tokens: int = 1024, **kwargs):
    """Call the model for this agent role and return the whole message (for tool calls).

    max_tokens covers hidden reasoning too, so it is generous; prompts keep replies short.
    Extra kwargs (response_format, tools, ...) pass straight through to the API.
    """
    if config.REASONING[role]:
        kwargs.setdefault("reasoning_effort", config.REASONING[role])
    resp = await get_client().chat.completions.create(
        model=config.MODELS[role],
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **kwargs,
    )
    return resp.choices[0].message


async def chat(messages: list[dict], role: str = "dadaji", **kwargs) -> str:
    """Send a list of {role, content} messages and return the reply text."""
    return ((await chat_message(messages, role, **kwargs)).content or "").strip()
