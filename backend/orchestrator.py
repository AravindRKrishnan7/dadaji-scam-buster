"""Orchestrator: runs one scammer turn through all the agents.

    scammer text ─┬─ evidence (background task, publishes when done) ──────────────┐
                  ├─ guardrail input check ┐ asyncio.gather                        │
                  └─ analyst ──────────────┴─> tactic ─> Dadaji ─> guardrail output ─> reply
Dashboard updates are pushed at each step, and the case file is saved after each turn.
If the scammer is giving up (a phrase, or the analyst's hanging_up flag), Dadaji doesn't reply:
handle_turn() returns None and the browser plays the finale and calls end_call().
end_call() wraps the call up: it waits for evidence, ends the case, writes the complaint, saves.
"""
import asyncio
import logging
import random
import time

from backend import analyst, dashboard, db, evidence, guardrail, reporter
from backend.dadaji import REPEAT_ASK, asked_to_repeat, dadaji_reply, recent_replies
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


async def _caller_left(case, turn: int, source: str, detail: str) -> None:
    case.hangup = {"turn": turn, "source": source, "detail": detail}
    if analyst.HANGUP_SIGNAL not in case.signals:
        case.signals.append(analyst.HANGUP_SIGNAL)
    await dashboard.publish(case)
    await _save(case)
    log.info("turn %d: the scammer is giving up (%s: %s)", turn, source, detail)
    return None


async def handle_turn(session: dict, text: str) -> str | None:
    """Dadaji's reply, or None if the scammer is giving up (time for the finale)."""
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

    # A clear goodbye or insult: go straight to the finale, before they actually hang up.
    phrase = analyst.hangup_phrase(text)
    if phrase:
        return await _caller_left(case, turn, "phrase", phrase)

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
        if analysis.hanging_up:
            return await _caller_left(case, turn, "analyst", "hanging_up flag")
    repeated = asked_to_repeat(session["history"])
    if guard.flagged:
        tactic = "baffled_by_jargon"
    else:
        tactic = analyst.pick_tactic(analysis.stall_tactic if analysis else None,
                                     case.tactics_used, repeated)
    persona = PERSONAS[session["persona"]]
    case.stall_tactic = tactic
    case.stall_note = analyst.tactic_instruction(tactic, persona.tactics)
    case.tactics_used.append(tactic)
    await dashboard.publish(case)

    note = analyst.tactic_note(tactic, persona.tactics)
    extra_check = None
    if repeated:
        # He has asked once already. Say so, and block a draft that asks again anyway.
        note += (" You already asked them to repeat once in this call: don't ask them to repeat,"
                 " slow down or speak louder again.")
        extra_check = lambda t: ["asked them to repeat again"] if REPEAT_ASK.search(t) else []
    # Canned lines he said recently are skipped, so a run of failures doesn't loop one line,
    # and so are "speak up" lines once he has asked.
    recent = recent_replies(session["history"], 3)
    fallbacks = tuple(f for f in persona.fallbacks if f not in recent
                      and not (repeated and REPEAT_ASK.search(f))) or persona.fallbacks
    start = time.perf_counter()
    try:
        # The guardrail cleans and checks the draft, retrying once before a canned stall line.
        reply, blocks = await guardrail.safe_reply(
            lambda feedback: dadaji_reply(session["persona"], session["history"],
                                          [note] + ([feedback] if feedback else [])),
            fallbacks, extra_check,
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
