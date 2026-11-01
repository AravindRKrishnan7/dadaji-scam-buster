"""FastAPI app: serves the front end and the chat API."""
import asyncio
import logging
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import awareness, config, dashboard, db, orchestrator, reporter, stt
from backend.case_file import CaseFile
from backend.llm import GroqUnavailable
from backend.personas import DEFAULT_PERSONA, PASS_TO, PERSONAS

MAX_AUDIO_BYTES = 5 * 1024 * 1024  # a 20 s clip is well under 1 MB

log = logging.getLogger("uvicorn.error")
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

app = FastAPI(title="Dadaji Scam Buster")
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# Live calls: session_id -> {"persona", "history" (LLM messages), "analysis", "case",
# "pending" (evidence tasks), "ending" (the end-of-call task), "report" (the complaint)}. Lost on restart, but every
# case file is also saved to SQLite (db.py), so finished cases can still be loaded.
sessions: dict[str, dict] = {}


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    session_id: str | None = None
    persona: str = DEFAULT_PERSONA


class ChatResponse(BaseModel):
    session_id: str
    persona: str
    reply: str = ""
    hangup: bool = False  # the scammer is giving up: the browser plays the finale and ends the call
    passed: dict | None = None  # Dadaji passed the phone: {persona, line, greeting}; reply is the line


class CallStartRequest(BaseModel):
    persona: str = DEFAULT_PERSONA


class CallStartResponse(BaseModel):
    session_id: str
    persona: str
    greeting: str


class CallEndRequest(BaseModel):
    session_id: str


class CallPassRequest(BaseModel):
    session_id: str


def new_session(persona: str) -> tuple[str, dict]:
    if persona not in PERSONAS:
        raise HTTPException(400, f"Unknown persona {persona!r}")
    session_id = str(uuid.uuid4())
    sessions[session_id] = {"persona": persona, "history": [], "analysis": None,
                            "case": CaseFile(session_id=session_id, persona=persona),
                            "pending": set()}
    return session_id, sessions[session_id]


@app.get("/")
def index():
    return FileResponse(FRONTEND_DIR / "index.html")


@app.get("/api/health")
def health():
    return {"ok": True, "provider": config.LLM_PROVIDER, "models": config.MODELS}


@app.get("/api/personas")
def list_personas():
    return [{"key": p.key, "name": p.name, "description": p.description, "finale": p.finale,
             "speaker": p.speaker, "rate": p.rate, "pitch": p.pitch}
            for p in PERSONAS.values()]


@app.post("/api/call/start", response_model=CallStartResponse)
def call_start(req: CallStartRequest):
    """The handoff: Dadaji picks up. His greeting goes into history so the LLM knows he said it."""
    session_id, session = new_session(req.persona)
    greeting = PERSONAS[req.persona].greeting
    session["history"].append({"role": "assistant", "content": greeting})
    session["case"].add_message("dadaji", greeting, PERSONAS[req.persona].speaker)
    return CallStartResponse(session_id=session_id, persona=req.persona, greeting=greeting)


@app.post("/api/chat", response_model=ChatResponse)
async def chat_endpoint(req: ChatRequest):
    # Reuse the session if the client sent a known id, otherwise start a new call.
    session = sessions.get(req.session_id or "")
    if session is None:
        session_id, session = new_session(req.persona)
    else:
        session_id = req.session_id
    if session["case"].ended_at is not None:
        raise HTTPException(409, "This call has ended. Start a new one.")

    # All the agents run here; failures fall back to in-character lines instead of errors.
    reply = await orchestrator.handle_turn(session, req.message)
    return ChatResponse(session_id=session_id, persona=session["persona"],
                        reply=reply or "", hangup=reply is None, passed=session.pop("passed", None))


@app.post("/api/call/pass")
async def call_pass(req: CallPassRequest):
    """The "Pass to Bunty" button: the same pass the rule makes, by hand."""
    session = sessions.get(req.session_id)
    if session is None:
        raise HTTPException(404, "Unknown call (the server may have restarted).")
    if session["case"].ended_at is not None:
        raise HTTPException(409, "This call has ended.")
    if session["persona"] == PASS_TO:
        raise HTTPException(409, "Bunty already has the phone.")
    return await orchestrator.pass_phone(session, "button", "Pass to Bunty")


@app.post("/api/call/end")
async def call_end(req: CallEndRequest):
    """Hang up: stop the timer, write the complaint and save everything."""
    session = sessions.get(req.session_id)
    if session is None:
        raise HTTPException(404, "Unknown call (the server may have restarted).")
    # A double click sends two requests; both wait for the same single end-of-call task.
    if "ending" not in session:
        session["ending"] = asyncio.create_task(orchestrator.end_call(session))
    await session["ending"]
    case = session["case"]
    return {"case": case.model_dump(), "report": session["report"],
            "awareness": awareness.card_for(case.scam_type)}


async def find_case(session_id: str) -> tuple[CaseFile, dict | None]:
    """A live call from memory, otherwise a saved one from SQLite (e.g. after a restart)."""
    if session_id in sessions:
        return sessions[session_id]["case"], sessions[session_id].get("report")
    saved = await db.load(session_id)
    if saved is None:
        raise HTTPException(404, "Unknown case")
    return saved


def download(name: str) -> dict:
    return {"Content-Disposition": f'attachment; filename="{name}"'}  # "save as" instead of opening


@app.get("/api/cases/{session_id}")
async def get_case(session_id: str):
    case, report = await find_case(session_id)
    return {"case": case.model_dump(), "report": report, "awareness": awareness.card_for(case.scam_type)}


@app.get("/api/cases/{session_id}/report")
async def get_report(session_id: str, format: str = "json", attach: bool = True):
    """The complaint as .json or .txt. attach=false shows it in the page instead (Copy all)."""
    case, report = await find_case(session_id)
    if report is None:
        raise HTTPException(409, "The complaint is written when the call ends.")
    name = f"dadaji-complaint-{session_id[:8]}.{format}"
    headers = download(name) if attach else None
    if format == "txt":
        return PlainTextResponse(reporter.to_text(report), headers=headers)
    if format == "json":
        return JSONResponse(report, headers=headers)
    raise HTTPException(400, "format must be json or txt")


@app.get("/api/cases/{session_id}/transcript")
async def get_transcript(session_id: str):
    """Plain-text transcript, to attach to the complaint as evidence."""
    case, _ = await find_case(session_id)
    return PlainTextResponse(reporter.transcript_text(case),
                             headers=download(f"dadaji-transcript-{session_id[:8]}.txt"))


@app.get("/api/stats")
async def stats():
    """Running total across every saved call, shown under the timer."""
    return await db.stats()


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
