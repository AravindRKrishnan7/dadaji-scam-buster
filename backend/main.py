"""FastAPI app: serves the front end and the chat API."""
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from backend import config, dashboard, orchestrator, stt
from backend.case_file import CaseFile
from backend.llm import GroqUnavailable
from backend.personas import DEFAULT_PERSONA, PERSONAS

MAX_AUDIO_BYTES = 5 * 1024 * 1024  # a 20 s clip is well under 1 MB

log = logging.getLogger("uvicorn.error")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Dadaji Scam Buster")

# In-memory sessions: session_id -> {"persona", "history" (LLM messages), "analysis", "case"}.
# Lost on restart; case files move to SQLite in milestone 4.
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
    sessions[session_id] = {"persona": persona, "history": [], "analysis": None,
                            "case": CaseFile(session_id=session_id, persona=persona)}
    return session_id, sessions[session_id]


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "provider": config.LLM_PROVIDER, "models": config.MODELS}


@app.get("/api/personas")
def list_personas():
    return [{"key": p.key, "name": p.name, "description": p.description} for p in PERSONAS.values()]


@app.post("/api/call/start", response_model=CallStartResponse)
def call_start(req: CallStartRequest):
    """The handoff: Dadaji picks up. His greeting goes into history so the LLM knows he said it."""
    session_id, session = new_session(req.persona)
    greeting = PERSONAS[req.persona].greeting
    session["history"].append({"role": "assistant", "content": greeting})
    session["case"].add_message("dadaji", greeting)
    return CallStartResponse(session_id=session_id, persona=req.persona, greeting=greeting)


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    # Reuse the session if the client sent a known id, otherwise start a new call.
    session = sessions.get(req.session_id or "")
    if session is None:
        session_id, session = new_session(req.persona)
    else:
        session_id = req.session_id

    # All the agents run here; failures fall back to in-character lines instead of errors.
    reply = await orchestrator.handle_turn(session, req.message)
    return ChatResponse(session_id=session_id, persona=session["persona"], reply=reply)


@app.post("/api/transcribe")
async def transcribe_endpoint(audio: UploadFile):
    data = await audio.read()
    if len(data) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "Audio clip too large (max 5 MB)")
    try:
        text = await stt.transcribe(data, audio.filename or "clip.webm", audio.content_type or "audio/webm")
    except GroqUnavailable as e:
        raise HTTPException(503, f"{e} Voice needs it. You can still type.")
    except Exception as e:
        log.exception("Transcription failed")
        raise HTTPException(502, f"Transcription error: {e}")
    return {"text": text}


@app.websocket("/ws/{session_id}")
async def dashboard_ws(ws: WebSocket, session_id: str):
    """The dashboard listens here. The server only pushes; nothing is expected back."""
    session = sessions.get(session_id)
    if session is None:
        await ws.close(code=4404)
        return
    await dashboard.connect(session_id, ws, session["case"])
    try:
        while True:
            await ws.receive_text()  # just keeps the connection open until the browser leaves
    except WebSocketDisconnect:
        pass
    finally:
        dashboard.disconnect(session_id, ws)
