"""Settings read from environment variables (and .env)."""
import os

from dotenv import load_dotenv

load_dotenv()

# Each agent ("role") gets its own model. On Groq's free tier every model has its own
# 8,000 tokens/minute budget, so spreading the agents out avoids rate-limit errors.
ROLES = ("dadaji", "analyst", "evidence")

# Each provider speaks the OpenAI chat API, so only the URL, models and key differ.
# models: role -> (model, reasoning_effort). Reasoning models "think" before answering;
# low/none keeps them fast. None means the parameter is not sent at all.
PROVIDERS = {
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "models": {
            "dadaji": ("openai/gpt-oss-120b", "low"),  # best Hinglish, stays in character
            "analyst": ("openai/gpt-oss-20b", "low"),  # fast JSON classification
            "evidence": ("qwen/qwen3.8-27b", "none"),  # tool calling, no thinking needed
        },
    },
    "ollama": {
        "base_url": "http://localhost:11434/v1",
        "api_key_env": None,  # Ollama ignores the key, but the client needs one
        "models": {role: ("gemma3:4b", None) for role in ROLES},  # Gemma is not a reasoning model
    },
}

LLM_PROVIDER = os.getenv("LLM_PROVIDER", "groq").lower()
if LLM_PROVIDER not in PROVIDERS:
    raise RuntimeError(f"LLM_PROVIDER must be one of {list(PROVIDERS)}, got {LLM_PROVIDER!r}")

_provider = PROVIDERS[LLM_PROVIDER]
LLM_BASE_URL = os.getenv("LLM_BASE_URL", _provider["base_url"])
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_API_KEY = os.getenv(_provider["api_key_env"]) if _provider["api_key_env"] else "ollama"

# Per-role overrides: DADAJI_MODEL, ANALYST_MODEL, EVIDENCE_MODEL (+ *_REASONING_EFFORT;
# set it empty to stop sending it). LLM_MODEL / LLM_REASONING_EFFORT still work for Dadaji.
MODELS: dict[str, str] = {}
REASONING: dict[str, str | None] = {}
for _role, (_model, _effort) in _provider["models"].items():
    _legacy = _role == "dadaji"
    MODELS[_role] = (os.getenv(f"{_role.upper()}_MODEL")
                     or (_legacy and os.getenv("LLM_MODEL")) or _model)
    _effort_env = os.getenv(f"{_role.upper()}_REASONING_EFFORT",
                            os.getenv("LLM_REASONING_EFFORT") if _legacy else None)
    REASONING[_role] = (_effort if _effort_env is None else _effort_env) or None

# Groq's prompt-injection classifier, used by the guardrail on scammer text.
PROMPT_GUARD_MODEL = os.getenv("PROMPT_GUARD_MODEL", "meta-llama/llama-prompt-guard-2-86m")

# Speech-to-text always uses Groq Whisper (Ollama has no Whisper).
GROQ_BASE_URL = os.getenv("STT_BASE_URL", PROVIDERS["groq"]["base_url"])
STT_MODEL = os.getenv("STT_MODEL", "whisper-large-v3-turbo")
