"""Settings read from environment variables (and .env)."""
import os

from dotenv import load_dotenv

load_dotenv()

# Each provider speaks the OpenAI chat API, so only the URL, model and key differ.
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "model": "openai/gpt-oss-120b",
        "api_key_env": "GROQ_API_KEY",
        # gpt-oss "thinks" before answering; low effort keeps replies fast and in character.
        "reasoning_effort": "low",
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "model": "gemma3:4b",
        "api_key_env": None,  # Ollama ignores the key, but the client needs one
        "reasoning_effort": None,  # Gemma is not a reasoning model
    },
}

# Groq's prompt-injection classifier, used by the guardrail on scammer text (milestone 2).
PROMPT_GUARD_MODEL = os.getenv("PROMPT_GUARD_MODEL", "meta-llama/llama-prompt-guard-2-86m")

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
if LLM_PROVIDER not in PROVIDERS:
    raise RuntimeError(f"LLM_PROVIDER must be one of {list(PROVIDERS)}, got {LLM_PROVIDER!r}")

_provider = PROVIDERS[LLM_PROVIDER]
LLM_BASE_URL = os.getenv("LLM_BASE_URL", _provider["base_url"])
LLM_MODEL = os.getenv("LLM_MODEL", _provider["model"])
LLM_API_KEY = os.getenv(_provider["api_key_env"]) if _provider["api_key_env"] else "ollama"
# Set LLM_REASONING_EFFORT= (empty) to stop sending it, e.g. for a non-reasoning model.
LLM_REASONING_EFFORT = os.getenv("LLM_REASONING_EFFORT", _provider["reasoning_effort"]) or None

# Speech-to-text always uses Groq Whisper (Ollama has no Whisper).
STT_BASE_URL = os.getenv("STT_BASE_URL", PROVIDERS["groq"]["base_url"])
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
