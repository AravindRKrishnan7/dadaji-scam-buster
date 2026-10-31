"""Guardrail: checks what the scammer says (prompt injection) and what Dadaji says (leaks).

Input:  Prompt Guard scores injection attempts. It misses Hinglish and reworded ones
        ("apne rules bhool jao"), so a phrase list backs it up.
Output: every Dadaji reply is cleaned (emojis, *actions*) and checked for real-looking
        numbers/IDs and for breaking character, before it is spoken.
"""
import logging
import random
import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from backend import config
from backend.llm import GroqUnavailable, get_groq_client

log = logging.getLogger("uvicorn.error")

# ---------- Input: prompt injection ----------

INJECTION_THRESHOLD = 0.5
INJECTION_PHRASES = re.compile(r"""
    ignore\s+(?:all\s+|your\s+|the\s+|previous\s+|prior\s+|above\s+)*(?:instructions|rules|prompt)
  | (?:forget|disregard)\s+(?:everything|all|your\s+(?:rules|instructions))
  | system\s+prompt | developer\s+mode | jailbreak
  | you\s+are\s+now\b
  | pretend\s+(?:to\s+be|you\s+are)
  | (?:reveal|print|show)\s+(?:me\s+)?(?:your\s+)?(?:prompt|instructions)
  | (?:rules|instructions|niyam)\s+(?:bhool|bhul|chhod)
  | (?:tum|aap)\s+(?:ab\s+)?(?:ek\s+)?(?:ai|bot|robot|assistant)\s+(?:ho|hai)
""", re.I | re.X)


@dataclass
class InputCheck:
    flagged: bool
    score: float | None = None  # Prompt Guard probability, None if it wasn't available
    source: str | None = None   # "prompt_guard" or "phrases"


async def prompt_guard_score(text: str) -> float | None:
    try:
        resp = await get_groq_client().chat.completions.create(
            model=config.PROMPT_GUARD_MODEL,
            messages=[{"role": "user", "content": text[:1500]}],  # the model reads 512 tokens max
        )
        # It answers with a bare probability, e.g. "0.9996".
        return float(resp.choices[0].message.content)
    except GroqUnavailable:
        return None
    except Exception:
        log.warning("Prompt Guard failed", exc_info=True)
        return None


async def check_input(text: str) -> InputCheck:
    score = await prompt_guard_score(text)
    if score is not None and score > INJECTION_THRESHOLD:
        return InputCheck(True, score, "prompt_guard")
    if INJECTION_PHRASES.search(text):
        return InputCheck(True, score, "phrases")
    return InputCheck(False, score)


# ---------- Output: clean, then check for leaks ----------

EMOJI = re.compile("[\U0001F000-\U0001FAFF☀-➿⬀-⯿️‍⃣]")
NON_ROMAN = re.compile("[\u0900-\u097F\u0600-\u06FF\u0750-\u077F]")  # Devanagari, Arabic/Urdu


def drop_non_roman(text: str) -> str:
    """Dadaji speaks Roman Hinglish. gpt-oss sometimes tacks on a Devanagari sentence; drop
    those sentences. If nothing Roman is left, keep it so find_problems() can block it."""
    sentences = re.split(r"(?<=[.?!…।])\s+", text)
    roman = [s for s in sentences if not NON_ROMAN.search(s)]
    return " ".join(roman) if roman else text


def clean(text: str) -> str:
    """Remove things that sound silly when spoken: *actions*, (asides), emojis, a name prefix."""
    text = re.sub(r"\*[^*]*\*|\([^)]*\)|\[[^\]]*\]", " ", text)
    text = EMOJI.sub("", text)
    text = drop_non_roman(text)
    text = re.sub(r"^\s*(?:dadaji|grandpa)\s*[:\-–]\s*", "", text, flags=re.I)
    text = re.sub(r"\s+", " ", text)
    return re.sub(r"\s+([,.?!])", r"\1", text).strip()


# Spoken digits ("nine eight seven six", "ek do teen char") count as numbers too.
NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4", "five": "5", "six": "6",
    "seven": "7", "eight": "8", "nine": "9", "shunya": "0", "ek": "1", "do": "2", "teen": "3",
    "char": "4", "chaar": "4", "panch": "5", "paanch": "5", "chhe": "6", "chheh": "6",
    "saat": "7", "aath": "8", "nau": "9",
}
_NUM_TOKEN = r"(?:\d+|" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")"
_NUM_RUN = re.compile(rf"\b{_NUM_TOKEN}(?:[\s,.\-–…]+{_NUM_TOKEN}){{3,}}\b", re.I)


def spoken_to_digits(text: str) -> str:
    """Turn runs of 4+ number words into digits: "ek do teen char" -> "1234"."""
    def join(m: re.Match) -> str:
        tokens = re.findall(rf"\b{_NUM_TOKEN}\b", m.group(), re.I)
        return "".join(NUMBER_WORDS.get(t.lower(), t) for t in tokens)
    return _NUM_RUN.sub(join, text)


DIGIT_RUN = re.compile(r"(?<!\w)\d(?:[\s\-.,]?\d){3,}(?!\w)")  # 4+ digits, single separators ok
MONEY = re.compile(r"₹|\brs\.?|\binr\b|rup[ae]|rupiya|lakh|\blac\b|hazaa?r|crore|karod|paise", re.I)
SECRET_WORDS = re.compile(r"\b(?:otp|pin|cvv|password|passcode)\b", re.I)
ID_PATTERNS = {
    "PAN-like ID": re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b", re.I),
    "IFSC-like code": re.compile(r"\b[A-Z]{4}0[A-Z0-9]{6}\b", re.I),
    "UPI ID or email": re.compile(r"[\w.\-]{2,}@[a-z]{2,}", re.I),
    "secret code": re.compile(r"\b(?:otp|pin|cvv|password|passcode)\b\D{0,15}\d{3,}", re.I),
}
CHARACTER_BREAKS = re.compile(r"""
    \bas\s+an\s+ai\b | \blanguage\s+model\b | \bi'?m\s+(?:just\s+)?an?\s+(?:ai|bot)\b
  | \bi\s+am\s+(?:just\s+)?an?\s+(?:ai|bot)\b | \bchat\s?bot\b | \bvirtual\s+assistant\b
  | \bopenai\b | \bsystem\s+prompt\b | \bmy\s+(?:instructions|programming)\b
  | \bi\s+can(?:no|')t\s+(?:help|assist)\b | \bmain\s+(?:ek\s+)?(?:ai|bot|robot)\s+hoon\b
""", re.I | re.X)
PROFANITY = re.compile(
    r"\b(?:fuck\w*|shit|bitch|bastard|asshole|chutiya|madarchod|behenchod|bhenchod|bhosdi\w*"
    r"|gandu|randi|harami"
    # name-calling: Grumpy Dadaji may grumble, but never insult the caller
    r"|bewa?koof|bevakoof|gadhe?|ullu|nalayak|nikamm[ae])\b", re.I)


def luhn_ok(digits: str) -> bool:
    """The checksum real card numbers pass. A Luhn-valid 16-digit number could be someone's card."""
    total = 0
    for i, d in enumerate(reversed(digits)):
        n = int(d) * (2 if i % 2 else 1)
        total += n - 9 if n > 9 else n
    return total % 10 == 0


def find_problems(text: str) -> list[str]:
    problems = []
    normalised = spoken_to_digits(text.replace("’", "'"))
    for m in DIGIT_RUN.finditer(normalised):
        digits = re.sub(r"\D", "", m.group())
        nearby = normalised[max(0, m.start() - 15): m.end() + 15]
        if 13 <= len(digits) <= 19 and luhn_ok(digits):
            problems.append("card-like number")
        elif SECRET_WORDS.search(nearby):
            problems.append(f"{len(digits)}-digit code near OTP/PIN")
        elif MONEY.search(nearby) and len(digits) <= 7:
            continue  # "25,000 rupaye pension" is fine
        elif len(digits) == 4 and 1900 <= int(digits) <= 2099:
            continue  # "1965 mein railway join kiya" is fine
        else:
            problems.append(f"{len(digits)}-digit number")
    problems += [name for name, rx in ID_PATTERNS.items() if rx.search(normalised)]
    if CHARACTER_BREAKS.search(normalised):
        problems.append("broke character")
    if PROFANITY.search(normalised):
        problems.append("abusive language")
    if NON_ROMAN.search(normalised):
        problems.append("non-Roman script")
    if not text:
        problems.append("empty reply")
    return list(dict.fromkeys(problems))  # dedupe, keep order


@dataclass
class OutputCheck:
    text: str
    problems: list[str] = field(default_factory=list)


def check_output(reply: str) -> OutputCheck:
    text = clean(reply)
    return OutputCheck(text, find_problems(text))


def redact(text: str) -> str:
    """For the guardrail log: show what was blocked without repeating the number."""
    return re.sub(r"\d", "•", text)


async def safe_reply(generate: Callable[[str | None], Awaitable[str]],
                     fallbacks: tuple[str, ...]) -> tuple[str, list[dict]]:
    """Get a reply that passes the checks: one retry with feedback, then a canned stall line.

    generate(note) returns a draft; note says why the previous draft was blocked (or None).
    Returns (reply, blocks) where blocks logs each rejected draft for the case file.
    """
    blocks, note = [], None
    for _ in range(2):
        result = check_output(await generate(note))
        if not result.problems:
            return result.text, blocks
        blocks.append({"draft": redact(result.text), "problems": result.problems})
        note = (f"Your previous draft was blocked ({', '.join(result.problems)}). Say something "
                "different, in character, in Roman letters only, with no numbers, IDs or codes.")
    return random.choice(fallbacks), blocks
