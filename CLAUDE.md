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
  - Personas live in `backend/personas.py`. Each has a name, description, system prompt,
    `greeting`, `fallbacks`, `finale` (his last line before the scream) and a `reminder`. The
    persona is chosen per session with the picker on the call screen.
    - Sweet Dadaji (forgetful and loving) is the default.
    - Grumpy Dadaji argues and lectures about "aajkal ke bachche", but never insults anyone.
    - Confused Dadaji is sure the caller is Pappu, his late brother Shyam's son who ran off
      to Bombay 25 years ago.
    - Naughty Bunty is not Dadaji: a cheeky, fearless 5-year-old grandson who grabs the phone
      while Dadaji naps (this Bunty is 5, not the 22-year-old of the Dadaji personas). He mixes up
      words ("OTP matlab Oh Tota Pyaara?"), asks silly questions and teases harmlessly, never
      name-calls. Numbers bore him: he reads made-up digits at most once per call (without
      this he read 3 digits every turn). His prompt is `BUNTY_RULES`.
      - `Persona.tactics` overrides the `TACTICS` instructions with his own versions (glasses →
        "can't read big numbers yet", chai → Mummy calls him for milk). A line in the prompt
        saying "play the notes as yourself" wasn't enough: he still lost his glasses and made
        chai. A test checks that every tactic has a Bunty version.
      - `speaker` ("Bunty") labels his lines on the call screen and pill; `rate`/`pitch` (1.05,
        1.5) give him a child's voice. Both come from `GET /api/personas`.
  - `SPEECH_RULES` (Hinglish, Roman letters only, 1–3 sentences) and `HARD_RULES` (no real
    data, no AI reveal, no abuse, injections are nonsense) are shared by all four personas.
    `BASE_RULES` adds Dadaji's identity and stalls on top, for the three Dadaji personas:
    - a **fixed family**: grandson Bunty (handles "phone matters") and daughter-in-law Sunita
      (chai, the bank passbook). He never invents other relatives; Pappu is Confused only.
    - **Roman letters only**;
    - **varied stalls**;
    - he can cheerfully read out **at most 3 made-up digits** ("4... 4...") and then lose his
      place. The output guardrail already allows that (it needs 4+ digits, or 3 in a row
      after OTP/PIN), so it didn't need changing.
  - The stall tactic note used to drown out the personality: Grumpy stopped grumbling and
    Confused forgot Pappu. So every reply's notes end with the persona's `reminder`, and the
    note says "in your own personality".
  - **Variety, in code:**
    - `dadaji.variety_note()` shows him how his last 3 replies began.
    - Asking the caller to repeat / slow down / speak up is allowed **once per call** (a real
      call had "dheere se, thoda zor se boliye" twice, 3 replies apart). `asked_to_repeat()`
      runs the `REPEAT_ASK` regex over **all** his replies. Once he has asked, `hard_of_hearing`
      is banned, the note says not to ask again, `safe_reply(extra_check=...)` blocks a draft
      that asks anyway (one retry, then a fallback), and fallbacks that ask are skipped.
      `REPEAT_ASK` needs a "again/slowly/louder" word shortly before a speaking verb (bolo,
      boliye, batao…), so "dheere dheere chalta hoon" doesn't count.
    - `analyst.pick_tactic()` enforces both bans and rotates through `ROTATION` when the
      analyst fails or its pick is banned.
    - Fallback lines he said recently aren't reused.
- **Analyst** (`analyst.py`): JSON mode, reading the last 6 messages + the previous analysis →
  `{scam_type, risk_score, signals[], stall_tactic, hanging_up}`, validated by pydantic (unknown values are
  coerced, not rejected). Tactics come from the `TACTICS` catalogue (key → when to use it, plus
  Dadaji's instruction), with no repeats from the last 2 turns. Dadaji gets the tactic as a
  one-off system note after the history. Risk is calibrated to stay under 30 until money, codes,
  details, an app or threats come up. `fake_fine_threat` is a scam type.
  - **Risk floor** (`risk_floor()`, a rule in code): the caller claims a bank or government
    body (`CLAIM`: an authority word near "se bol raha", officer, department…) **and** either
    asks for account/card details, an OTP/PIN or money, **or** threatens a fine or arrest.
    - It's checked over **all** scammer messages, because the claim and the demand often
      come in different turns.
    - When it hits, risk is at least 75 (`RISK_FLOOR`), the `not_scam` reset can't apply, and
      a type of other/unknown/not_scam becomes `FloorHit.scam_type`: arrest →
      `digital_arrest`, fine → `fake_fine_threat`, OTP → `otp_fraud`, bank → `bank_kyc`,
      otherwise `fake_fine_threat`. The signal "authority claim + demand/threat (rule)" is
      added.
    - "fine" only counts next to an amount or lagega/bharna ("main fine hoon" is not a
      threat), and FIR only in capitals ("fir se" is Hinglish for "again").
    - `tests/test_risk_floor.py` covers the SBI claim → account request → ₹10 lakh fine call.
- **Auto-finale** (hang-up detection): when the scammer gives up, Dadaji doesn't reply and
  the finale plays by itself. `handle_turn()` returns `None`, `/api/chat` returns
  `{"reply": "", "hangup": true}`, and `call.js` runs the same `endCall()` as the End call
  button (which stays as a backup). `case.hangup = {turn, source, detail}` and the signal
  "caller gave up / hung up" is added.
  - `analyst.HANGUP` (phrase list, checked **before** the analyst so the finale starts before
    they hang up): phone cut/rakh/band, bye, chhodo at the end of a sentence, time waste,
    insults (bewakoof by prefix, since Whisper wrote "bevaku fora", stupid, pagal, buddhe…).
    Not when followed by mat/nahi/na ("call cut mat karna", "time waste mat karo") or after
    pe/par ("hold pe rakh raha hoon").
  - Otherwise the analyst's `hanging_up` flag (only a real `true` counts).
  - `tests/test_hangup.py` has the real lines "Aray yaar, bevaku fora, main phone cut kar raha
    hoon" and "TK, bye bye, you are stupid, bye".
- **Evidence** (`evidence.py`): tool calling on the latest scammer message only. Finder tools
  take no arguments (they scan that message): `find_phone_numbers`, `find_upi_ids`, `find_links`,
  `find_bank_names`. There's also `record_context` for the claimed identity, amount and payment
  method. A regex safety net runs afterwards, so items are tagged `source: tool` or `regex`.
  `normalise()` turns spoken forms ("at the rate" → @, "dot" → ., number words → digits)
  back into written ones. "phone pe" with a space is Hindi for "on the phone", so only "PhonePe"
  counts as the app. On Ollama it uses regexes only (Gemma has no tool support).
- **Case file** (`case_file.py`): a pydantic `CaseFile` in the session, holding risk history,
  signals, tactics, evidence (with turn numbers), injection attempts, blocked replies (with
  digits redacted), stage timings, the transcript with timestamps, and `started_at`/`ended_at`
  for the timer. It lives in the session and is saved to SQLite after every turn (`db.py`).
  - **Merge rules** (`apply_analysis()`): the analyst only sees the last 6 messages, so one odd
    answer mustn't undo the case.
    - A specific scam type is sticky. It can change to another specific type, but never falls
      back to `other`. (The analyst prompt also says to keep a clear type.)
    - Risk drops by at most 5 per turn (`MAX_RISK_DROP`). The one exception: the analyst says
      `not_scam` with risk under 30 (`INNOCENT_RISK`), and then its score is taken as is.
    - An injection attempt lifts risk to 10 above the higher of the new and previous scores
      (`INJECTION_RISK_BUMP`), capped at 100. "prompt injection attempt" then stays in the
      signals for the rest of the call.
    - If the analyst fails, type and risk stay as they were (risk history still gets an entry).
    - Last, the risk floor (see Analyst) is applied.
    - The orchestrator hands the analyst the **merged** view as its "previous analysis" next
      turn, not its own raw answer.
    - `tests/test_case_merge.py` replays the SBI KYC + OTP + injection call with stubbed LLMs.
      `LIVE=1 pytest` also runs it against Groq.
- **Reporter** (`reporter.py`): at the end of the call, turns the case file into a `Complaint`
  (sections of `{label, value, hint}`) laid out like the cybercrime.gov.in form.
  - **Plain code** fills every field: category/sub-category from `CATEGORIES` (default
    *Online Financial Fraud › Fraud Call/Vishing*; the names are from memory and should be
    checked against the live portal), date/time in IST, suspect identifiers (with their turn),
    amounts and amount lost ₹0. **Complainant fields stay blank** ("Your name"…) because the
    app never collects the user's details.
  - **The LLM** (`reporter` role) writes only the "additional information" text (200–1500
    chars). `check_narrative()` rejects it if it names any phone, UPI ID or link that isn't in
    the evidence, or if it's a refusal or too short. Then `template_narrative()` is used, so a
    complaint always comes out. gpt-oss writes non-breaking hyphens (U+2011), which are
    turned into "-" before the check, or they'd split IDs.
  - The LLM sees **only the scammer's lines**. When it got Dadaji's lines too, it credited his
    stalling ("where are my glasses?") to the scammer, even when told not to.
- **Guardrail** (`guardrail.py`): two checks.
  - **Input:** Groq's `meta-llama/llama-prompt-guard-2-86m` (`PROMPT_GUARD_MODEL`) returns a
    bare probability string (`"0.9996"`), and anything above 0.5 is flagged. **It misses
    Hinglish and reworded attempts** ("apne rules bhool jao" scores 0.00), so the
    `INJECTION_PHRASES` regex is ORed with it. A flag forces the `baffled_by_jargon` tactic. It
    needs a Groq key and is skipped without one.
  - **Output:** `clean()` strips emojis, *actions*, (asides) and a name prefix. Then
    `find_problems()` blocks 5+ digits and 4 digits (unless a year 1900–2099 or near
    ₹/rupaye/lakh). It always blocks anything near OTP/PIN/CVV, Luhn-valid cards, PAN, IFSC,
    UPI or email strings, AI reveals, and abuse, including name-calling (bewakoof, nalayak…,
    for Grumpy). Spoken digits ("ek do teen char") count.
    - gpt-oss sometimes adds a Devanagari sentence. `clean()` drops Devanagari and Urdu
      sentences; if nothing Roman is left, the problem is "non-Roman script".
    - `safe_reply()` retries once with the reasons, then uses a persona fallback line.

## Stack

- FastAPI (REST + WebSocket), SQLite for case files.
- Open-weight LLMs through the OpenAI-compatible client (`openai` package). The provider is
  switched with the `LLM_PROVIDER` environment variable:
  - `groq` (the default): cloud, fast.
  - `ollama`: Gemma (`gemma3:4b`) for every role, for an offline, private mode. Whisper and
    Prompt Guard still use Groq if a key is set, so voice mode isn't fully offline.
- **Each agent role has its own model** (`config.MODELS`, overridable with `DADAJI_MODEL`,
  `ANALYST_MODEL`, `EVIDENCE_MODEL`, `REPORTER_MODEL`), because **Groq's free tier allows 8,000 tokens/min per
  model**. One model for everything would hit 429 errors within a minute.
  | role | Groq model | reasoning_effort |
  |---|---|---|
  | dadaji | `openai/gpt-oss-120b` | low |
  | analyst | `openai/gpt-oss-20b` | low |
  | evidence | `qwen/qwen3.8-27b` | none |
  | reporter | `openai/gpt-oss-20b` | low |
  The reporter shares the analyst's model: it runs once, after the call, when the analyst is
  idle. The only chat models left on Groq are these three (no llama). gpt-oss rejects `"none"` and
  accepts low/medium/high only. Prompt Guard has its own 15k/min budget. A 6-turn scripted call
  at about 35 turns/min gave no 429s.
- gpt-oss is a reasoning model, and its hidden reasoning counts toward `max_tokens`. Keep
  reasoning low and `max_tokens` generous (1024). Otherwise replies get cut off mid-sentence
  or fall back to stock "I can't help with that" refusals.
- Front end: `frontend/index.html` + `call.js` + `dashboard.js` (served at `/static`). The call
  screen is on the left and the dashboard on the right, stacked on phones. The dashboard sets
  scammer text with `textContent` only, never `innerHTML`.
- Deploy on Render. Its free tier wipes the disk on every deploy, so saved cases don't survive
  a redeploy. That's fine for the demo.
  - `render.yaml` (Blueprint): free web service, `pip install -r requirements.txt`, then
    `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`, health check `/api/health`,
    `PYTHON_VERSION=3.14.6`. **Exactly one worker**: sessions live in memory in `main.py`.
  - The only secret is `GROQ_API_KEY` (`sync: false`, entered in the dashboard). `requirements.txt`
    is pinned to the tested versions.
  - The free tier sleeps after 15 min idle; open the URL a minute before a demo.
- Everything free and open source under the MIT licence. Secrets go in `.env` (git-ignored),
  and `.env.example` documents them.

## Voice (milestone 3)

- Flow in `frontend/call.js`: the handoff button → `POST /api/call/start` (the persona's
  fixed `greeting`, stored as the first assistant message) → speak → listen →
  `POST /api/transcribe` → `POST /api/chat` → speak → listen…
- STT is `whisper-large-v3-turbo` (`STT_MODEL`) and **always uses Groq**, even when
  `LLM_PROVIDER=ollama`, because Ollama has no Whisper. With no key, it returns a 503 and the UI
  falls back to typing.
- Whisper runs with `language="hi"`. Left to guess, it sometimes wrote Hinglish in Urdu
  script, but with Hindi it writes Devanagari, so `translit.to_roman()` romanises every
  transcript. That's a letter table plus Hindi schwa deletion: आठ → aath, करना → karna, a
  cluster ending in य/र/व keeps its "a" (शून्य → shoonya), हूँ → hoon. Without this, injection
  phrases, spoken numbers and evidence regexes would miss Devanagari. Romanised spellings
  differ ("rools", "baink", "pulis", "nambar"), so the regexes include them.
- The Whisper prompt (`PROMPT_HINT`) is written like a transcript in Roman Hinglish with the
  scam words (KYC, OTP, UPI, account, fine, beta, Dadaji), because Whisper reads it as "the
  text so far". Transcripts under 3 characters are dropped as noise.
- Whisper invents "Thank you." for silence. Groq's `no_speech_prob` is always 0, so `stt.py`
  drops known filler phrases instead, and the browser only uploads clips with ≥0.5 s of speech.
- Hands-free turn-taking: a volume (RMS) threshold that adapts to background noise, and 1.2 s
  of silence ends a turn. Recording stops while Dadaji speaks, so he doesn't hear himself.
  "Done speaking" forces a turn to end in noisy rooms, and "Interrupt Dadaji" cuts him off.
- TTS: `speechSynthesis`, `hi-IN` and `en-IN` voices. Rate 0.9 and pitch 0.8. **Rishi**
  (en-IN, Apple) is the default when available, unless the user picked another voice in the
  dropdown, because most Hindi voices are female.
- gpt-oss sometimes glues several Dadaji turns into one reply. `trim_reply()` keeps the first
  turn and at most 3 sentences.
- Anything the scammer says while Dadaji is speaking isn't recorded (that's the echo protection).
- Headless Chrome's `--use-file-for-fake-audio-capture` gives silence on macOS. For automated
  tests, override `getUserMedia` with a Web Audio stream that plays a WAV instead.

## End of call, SQLite, reporter (milestone 4)

- `POST /api/call/end` → `orchestrator.end_call()`:
  1. stamps `ended_at` first, so the timer stops when End was pressed;
  2. waits up to 2 s (`EVIDENCE_WAIT`) for the call's evidence tasks (`session["pending"]`).
     If any are still running (Groq rate limits), the regex net runs over every scammer
     message, so the complaint still gets the identifiers;
  3. writes the complaint and saves case + complaint.
  A double click shares one `session["ending"]` task. `/api/chat` on an ended call returns 409.
- `db.py`: stdlib `sqlite3`, one `cases` row per call with the whole case file as JSON (no
  migrations when `CaseFile` changes) and the complaint as `report_json`. A save without a
  report keeps the old one. Calls run in `asyncio.to_thread` so the event loop isn't blocked.
  `DB_PATH` defaults to `data/cases.db` (git-ignored). Tests get a throwaway database from
  `tests/conftest.py`.
- Routes: `GET /api/cases/{id}` (memory first, then SQLite, so it works after a restart),
  `/api/cases/{id}/report?format=json|txt` (a download; `attach=false` for Copy all),
  `/api/cases/{id}/transcript` (.txt, to attach as evidence), `/api/stats` (ended calls with
  at least one scammer turn, and their total seconds).
- Timer: each WebSocket message carries the server's `now`, and the browser keeps the
  difference from its own clock, so the timer is right even if the phone's clock is off. It
  ticks locally every second and freezes at `ended_at`. The running total is underneath.
- Complaint card: shown after End call, a Copy button per field (the portal is a form), Copy
  all, and the downloads. Hidden again when a new call starts.

## Personas, finale, typed calls (milestone 5)

- **Finale** (`endCall()` in `call.js`, from End call or the auto-finale):
  1. `POST /api/call/end` starts immediately, while Dadaji talks.
  2. The browser shows and speaks the persona's `finale` ("call record ho gayi… report bhi
     ho gayi… Ab suno…").
  3. `frontend/scream.wav` plays.
  4. The complaint card appears.
  `end_call()` adds the finale as the last transcript line.
- Browsers only allow sound that was started inside a click, so `unlockAudio()` (an empty
  utterance + the scream played muted for a moment) runs on the handoff click, every Send and
  the End click. The auto-finale has no click of its own.
- **The finale never waits forever:**
  - `speak()` skips speech that hasn't started after 2.5 s and cuts it off at 20 s.
  - `playScream()` skips after 1.5 s without playing and stops at 5 s.
  - `/api/call/end` times out after 30 s, and then an error replaces the complaint.
  - Each step logs `[finale] n/5` to the console.
- Don't `return` inside the `try` in `scammerSays()`: the `finally` runs and then the function
  exits, so the `endCall()` after it is skipped. That was the auto-finale hang (tested in
  headless Chrome over CDP with real mouse clicks).
- The scream comes from `scripts/make_scream.py`: stdlib only, a fixed seed, so it's
  reproducible. A jump scare: 0.7 s of silence, then a 5 ms attack into a ~3.4 kHz shriek
  (two detuned buzzy voices, "eee" formants at 3 and 6 kHz, a 70 Hz roughness flutter, hiss)
  sliding to ~1.9 kHz, tanh soft clipping for loudness (about -7 dBFS RMS, 7 dB above the old
  one), two short echoes. 44.1 kHz, 2.9 s. The README credits it.
- **Typed sessions:** End call appears after the first typed reply, and the handoff button
  hides until then. So typed calls also get the finale and the complaint.
- **Persona picker:** `#persona` is filled from `GET /api/personas` (which includes `finale`)
  and locked while a call is open. The dashboard header shows the persona's name.

## Live dashboard (milestone 2)

- `WS /ws/{session_id}` sends a snapshot on connect, then `dashboard.publish()` pushes
  `{"type": "case", "case": {...}, "now": <server time>}` after every pipeline step. It always sends the **whole**
  case file, and the page re-renders. The turn itself stays plain HTTP (`/api/chat`), and the
  WebSocket only pushes updates to the display.
- `dashboard.js` reconnects every 2 s during a call and gives up on close code 4404 (the server
  restarted, so the session is gone). After End call, the last case file stays on screen,
  with the complaint card.
- Panels: time wasted (+ running total), complaint (after End call), risk (number, colour, sparkline), scam type + signals, director's note, evidence
  (dashed chips = found by the regex net), guardrail log, stage timings.

## Layout

```
backend/
  config.py        env vars, provider + per-role model selection
  llm.py           shared clients (get_client, get_groq_client) + chat()/chat_message()
  personas.py      Dadaji personas (prompt, greeting, fallbacks, finale, reminder)
  dadaji.py        Dadaji agent (prompt + one-off notes, trims replies)
  analyst.py       scam classification, TACTICS + pick_tactic(), risk_floor() rule
  evidence.py      tool-calling evidence agent + regex extractors
  guardrail.py     injection check (input) + leak/character filter (output)
  case_file.py     CaseFile model
  orchestrator.py  handle_turn(): the asyncio pipeline; end_call()
  reporter.py      case file → cybercrime.gov.in complaint (+ transcript text)
  db.py            SQLite storage for case files and complaints
  dashboard.py     WebSocket hub (subscribers, publish)
  stt.py           Groq Whisper speech-to-text (Hindi, romanised, noise filter)
  translit.py      Devanagari → Roman Hinglish for transcripts
  main.py          FastAPI app: routes, sessions, WebSocket, static files
frontend/
  index.html       layout + styles
  call.js          call screen, mic, TTS
  dashboard.js     live case-file dashboard
  scream.wav       the finale scream (generated)
scripts/
  make_scream.py   generates frontend/scream.wav (stdlib only)
tests/             pytest unit tests (no network): guardrail, evidence regexes, trim_reply,
                   case merge rules, SQLite, reporter, personas, STT/translit, risk floor
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
4. [x] Reporter + SQLite + time-wasted timer
5. [x] Persona polish, Grumpy/Confused personas with a picker, the scream finale, typed End
   call, Whisper fixes, risk floor rule
6. [ ] Deploy to Render
7. [ ] Stretch goal: eval script that runs 10 scripted scam calls and reports classification
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
