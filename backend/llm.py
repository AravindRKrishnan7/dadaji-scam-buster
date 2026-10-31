"""One shared OpenAI-compatible client, used by every agent."""
from openai import AsyncOpenAI

from backend import config

_client: AsyncOpenAI | None = None


def get_client() -> AsyncOpenAI:
    # Created lazily so the server can start (and show a clear error) without a key.
    global _client
    if _client is None:
        if not config.LLM_API_KEY:
            raise RuntimeError("GROQ_API_KEY is not set. Add it to .env or use LLM_PROVIDER=ollama.")
        _client = AsyncOpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)
    return _client


async def chat(messages: list[dict], temperature: float = 0.8, max_tokens: int = 1024) -> str:
    """Send a list of {role, content} messages and return the reply text."""
    # max_tokens covers hidden reasoning too, so it is generous; the prompt keeps replies short.
    extra = {"reasoning_effort": config.LLM_REASONING_EFFORT} if config.LLM_REASONING_EFFORT else {}
    resp = await get_client().chat.completions.create(
        model=config.LLM_MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        **extra,
    )
    return (resp.choices[0].message.content or "").strip()
