"""Generate frontend/scream.wav: the ghostly Halloween scream Dadaji lets out at the end of a call.

Made from scratch with the standard library only (no samples, so no licence questions):
    python scripts/make_scream.py

It's a jump scare, so it's built to be sudden, shrill and loud:
  1. Silence: after Dadaji's "Ab suno..." nothing happens for a moment.
  2. A shriek with a 5 ms attack (no fade-in): a buzzy tone (10 harmonics) that jumps to
     ~3.4 kHz, the range where the ear is most sensitive, and wails slowly down to ~1.9 kHz
     with a wide, uneven vibrato. Band-pass filters around 3 and 6 kHz make it a thin "eee".
  3. Roughness: a second voice 4% sharp, and a 70 Hz flutter in the volume. Fast flutter like
     this is what makes real screams sound alarming instead of musical.
  4. Hiss (filtered noise) and two short echoes, so it rings round the room.
  5. Loudness: soft clipping (tanh) squashes the peaks so the whole shriek can be turned up
     to nearly full scale. It's much louder than speech, which is how it beats Dadaji's voice.
The random seed is fixed, so the file comes out the same every time.
"""
import math
import random
import struct
import wave
from pathlib import Path

RATE = 44100
SILENCE = 0.7   # the pause before the jump scare
SHRIEK = 1.7
TAIL = 0.5      # time for the echoes to fade out
OUT = Path(__file__).resolve().parent.parent / "frontend" / "scream.wav"


def pitch(t: float) -> float:
    """Fundamental frequency over time (t from the start of the shriek): an instant jump to
    ~3.4 kHz, then a wail down to ~1.9 kHz."""
    if t < 0.04:
        return 2600 + (3400 - 2600) * (t / 0.04)
    return 3400 * (1900 / 3400) ** ((t - 0.04) / (SHRIEK - 0.04))


def envelope(t: float) -> float:
    if t < 0.005:
        return t / 0.005                      # 5 ms: as sudden as it gets without a click
    if t > SHRIEK - 0.35:
        return max(0.0, (SHRIEK - t) / 0.35)  # quick fade into the echoes
    return 1.0


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
    lead, n = int(RATE * SILENCE), int(RATE * (SILENCE + SHRIEK + TAIL))
    formants = [(BandPass(3000, 3), 1.2), (BandPass(6000, 4), 0.6)]  # roughly "eee"
    hiss_filter = BandPass(7000, 1.2)
    phases = [0.0, 0.0]  # the main voice and the one 4% sharp
    shriek = []
    for i in range(int(RATE * SHRIEK)):
        t = i / RATE
        vibrato = (1 + 0.06 * math.sin(2 * math.pi * 7 * t) + 0.02 * math.sin(2 * math.pi * 11.3 * t)
                   + 0.01 * (random.random() - 0.5))
        buzz = 0.0
        for v, detune in enumerate((1.0, 1.04)):
            phases[v] += 2 * math.pi * pitch(t) * detune * vibrato / RATE
            buzz += sum(math.sin(k * phases[v]) / k for k in range(1, 11))
        voice = 0.3 * buzz + sum(f(buzz) * gain for f, gain in formants)
        flutter = 1 - 0.45 * (0.5 + 0.5 * math.sin(2 * math.pi * 70 * t))
        hiss = 0.25 * hiss_filter(random.uniform(-1, 1))
        shriek.append(envelope(t) * (voice * flutter + hiss))
    peak = max(abs(s) for s in shriek)
    shriek = [math.tanh(5 * s / peak) for s in shriek]  # squash peaks: much louder overall
    out = [0.0] * lead + shriek + [0.0] * (n - lead - len(shriek))
    # Echoes: two quiet copies, a little later. Going backwards adds each copy once (no
    # feedback build-up), so the echo never drowns the shriek.
    for delay_s, gain in ((0.09, 0.3), (0.14, 0.2)):
        d = int(delay_s * RATE)
        for i in range(n - 1, lead + d - 1, -1):
            out[i] += gain * out[i - d]
    peak = max(abs(s) for s in out)
    return [0.98 * s / peak for s in out]


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
