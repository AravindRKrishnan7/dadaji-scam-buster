"""Case file: everything learned about one call, built up turn by turn.

The dashboard renders it live, db.py saves it, and at the end of the call the reporter
turns it into a complaint.
"""
import time

from pydantic import BaseModel, Field

from backend.analyst import FLOOR_SIGNAL, RISK_FLOOR, SCAM_TYPES, Analysis, FloorHit
from backend.evidence import Findings

EVIDENCE_KINDS = ("phones", "upi_ids", "links", "banks")
SPECIFIC_TYPES = set(SCAM_TYPES) - {"other", "not_scam"}
MAX_RISK_DROP = 5          # per turn, unless the call clearly turns innocent
INNOCENT_RISK = 30         # analyst says not_scam AND risk below this = clearly innocent
INJECTION_RISK_BUMP = 10   # trying to hijack Dadaji is itself a red flag
INJECTION_SIGNAL = "prompt injection attempt"


class CaseFile(BaseModel):
    session_id: str
    persona: str
    started_at: float = Field(default_factory=time.time)  # the handoff: Dadaji picked up
    ended_at: float | None = None            # set by End call; stops the time-wasted timer
    turns: int = 0                           # scammer turns so far
    scam_type: str = "unknown"
    risk_score: int = 0
    risk_history: list[int] = []
    signals: list[str] = []                  # the analyst's latest (cumulative) list
    stall_tactic: str | None = None          # tactic key for Dadaji's latest reply
    stall_note: str | None = None            # ...and the instruction he was given
    tactics_used: list[str] = []
    evidence: dict[str, list[dict]] = Field(
        default_factory=lambda: {kind: [] for kind in (*EVIDENCE_KINDS, "context")})
    injection_attempts: list[dict] = []      # {turn, source, score}
    guardrail_blocks: list[dict] = []        # {turn, draft (redacted), problems}
    timings: dict[str, float] = {}           # seconds per pipeline stage, latest turn
    transcript: list[dict] = []              # {role: "scammer"|"dadaji", text, t}

    def add_message(self, role: str, text: str):
        self.transcript.append({"role": role, "text": text, "t": round(time.time() - self.started_at, 1)})

    def apply_analysis(self, a: Analysis | None, injection: bool = False, floor: FloorHit | None = None):
        """Merge the analyst's latest view into what we already know.

        The analyst only sees recent messages, so one odd answer shouldn't undo the case:
        - a specific scam type is sticky: it can change to another specific type, but not
          fall back to "other";
        - risk drops by at most MAX_RISK_DROP per turn, unless the call clearly turns innocent;
        - an injection attempt raises risk above where it was;
        - the risk floor (analyst.risk_floor: authority claim + demand/threat) keeps risk at
          RISK_FLOOR or more and replaces a non-specific type.
        a is None when the analyst failed this turn.
        """
        prev = self.risk_score
        innocent = (a is not None and a.scam_type == "not_scam" and a.risk_score < INNOCENT_RISK
                    and floor is None)
        risk = prev
        if a is not None:
            if innocent or a.scam_type in SPECIFIC_TYPES or self.scam_type not in SPECIFIC_TYPES:
                self.scam_type = a.scam_type
            risk = a.risk_score if innocent else max(a.risk_score, prev - MAX_RISK_DROP)
            self.signals = list(a.signals)
        if injection:
            risk = max(risk, prev) + INJECTION_RISK_BUMP
        if self.injection_attempts and INJECTION_SIGNAL not in self.signals:
            self.signals.append(INJECTION_SIGNAL)  # stays listed on later turns too
        if floor:
            risk = max(risk, RISK_FLOOR)
            if self.scam_type not in SPECIFIC_TYPES:
                self.scam_type = floor.scam_type
            if FLOOR_SIGNAL not in self.signals:
                self.signals.append(FLOOR_SIGNAL)
        self.risk_score = min(100, risk)
        self.risk_history.append(self.risk_score)

    def add_evidence(self, turn: int, f: Findings):
        for kind in EVIDENCE_KINDS:
            known = {item["value"] for item in self.evidence[kind]}
            self.evidence[kind] += [{**item, "turn": turn} for item in getattr(f, kind)
                                    if item["value"] not in known]
        if f.context:
            self.evidence["context"].append({"turn": turn, **f.context})
