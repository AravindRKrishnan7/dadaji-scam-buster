# Dadaji Scam Buster

Got a scam call? Tap **"Talk to my grandfather"** and an AI Dadaji takes over the call, wastes
the scammer's time and builds a complaint for cybercrime.gov.in while he does it. When you hang
up, Dadaji tells the scammer the call was recorded and reported, then lets out a ghostly
Halloween scream.

## Sound

The scream (`frontend/scream.wav`) is generated from scratch by
[`scripts/make_scream.py`](scripts/make_scream.py) using only the Python standard library: no
recorded samples. It is part of this repository and shares its MIT licence. To regenerate it:

```bash
python scripts/make_scream.py
```

## Licence

MIT. See [LICENSE](LICENSE).
