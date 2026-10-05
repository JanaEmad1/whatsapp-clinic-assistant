"""Input guardrails: redact personal data before it reaches the LLM or the logs,
and flag obvious prompt-injection attempts (English and Arabic).

These are simple, readable rules — a first layer, not a complete defence. The strongest
protection is architectural: the LLM cannot touch the database or book anything on its own
(see booking.py and agent.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from clinic.text import to_latin_digits

_PATTERNS = [
    # card numbers: 13-19 digits, optionally split by spaces/dashes; checked with Luhn below
    ("CARD", re.compile(r"\b(?:\d[ -]?){13,19}\b")),
    # Kuwaiti civil ID: 12 digits starting with 2 or 3 (century digit)
    ("CIVIL_ID", re.compile(r"\b[23]\d{11}\b")),
    ("EMAIL", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    # phones: international (+...), or a Kuwaiti 8-digit mobile/landline (starts 2, 4, 5, 6 or 9)
    ("PHONE", re.compile(r"(?<!\w)(?:\+\d[\d ()-]{7,}\d|[24569]\d{3}[ -]?\d{4})\b")),
    ("CVV", re.compile(r"\b(?:cvv|cvc|security code)\D{0,5}\d{3,4}\b", re.I)),
]

_INJECTION = re.compile(
    r"ignore (all |any )?(previous|prior|above) (instructions|rules)"
    r"|disregard (the |your )?(system|previous) (prompt|instructions)"
    r"|you are now|act as (an? )?(admin|developer|system)"
    r"|reveal (your|the) (system )?prompt|show (me )?(your|the) system prompt"
    r"|other (patient|customer|user)'?s? (appointment|booking|data|record)"
    r"|(تجاهل|انس[ىي]|اترك) (كل )?(التعليمات|الأوامر|الاوامر|القواعد)"
    r"|(اعطني|عطني|ورني|وريني) (ال)?(برومبت|التعليمات)",
    re.I,
)


def _luhn_ok(digits: str) -> bool:
    total, parity = 0, len(digits) % 2
    for i, ch in enumerate(digits):
        d = int(ch)
        if i % 2 == parity:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


@dataclass
class GuardResult:
    text: str
    redacted: list[str] = field(default_factory=list)
    injection: bool = False


def check(message: str) -> GuardResult:
    message = to_latin_digits(message)
    text, found = message, []
    for kind, pattern in _PATTERNS:
        def _replace(m: re.Match) -> str:
            if kind == "CARD" and not _luhn_ok(re.sub(r"\D", "", m.group())):
                return m.group()  # a long number that is not a card
            found.append(kind)
            return f"[{kind}]"
        text = pattern.sub(_replace, text)
    return GuardResult(text, found, bool(_INJECTION.search(message)))
