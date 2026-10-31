"""FastAPI app: serves the front end and the chat API."""
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend import config
from backend.dadaji import dadaji_reply
from backend.personas import DEFAULT_PERSONA, PERSONAS

log = logging.getLogger("uvicorn.error")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Dadaji Scam Buster")

# In-memory sessions: session_id -> {"persona": key, "history": [messages]}.
# Lost on restart; case files move to SQLite in a later milestone.
sessions: dict[str, dict] = {}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    persona: str = DEFAULT_PERSONA


class ChatResponse(BaseModel):
    session_id: str
    persona: str
    reply: str


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "provider": config.LLM_PROVIDER, "model": config.LLM_MODEL}


@app.get("/api/personas")
def list_personas():
    return [{"key": p.key, "name": p.name, "description": p.description} for p in PERSONAS.values()]


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    # Reuse the session if the client sent a known id, otherwise start a new call.
    session = sessions.get(req.session_id or "")
    if session is None:
        if req.persona not in PERSONAS:
            raise HTTPException(400, f"Unknown persona {req.persona!r}")
        session_id = str(uuid.uuid4())
        session = sessions[session_id] = {"persona": req.persona, "history": []}
    else:
        session_id = req.session_id

    session["history"].append({"role": "user", "content": req.message})
    try:
        reply = await dadaji_reply(session["persona"], session["history"])
    except Exception as e:
        session["history"].pop()  # drop the unanswered message so a retry is clean
        log.exception("LLM call failed")
        raise HTTPException(502, f"LLM error: {e}")
    session["history"].append({"role": "assistant", "content": reply})

    return ChatResponse(session_id=session_id, persona=session["persona"], reply=reply)
