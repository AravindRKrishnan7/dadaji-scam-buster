"""Generate frontend/scream.wav: the ghostly Halloween scream Dadaji lets out at the end of a call.

Made from scratch with the standard library only (no samples, so no licence questions):
    python scripts/make_scream.py

How it's built, layer by layer:
  1. A screaming "voice": a buzzy tone (8 harmonics) that shoots up to ~1.3 kHz, then slides
     down to ~300 Hz, with a wobbly vibrato. Two band-pass filters shape it into an "aaah".
  2. A ghostly whistle: a pure tone sliding down an octave, slightly out of tune with the voice.
  3. Breath: filtered white noise.
  4. Echoes: three decaying feedback delays, which make it sound like a haunted hallway.
The random seed is fixed, so the file comes out the same every time.
"""
import math
import random
import struct
import wave
from pathlib import Path

RATE = 22050
SECONDS = 3.0
TAIL = 0.8  # extra time for the echoes to fade out
OUT = Path(__file__).resolve().parent.parent / "frontend" / "scream.wav"


def pitch(t: float) -> float:
    """Fundamental frequency over time: a fast jump up, then a long ghostly slide down."""
    if t < 0.15:
        return 700 + (1300 - 700) * (t / 0.15)
    return 1300 * (300 / 1300) ** ((t - 0.15) / (SECONDS - 0.15))


def envelope(t: float) -> float:
    if t < 0.06:
        return t / 0.06                       # sharp attack
    if t > SECONDS - 0.9:
        return max(0.0, (SECONDS - t) / 0.9)  # fade into the echoes
    return 1.0 - 0.25 * (t / SECONDS)


class BandPass:
    """A two-pole resonator (the classic biquad band-pass), to give the voice a vowel."""

    def __init__(self, freq: float, q: float):
        w = 2 * math.pi * freq / RATE
        alpha = math.sin(w) / (2 * q)
        a0 = 1 + alpha
        self.b0, self.b2 = alpha / a0, -alpha / a0
        self.a1, self.a2 = -2 * math.cos(w) / a0, (1 - alpha) / a0
        self.x1 = self.x2 = self.y1 = self.y2 = 0.0

    def __call__(self, x: float) -> float:
        y = self.b0 * x + self.b2 * self.x2 - self.a1 * self.y1 - self.a2 * self.y2
        self.x2, self.x1, self.y2, self.y1 = self.x1, x, self.y1, y
        return y


def render() -> list[float]:
    random.seed(31)
    n = int(RATE * (SECONDS + TAIL))
    formants = [(BandPass(900, 4), 1.0), (BandPass(2600, 6), 0.5)]  # roughly "aah"
    breath_filter = BandPass(3000, 1.5)
    voice_phase = whistle_phase = 0.0
    out = []
    for i in range(n):
        t = i / RATE
        if t < SECONDS:
            vibrato = 1 + 0.04 * math.sin(2 * math.pi * 6 * t) + 0.01 * (random.random() - 0.5)
            voice_phase += 2 * math.pi * pitch(t) * vibrato / RATE
            buzz = sum(math.sin(k * voice_phase) / k for k in range(1, 9))
            voice = 0.25 * buzz + sum(f(buzz) * gain for f, gain in formants)  # a little raw buzz = harsher
            whistle_phase += 2 * math.pi * (pitch(t) * 1.07) * (1 + 0.02 * math.sin(2 * math.pi * 3 * t)) / RATE
            whistle = 0.35 * math.sin(whistle_phase)
            breath = 0.12 * breath_filter(random.uniform(-1, 1))
            out.append(envelope(t) * (voice + whistle + breath))
        else:
            out.append(0.0)
    # Echoes: each delay line feeds back into itself, fading a little each time round.
    for delay_s, feedback in ((0.11, 0.45), (0.17, 0.35), (0.23, 0.3)):
        d = int(delay_s * RATE)
        for i in range(d, n):
            out[i] += feedback * out[i - d]
    peak = max(abs(s) for s in out)
    return [0.9 * s / peak for s in out]


def main():
    samples = render()
    with wave.open(str(OUT), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)  # 16-bit
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(s * 32767)) for s in samples))
    print(f"Wrote {OUT} ({len(samples) / RATE:.1f} s, {OUT.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
