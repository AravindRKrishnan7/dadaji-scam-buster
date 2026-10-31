# Dadaji Scam Buster

Got a scam call? Tap **"Talk to my grandfather"** and an AI Dadaji takes over the call, wastes
the scammer's time and builds a complaint for cybercrime.gov.in while he does it. When you hang
up, Dadaji tells the scammer the call was recorded and reported, then lets out a ghostly
Halloween scream.

## Personas

Pick who answers the call:

- **Sweet Dadaji**: forgetful, loving, and very slow with technology.
- **Grumpy Dadaji**: argues with everything and lectures about kids these days (never abusive).
- **Confused Dadaji**: sure the caller is his long-lost nephew Pappu.

All three share the same family (grandson Bunty, daughter-in-law Sunita) and the same hard
rules: never share real data, never admit to being an AI, never use abusive language.

## Run it

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then add a free GROQ_API_KEY
uvicorn backend.main:app --reload # http://localhost:8000
pip install -r requirements-dev.txt && pytest
```

## Sound

The scream (`frontend/scream.wav`) is generated from scratch by
[`scripts/make_scream.py`](scripts/make_scream.py) using only the Python standard library: no
recorded samples. It is part of this repository and shares its MIT licence. To regenerate it:

```bash
python scripts/make_scream.py
```

## Licence

MIT. See [LICENSE](LICENSE).
