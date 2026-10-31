"""FastAPI app: serves the front end and the chat API."""
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend import config, stt
from backend.dadaji import dadaji_reply
from backend.personas import DEFAULT_PERSONA, PERSONAS

MAX_AUDIO_BYTES = 5 * 1024 * 1024  # a 20 s clip is well under 1 MB

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


class CallStartRequest(BaseModel):
    persona: str = DEFAULT_PERSONA


class CallStartResponse(BaseModel):
    session_id: str
    persona: str
    greeting: str


def new_session(persona: str) -> tuple[str, dict]:
    if persona not in PERSONAS:
        raise HTTPException(400, f"Unknown persona {persona!r}")
    session_id = str(uuid.uuid4())
    sessions[session_id] = {"persona": persona, "history": []}
    return session_id, sessions[session_id]


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "provider": config.LLM_PROVIDER, "model": config.LLM_MODEL}


@app.get("/api/personas")
def list_personas():
    return [{"key": p.key, "name": p.name, "description": p.description} for p in PERSONAS.values()]


@app.post("/api/call/start", response_model=CallStartResponse)
def call_start(req: CallStartRequest):
    """The handoff: Dadaji picks up. His greeting goes into history so the LLM knows he said it."""
    session_id, session = new_session(req.persona)
    greeting = PERSONAS[req.persona].greeting
    session["history"].append({"role": "assistant", "content": greeting})
    return CallStartResponse(session_id=session_id, persona=req.persona, greeting=greeting)


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    # Reuse the session if the client sent a known id, otherwise start a new call.
    session = sessions.get(req.session_id or "")
    if session is None:
        session_id, session = new_session(req.persona)
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


@app.post("/api/transcribe")
async def transcribe_endpoint(audio: UploadFile):
    data = await audio.read()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio clip too large (max 5 MB)")
    try:
        text = await stt.transcribe(data, audio.filename or "clip.webm", audio.content_type or "audio/webm")
    except stt.STTUnavailable as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        log.exception("Transcription failed")
        raise HTTPException(502, f"Transcription error: {e}")
    return {"text": text}
