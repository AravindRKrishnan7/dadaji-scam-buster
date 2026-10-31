"""Case file: everything learned about one call, built up turn by turn.

The dashboard renders it live; in milestone 4 the reporter turns it into a complaint.
"""
import time

from pydantic import BaseModel, Field

from backend.analyst import Analysis
from backend.evidence import Findings

EVIDENCE_KINDS = ("phones", "upi_ids", "links", "banks")


class CaseFile(BaseModel):
    session_id: str
    persona: str
    started_at: float = Field(default_factory=time.time)
    turns: int = 0                           # scammer turns so far
    scam_type: str = "unknown"
    risk_score: int = 0
    risk_history: list[int] = []
    signals: list[str] = []                  # the analyst's latest (cumulative) list
    stall_tactic: str | None = None          # the director's note for Dadaji's latest reply
    tactics_used: list[str] = []
    evidence: dict[str, list[dict]] = Field(
        default_factory=lambda: {kind: [] for kind in (*EVIDENCE_KINDS, "context")})
    injection_attempts: list[dict] = []      # {turn, source, score}
    guardrail_blocks: list[dict] = []        # {turn, draft (redacted), problems}
    timings: dict[str, float] = {}           # seconds per pipeline stage, latest turn
    transcript: list[dict] = []              # {role: "scammer"|"dadaji", text, t}

    def add_message(self, role: str, text: str):
        self.transcript.append({"role": role, "text": text, "t": round(time.time() - self.started_at, 1)})

    def apply_analysis(self, a: Analysis):
        self.scam_type = a.scam_type
        self.risk_score = a.risk_score
        self.risk_history.append(a.risk_score)
        self.signals = a.signals

    def add_evidence(self, turn: int, f: Findings):
        for kind in EVIDENCE_KINDS:
            known = {item["value"] for item in self.evidence[kind]}
            self.evidence[kind] += [{**item, "turn": turn} for item in getattr(f, kind)
                                    if item["value"] not in known]
        if f.context:
            self.evidence["context"].append({"turn": turn, **f.context})
