"""Devanagari to Roman Hinglish, for Whisper transcripts.

Whisper is told the call is in Hindi (so it never writes Urdu script), but then it often
writes Hindi words in Devanagari: "मुझे OTP बताओ". Everything downstream (injection phrases,
spoken number words, evidence regexes, the dashboard) expects Roman Hinglish, so transcripts
are converted: "mujhe OTP bataao".

It's a simple letter-by-letter table plus one Hindi rule, "schwa deletion": a consonant's
built-in "a" is not pronounced at the end of a word (आठ = aath, not aatha) or between two
pronounced syllables (करना = karna, not karana). Not perfect, but readable and regex-friendly.
"""
import re

VOWELS = {  # independent vowel letters
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
}
MATRAS = {  # vowel signs written on a consonant
    "ा": "aa", "ि": "i", "ी": "ee", "ु": "u", "ू": "oo", "ृ": "ri",
    "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ॉ": "o", "ॅ": "e",
}
CONSONANTS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n", "च": "ch", "छ": "chh", "ज": "j",
    "झ": "jh", "ञ": "n", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n", "त": "t",
    "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh",
    "म": "m", "य": "y", "र": "r", "ल": "l", "ळ": "l", "व": "v", "श": "sh", "ष": "sh",
    "स": "s", "ह": "h",
    # with a nukta dot, precomposed: क़ ख़ ग़ ज़ ड़ ढ़ फ़ य़
    "क़": "k", "ख़": "kh", "ग़": "g", "ज़": "z", "ड़": "d",
    "ढ़": "dh", "फ़": "f", "य़": "y",
}
NUKTA = {"क": "k", "ख": "kh", "ग": "g", "ज": "z", "ड": "d", "ढ": "dh", "फ": "f", "य": "y"}
VIRAMA, NUKTA_SIGN = "्", "़"
NASAL = {"ं": "n", "ँ": "n"}  # anusvara, chandrabindu
VISARGA = "ः"
PUNCT = str.maketrans({"।": ".", "॥": ".", "ऽ": "", **{chr(0x0966 + d): str(d) for d in range(10)}})
WORD = re.compile(r"[ऀ-ॿ]+")


class Syllable:
    def __init__(self, consonant: str, vowel: str, inherent: bool = False):
        self.consonant, self.vowel, self.inherent, self.tail = consonant, vowel, inherent, ""


def _syllables(word: str) -> list[Syllable]:
    out: list[Syllable] = []
    i = 0
    while i < len(word):
        ch = word[i]
        if ch in VOWELS:
            out.append(Syllable("", VOWELS[ch]))
        elif ch in CONSONANTS:
            roman = CONSONANTS[ch]
            if i + 1 < len(word) and word[i + 1] == NUKTA_SIGN:  # क + ़ written separately
                roman, i = NUKTA.get(ch, roman), i + 1
            nxt = word[i + 1] if i + 1 < len(word) else ""
            if nxt in MATRAS:
                out.append(Syllable(roman, MATRAS[nxt]))
                i += 1
            elif nxt == VIRAMA:  # a cluster: no vowel at all ("स्" in "रूल्स")
                out.append(Syllable(roman, ""))
                i += 1
            else:
                out.append(Syllable(roman, "a", inherent=True))
        elif ch in NASAL and out:
            out[-1].tail += NASAL[ch]
        elif ch == VISARGA and out:
            out[-1].tail += "h"
        i += 1
    return out


def _drop_schwas(syl: list[Syllable]):
    """Hindi drops the inherent "a" at the end of a word, and in the middle when a vowel comes
    before it and a consonant with a vowel comes after it. Right to left, as Hindi does.
    One exception: a cluster ending in y/r/v keeps it (शून्य = shoonya, मंत्र = mantra),
    while other clusters don't (रूल्स = rools)."""
    last = syl[-1]
    keep = not syl[-2].vowel and last.consonant in ("y", "r", "v") if len(syl) > 1 else True
    if last.inherent and not last.tail and not keep:
        last.vowel = ""
    for i in range(len(syl) - 2, 0, -1):
        s, before, after = syl[i], syl[i - 1], syl[i + 1]
        if s.inherent and not s.tail and before.vowel and after.consonant and after.vowel:
            s.vowel = ""


def _word(word: str) -> str:
    syl = _syllables(word)
    _drop_schwas(syl)
    if len(syl) > 1 or syl and syl[0].consonant:
        # Hinglish spells long vowels short at the end of a word: का = ka, नहीं = nahin, तू = tu.
        # With a nasal only "ee" shortens; the others stay long: हाँ = haan, हूँ = hoon.
        last = syl[-1]
        short = {"ee": "i"} if last.tail else {"aa": "a", "ee": "i", "oo": "u"}
        last.vowel = short.get(last.vowel, last.vowel)
    return "".join(s.consonant + s.vowel + s.tail for s in syl)


def to_roman(text: str) -> str:
    """Romanise any Devanagari words; Roman text and English words pass through untouched."""
    return WORD.sub(lambda m: _word(m.group()), text.translate(PUNCT))
