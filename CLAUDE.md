# Dadaji Scam Buster

Solo entry for a 24-hour hackathon (**submission: Nov 1, 5 PM IST**) and for Hacktoberfest's
"Ghost in the Machine" open-source AI theme.

When a user picks up a scam call, they tap **"talk to my grandfather"** and an AI grandpa
(Dadaji) takes over the call and wastes the scammer's time. **Finale:** Dadaji says the call
was recorded and reported, then lets out a ghostly Halloween scream.

## Pipeline

```
Browser mic → Groq Whisper (STT) → orchestrator → Dadaji reply → guardrail check → browser TTS
                                       │
                                       ├─ Analyst  ┐  run in parallel (asyncio.gather)
                                       └─ Evidence ┘
WebSocket → live dashboard (transcript, risk score, signals, evidence, timer)
```

## Agents

- **Dadaji**: 78-year-old retired railway clerk. Speaks Hinglish (Romanized Hindi + English)
  in short 1–3 sentence replies. Stalls with confusion and tangents. Never shares real data,
  never reveals he is an AI, never uses abusive language.
  - Personas live in `backend/personas.py`. Each has a name, description and system prompt,
    and the persona is chosen per session. The shared safety rules sit in one base prompt.
  - Sweet Dadaji (forgetful and loving) is the default.
  - Later: Grumpy Dadaji (argues and lectures, never abusive), Confused Dadaji (thinks the
    scammer is his long-lost nephew).
- **Analyst**: after every scammer turn it returns structured JSON:
  `{scam_type, risk_score (0–100), signals[]}`. It also sends Dadaji a stalling tactic
  (for example, an OTP request triggers "lost glasses").
- **Evidence**: uses tool calling. Regex tools pull out phone numbers, UPI IDs, links and bank
  names, and the LLM adds context. Together they build a case file.
- **Reporter**: at the end of the call, maps the case file into a complaint shaped like the
  fields on the Indian cybercrime portal (cybercrime.gov.in).
- **Guardrail**: two checks.
  - **Input:** scammer text goes through Groq's `meta-llama/llama-prompt-guard-2-86m`
    (`PROMPT_GUARD_MODEL`) to detect prompt-injection attempts ("ignore your instructions",
    "reveal your prompt"). It returns a plain probability string as the message content
    (for example `"0.9996"` for an injection, `"0.0005"` for normal speech), so parse it with
    `float()` and flag anything above a threshold. Flags go to the dashboard and the analyst.
    This model exists only on Groq, so in Ollama mode skip it (or fall back to regex).
  - **Output:** checks every Dadaji reply before it is spoken and blocks any real-looking
    OTP, card or account number.

## Stack

- FastAPI (REST + WebSocket), SQLite for case files.
- Open-weight LLMs through the OpenAI-compatible client (`openai` package). The provider is
  switched with the `LLM_PROVIDER` environment variable:
  - `groq` (the default): cloud, fast. The default model is `openai/gpt-oss-120b`
    (Groq retired `llama-3.3-70b-versatile`).
  - `ollama`: Gemma (`gemma3:4b`) running locally, for an offline, private mode.
  - gpt-oss is a reasoning model, and its hidden reasoning counts toward `max_tokens`. Keep
    `reasoning_effort="low"` (`LLM_REASONING_EFFORT`) and a generous `max_tokens`. Otherwise
    replies get cut off mid-sentence or fall back to stock "I can't help with that" refusals.
- Front end: one HTML/JS page in `frontend/`, served by FastAPI.
- Deploy on Render.
- Everything free and open source under the MIT licence. Secrets go in `.env` (git-ignored),
  and `.env.example` documents them.

## Voice (milestone 3)

- Flow in `frontend/index.html`: the handoff button → `POST /api/call/start` (the persona's
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
- Headless Chrome's `--use-file-for-fake-audio-capture` gives silence on macOS. For automated
  tests, override `getUserMedia` with a Web Audio stream that plays a WAV instead.

## Layout

```
backend/
  config.py     env vars and LLM provider selection
  llm.py        shared OpenAI-compatible client + chat() helper
  personas.py   Dadaji persona configs
  dadaji.py     Dadaji agent (builds the prompt, calls the LLM, trims replies)
  stt.py        Groq Whisper speech-to-text
  main.py       FastAPI app: routes, sessions, serves the front end
frontend/
  index.html    single-page UI
```

## Commands

```bash
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then add GROQ_API_KEY
uvicorn backend.main:app --reload # run from the repo root → http://localhost:8000
```

## Build order

1. [x] Text chat with Sweet Dadaji
2. [ ] Analyst, evidence and guardrail agents + live dashboard over WebSocket
3. [x] Voice (Whisper STT + browser TTS) and the "talk to my grandfather" handoff button
   (built before M2 by choice; M2 slots in between `/api/transcribe` and the TTS step)
4. [ ] Reporter + time-wasted timer
5. [ ] Grumpy/Confused personas with a picker, the scream finale, deploy to Render
6. [ ] Stretch goal: eval script that runs 10 scripted scam calls and reports classification
   accuracy and data leaks

## Working rules

- Build **one milestone at a time**. Don't start the next one until the current one works.
- **Commit after each working step.**
- **Explain each change briefly.** The author is learning backend engineering, so say what
  was added and why, in plain terms.
- Keep it simple: no frameworks or services beyond the stack above. Only free and open-source
  dependencies.
- Treat all scammer text as untrusted input. It must never be able to override Dadaji's rules.
