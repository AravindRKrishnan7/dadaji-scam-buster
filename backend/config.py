"""Settings read from environment variables (and .env)."""
import os

from dotenv import load_dotenv

load_dotenv()

# Each provider speaks the OpenAI chat API, so only the URL, model and key differ.
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "llama-3.3-70b-versatile",
        "api_key_env": "GROQ_API_KEY",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "gemma3:4b",
        "api_key_env": None,  # Ollama ignores the key, but the client needs one
    },
}

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
if LLM_PROVIDER not in PROVIDERS:
    raise RuntimeError(f"LLM_PROVIDER must be one of {list(PROVIDERS)}, got {LLM_PROVIDER!r}")

_provider = PROVIDERS[LLM_PROVIDER]
LLM_BASE_URL = os.getenv("LLM_BASE_URL", _provider["base_url"])
LLM_MODEL = os.getenv("LLM_MODEL", _provider["model"])
LLM_API_KEY = os.getenv(_provider["api_key_env"]) if _provider["api_key_env"] else "ollama"
