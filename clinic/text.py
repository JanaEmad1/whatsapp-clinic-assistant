"""Arabic-aware text helpers.

Gulf Arabic on WhatsApp is written many ways: with or without hamza (أبي / ابي), ة or ه at
the end (عيادة / عياده), Arabic-Indic or Latin digits (٤ / 4). We normalise everything to one
form before matching keywords or searching the knowledge base.
"""
from __future__ import annotations

import re

_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_TASHKEEL = re.compile(r"[\u0617-\u061A\u064B-\u0652\u0640]")  # short vowels + tatweel
_ARABIC = re.compile(r"[\u0600-\u06FF]")
_TOKEN = re.compile(r"[\w:/]+")

# common one-letter prefixes glued to Arabic words: و (and), ب (with/in), ال (the), ف, ل
_PREFIXES = ("", "ال", "و", "ب", "وال", "بال", "ف", "ل", "لل")


def to_latin_digits(text: str) -> str:
    return text.translate(_DIGITS)


def normalize(text: str) -> str:
    text = _TASHKEEL.sub("", to_latin_digits(text))
    text = re.sub("[إأآٱ]", "ا", text)
    text = text.replace("ة", "ه").replace("ى", "ي").replace("ؤ", "و").replace("ئ", "ي").replace("گ", "ك")
    return re.sub(r"\s+", " ", text).strip().lower()


def is_arabic(text: str) -> bool:
    return bool(_ARABIC.search(text))


def tokens(text: str) -> list[str]:
    return _TOKEN.findall(normalize(text))


def has_any(text: str, words: list[str]) -> bool:
    """True if `text` contains any of `words` (both normalised).

    Long words and phrases match as substrings. Short words (< 5 letters) must be a whole
    token, optionally with a glued prefix — otherwise "ألم" (pain) would match "المواعيد".
    """
    norm = normalize(text)
    toks = set(_TOKEN.findall(norm))
    for word in words:
        w = normalize(word)
        if " " in w or len(w) >= 5:
            if w in norm:
                return True
        elif any(p + w in toks for p in _PREFIXES):
            return True
    return False
