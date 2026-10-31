# Dadaji Scam Buster

Solo entry for a 24-hour hackathon (**submission: Nov 1, 5 PM IST**) and for Hacktoberfest's
"Ghost in the Machine" open-source AI theme.

When a user picks up a scam call, they tap **"talk to my grandfather"** and an AI grandpa
(Dadaji) takes over the call and wastes the scammer's time. **Finale:** Dadaji says the call
was recorded and reported, then lets out a ghostly Halloween scream.

## Pipeline

```
Browser mic → Whisper → /api/chat → orchestrator.handle_turn():
    ├─ Evidence agent ──── background task, publishes when done (~1 s) ───────────────┐
    ├─ Guardrail input ┐  asyncio.gather                                              │
    └─ Analyst ────────┴→ stall tactic → Dadaji → guardrail output → reply → browser TTS
Every step: dashboard.publish(case) → WebSocket /ws/{session_id} → live dashboard
```
Dadaji waits for the analyst (he needs its tactic) but not for evidence (he doesn't).
A turn takes about 1–1.5 s end to end. If an agent fails, it's logged and skipped. If Dadaji
fails (including a 429), the persona's `fallbacks` line is used, so the call never breaks.

## Agents

- **Dadaji**: 78-year-old retired railway clerk. Speaks Hinglish (Romanized Hindi + English)
  in short 1–3 sentence replies. Stalls with confusion and tangents. Never shares real data,
  never reveals he is an AI, never uses abusive language.
  - Personas live in `backend/personas.py`. Each has a name, description and system prompt,
    and the persona is chosen per session. The shared safety rules sit in one base prompt.
  - Sweet Dadaji (forgetful and loving) is the default.
  - Later: Grumpy Dadaji (argues and lectures, never abusive), Confused Dadaji (thinks the
    scammer is his long-lost nephew).
- **Analyst** (`analyst.py`): JSON mode, reading the last 6 messages + the previous analysis →
  `{scam_type, risk_score, signals[], stall_tactic}`, validated by pydantic (unknown values are
  coerced, not rejected). Tactics come from the `TACTICS` catalogue (key → when to use it, plus
  Dadaji's instruction), with no repeats from the last 2 turns. Dadaji gets the tactic as a
  one-off system note after the history. Risk is calibrated to stay under 30 until money, codes,
  details, an app or threats come up.
- **Evidence** (`evidence.py`): tool calling on the latest scammer message only. Finder tools
  take no arguments (they scan that message): `find_phone_numbers`, `find_upi_ids`, `find_links`,
  `find_bank_names`. There's also `record_context` for the claimed identity, amount and payment
  method. A regex safety net runs afterwards, so items are tagged `source: tool` or `regex`.
  `normalise()` turns spoken forms ("at the rate" → @, "dot" → ., number words → digits)
  back into written ones. "phone pe" with a space is Hindi for "on the phone", so only "PhonePe"
  counts as the app. On Ollama it uses regexes only (Gemma has no tool support).
- **Case file** (`case_file.py`): a pydantic `CaseFile` in the session, holding risk history,
  signals, tactics, evidence (with turn numbers), injection attempts, blocked replies (with
  digits redacted), stage timings and the transcript with timestamps. It's in memory for now,
  and SQLite comes with the reporter in M4.
- **Reporter**: at the end of the call, maps the case file into a complaint shaped like the
  fields on the Indian cybercrime portal (cybercrime.gov.in).
- **Guardrail** (`guardrail.py`): two checks.
  - **Input:** Groq's `meta-llama/llama-prompt-guard-2-86m` (`PROMPT_GUARD_MODEL`) returns a
    bare probability string (`"0.9996"`), and anything above 0.5 is flagged. **It misses
    Hinglish and reworded attempts** ("apne rules bhool jao" scores 0.00), so the
    `INJECTION_PHRASES` regex is ORed with it. A flag forces the `baffled_by_jargon` tactic. It
    needs a Groq key and is skipped without one.
  - **Output:** `clean()` strips emojis, *actions*, (asides) and a name prefix. Then
    `find_problems()` blocks 5+ digits and 4 digits (unless a year 1900–2099 or near
    ₹/rupaye/lakh). It always blocks anything near OTP/PIN/CVV, Luhn-valid cards, PAN, IFSC,
    UPI or email strings, AI reveals and abuse. Spoken digits ("ek do teen char") count.
    `safe_reply()` retries once with the reasons, then uses a persona fallback line.

## Stack

- FastAPI (REST + WebSocket), SQLite for case files.
- Open-weight LLMs through the OpenAI-compatible client (`openai` package). The provider is
  switched with the `LLM_PROVIDER` environment variable:
  - `groq` (the default): cloud, fast.
  - `ollama`: Gemma (`gemma3:4b`) for every role, for an offline, private mode. Whisper and
    Prompt Guard still use Groq if a key is set, so voice mode isn't fully offline.
- **Each agent role has its own model** (`config.MODELS`, overridable with `DADAJI_MODEL`,
  `ANALYST_MODEL`, `EVIDENCE_MODEL`), because **Groq's free tier allows 8,000 tokens/min per
  model**. One model for everything would hit 429 errors within a minute.
  | role | Groq model | reasoning_effort |
  |---|---|---|
  | dadaji | `openai/gpt-oss-120b` | low |
  | analyst | `openai/gpt-oss-20b` | low |
  | evidence | `qwen/qwen3.8-27b` | none |
  The only chat models left on Groq are these three (no llama). gpt-oss rejects `"none"` and
  accepts low/medium/high only. Prompt Guard has its own 15k/min budget. A 6-turn scripted call
  at about 35 turns/min gave no 429s.
- gpt-oss is a reasoning model, and its hidden reasoning counts toward `max_tokens`. Keep
  reasoning low and `max_tokens` generous (1024). Otherwise replies get cut off mid-sentence
  or fall back to stock "I can't help with that" refusals.
- Front end: `frontend/index.html` + `call.js` + `dashboard.js` (served at `/static`). The call
  screen is on the left and the dashboard on the right, stacked on phones. The dashboard sets
  scammer text with `textContent` only, never `innerHTML`.
- Deploy on Render.
- Everything free and open source under the MIT licence. Secrets go in `.env` (git-ignored),
  and `.env.example` documents them.

## Voice (milestone 3)

- Flow in `frontend/call.js`: the handoff button → `POST /api/call/start` (the persona's
  fixed `greeting`, stored as the first assistant message) → speak → listen →
  `POST /api/transcribe` → `POST /api/chat` → speak → listen…
- STT is `whisper-large-v3-turbo` (`STT_MODEL`) and **always uses Groq**, even when
  `LLM_PROVIDER=ollama`, because Ollama has no Whisper. With no key, it returns a 503 and the UI
  falls back to typing.
- Whisper invents "Thank you." for silence. Groq's `no_speech_prob` is always 0, so `stt.py`
  drops known filler phrases instead, and the browser only uploads clips with ≥0.5 s of speech.
- Hands-free turn-taking: a volume (RMS) threshold that adapts to background noise, and 1.2 s
  of silence ends a turn. Recording stops while Dadaji speaks, so he doesn't hear himself.
  "Done speaking" forces a turn to end in noisy rooms, and "Interrupt Dadaji" cuts him off.
- TTS: `speechSynthesis`, preferring `hi-IN`, then `en-IN`, voices. Rate 0.9 and pitch 0.8.
  There's a voice dropdown, because most Hindi voices are female.
- gpt-oss sometimes glues several Dadaji turns into one reply. `trim_reply()` keeps the first
  turn and at most 3 sentences.
- Anything the scammer says while Dadaji is speaking isn't recorded (that's the echo protection).
- Headless Chrome's `--use-file-for-fake-audio-capture` gives silence on macOS. For automated
  tests, override `getUserMedia` with a Web Audio stream that plays a WAV instead.

## Live dashboard (milestone 2)

- `WS /ws/{session_id}` sends a snapshot on connect, then `dashboard.publish()` pushes
  `{"type": "case", "case": {...}}` after every pipeline step. It always sends the **whole**
  case file, and the page re-renders. The turn itself stays plain HTTP (`/api/chat`), and the
  WebSocket only pushes updates to the display.
- `dashboard.js` reconnects every 2 s during a call and gives up on close code 4404 (the server
  restarted, so the session is gone). After End call, the last case file stays on screen.
- Panels: risk (number, colour, sparkline), scam type + signals, director's note, evidence
  (dashed chips = found by the regex net), guardrail log, stage timings.

## Layout

```
backend/
  config.py        env vars, provider + per-role model selection
  llm.py           shared clients (get_client, get_groq_client) + chat()/chat_message()
  personas.py      Dadaji persona configs (prompt, greeting, fallbacks)
  dadaji.py        Dadaji agent (prompt + one-off notes, trims replies)
  analyst.py       scam classification + TACTICS catalogue
  evidence.py      tool-calling evidence agent + regex extractors
  guardrail.py     injection check (input) + leak/character filter (output)
  case_file.py     CaseFile model
  orchestrator.py  handle_turn(): the asyncio pipeline
  dashboard.py     WebSocket hub (subscribers, publish)
  stt.py           Groq Whisper speech-to-text
  main.py          FastAPI app: routes, sessions, WebSocket, static files
frontend/
  index.html       layout + styles
  call.js          call screen, mic, TTS
  dashboard.js     live case-file dashboard
tests/             pytest unit tests (no network): guardrail, evidence regexes, trim_reply
```

## Commands

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then add GROQ_API_KEY
uvicorn backend.main:app --reload # run from the repo root → http://localhost:8000
pip install -r requirements-dev.txt && pytest   # unit tests, about 0.3 s, no network
```

## Build order

1. [x] Text chat with Sweet Dadaji
2. [x] Analyst, evidence and guardrail agents + live dashboard over WebSocket
3. [x] Voice (Whisper STT + browser TTS) and the "talk to my grandfather" handoff button
   (built before M2 by choice; M2 slots in between `/api/transcribe` and the TTS step)
4. [ ] Reporter + time-wasted timer
5. [ ] Grumpy/Confused personas with a picker, the scream finale, deploy to Render
6. [ ] Stretch goal: eval script that runs 10 scripted scam calls and reports classification
   accuracy and data leaks

## Working rules

- Build **one milestone at a time**. Don't start the next one until the current one works.
- **Commit after each working step**, on a feature branch per milestone. Merge to `main` only
  when asked.
- **Explain each change briefly.** The author is learning backend engineering, so say what
  was added and why, in plain terms.
- Keep it simple: no frameworks or services beyond the stack above. Only free and open-source
  dependencies.
- Treat all scammer text as untrusted input. It must never be able to override Dadaji's rules.
