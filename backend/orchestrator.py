"""Orchestrator: runs one scammer turn through all the agents.

    scammer text ─┬─ evidence (background task, publishes when done) ──────────────┐
                  ├─ guardrail input check ┐ asyncio.gather                        │
                  └─ analyst ──────────────┴─> tactic ─> Dadaji ─> guardrail output ─> reply
Dashboard updates are pushed at each step, and the case file is saved after each turn.
end_call() wraps the call up: it waits for evidence, ends the case, writes the complaint, saves.
"""
import asyncio
import logging
import random
import time

from backend import analyst, dashboard, db, evidence, guardrail, reporter
from backend.dadaji import asked_to_repeat, dadaji_reply, recent_replies
from backend.personas import PERSONAS

log = logging.getLogger("uvicorn.error")

EVIDENCE_WAIT = 2  # seconds end_call() waits for evidence still being collected


async def _analyse(session: dict) -> analyst.Analysis | None:
    try:
        return await analyst.run(session["history"], session["analysis"], session["case"].tactics_used)
    except Exception:
        log.exception("Analyst failed; keeping the previous analysis")
        return None


def _regex_findings(text: str) -> evidence.Findings:
    findings = evidence.Findings()
    for kind, extract in evidence.EXTRACTORS.values():
        findings.add(kind, extract(evidence.normalise(text)), "regex")
    return findings


async def _collect_evidence(case, turn: int, text: str):
    start = time.perf_counter()
    try:
        findings = await evidence.run(text)
    except Exception:
        log.exception("Evidence agent failed; using regexes only")
        findings = _regex_findings(text)
    case.add_evidence(turn, findings)
    case.timings["evidence"] = round(time.perf_counter() - start, 2)
    await dashboard.publish(case)


async def handle_turn(session: dict, text: str) -> str:
    case = session["case"]
    case.turns += 1
    turn = case.turns
    session["history"].append({"role": "user", "content": text})
    case.add_message("scammer", text)
    await dashboard.publish(case)

    # Evidence starts now and runs alongside everything else; Dadaji doesn't wait for it.
    # The session keeps a reference to the task: asyncio only holds weak ones, so an
    # unreferenced task can be garbage-collected before it finishes. end_call() waits on these.
    task = asyncio.create_task(_collect_evidence(case, turn, text))
    session["pending"].add(task)
    task.add_done_callback(session["pending"].discard)

    # The injection check and the analyst run in parallel; Dadaji needs both.
    start = time.perf_counter()
    guard, analysis = await asyncio.gather(guardrail.check_input(text), _analyse(session))
    case.timings["analysis"] = round(time.perf_counter() - start, 2)
    if guard.flagged:
        case.injection_attempts.append({"turn": turn, "source": guard.source, "score": guard.score})
    floor = analyst.risk_floor([m["text"] for m in case.transcript if m["role"] == "scammer"])
    case.apply_analysis(analysis, injection=guard.flagged, floor=floor)
    if analysis:
        # The analyst's next turn should build on the merged (sticky) view, not its raw answer.
        session["analysis"] = analysis.model_copy(
            update={"scam_type": case.scam_type, "risk_score": case.risk_score, "signals": case.signals})
    repeated = asked_to_repeat(session["history"])
    if guard.flagged:
        tactic = "baffled_by_jargon"
    else:
        tactic = analyst.pick_tactic(analysis.stall_tactic if analysis else None,
                                     case.tactics_used, repeated)
    case.stall_tactic = tactic
    case.stall_note = analyst.TACTICS[tactic][1]
    case.tactics_used.append(tactic)
    await dashboard.publish(case)

    persona = PERSONAS[session["persona"]]
    note = analyst.tactic_note(tactic)
    if repeated:
        note += " Don't ask them to repeat or speak up this time."
    # Canned lines he said recently are skipped, so a run of failures doesn't loop one line.
    recent = recent_replies(session["history"], 3)
    fallbacks = tuple(f for f in persona.fallbacks if f not in recent) or persona.fallbacks
    start = time.perf_counter()
    try:
        # The guardrail cleans and checks the draft, retrying once before a canned stall line.
        reply, blocks = await guardrail.safe_reply(
            lambda feedback: dadaji_reply(session["persona"], session["history"],
                                          [note] + ([feedback] if feedback else [])),
            fallbacks,
        )
    except Exception:
        # Rate limit or network error: stay in character instead of breaking the call.
        log.exception("Dadaji failed; using a fallback line")
        reply, blocks = random.choice(fallbacks), []
    case.timings["dadaji"] = round(time.perf_counter() - start, 2)
    case.guardrail_blocks += [{"turn": turn, **b} for b in blocks]

    session["history"].append({"role": "assistant", "content": reply})
    case.add_message("dadaji", reply)
    await dashboard.publish(case)
    await _save(case)
    log.info("turn %d: %s", turn, case.timings)
    return reply


async def _save(case, report: dict | None = None):
    try:
        await db.save(case, report)
    except Exception:  # a full disk shouldn't end the call; the case is still in memory
        log.exception("Saving case %s failed", case.session_id)


async def end_call(session: dict):
    case = session["case"]
    case.ended_at = time.time()  # first, so the timer stops at the moment End call was pressed
    # The browser speaks the finale itself (no waiting); it's recorded here for the transcript.
    case.add_message("dadaji", PERSONAS[session["persona"]].finale)
    if session["pending"]:
        _, late = await asyncio.wait(session["pending"], timeout=EVIDENCE_WAIT)
        if late:
            # The evidence agent is slow (rate-limited?). Run the regex net over everything the
            # scammer said, so the complaint still gets the numbers and IDs.
            log.warning("%d evidence task(s) still running at end of call; using regexes", len(late))
            said = [m["text"] for m in case.transcript if m["role"] == "scammer"]
            for turn, text in enumerate(said, start=1):
                case.add_evidence(turn, _regex_findings(text))
    await dashboard.publish(case)
    session["report"] = (await reporter.build(case)).model_dump()
    await _save(case, session["report"])
