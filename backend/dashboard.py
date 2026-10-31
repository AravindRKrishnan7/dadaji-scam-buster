"""Live dashboard hub: pushes the case file to every browser watching a call.

Every message carries the whole case file, so the page simply re-renders.
"""
from fastapi import WebSocket

from backend.case_file import CaseFile

# session_id -> open WebSocket connections watching that call
subscribers: dict[str, set[WebSocket]] = {}


def message(case: CaseFile) -> dict:
    return {"type": "case", "case": case.model_dump()}


async def connect(session_id: str, ws: WebSocket, case: CaseFile):
    await ws.accept()
    subscribers.setdefault(session_id, set()).add(ws)
    await ws.send_json(message(case))  # snapshot, so late joiners and reconnects catch up


def disconnect(session_id: str, ws: WebSocket):
    subscribers.get(session_id, set()).discard(ws)


async def publish(case: CaseFile):
    msg = message(case)
    for ws in list(subscribers.get(case.session_id, ())):
        try:
            await ws.send_json(msg)
        except Exception:  # the browser went away mid-send
            disconnect(case.session_id, ws)
