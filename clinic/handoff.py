"""Human handoff: when the bot shouldn't answer, a person takes over the chat.

Starting a handoff (1) records it, (2) marks the conversation as owned by a human so the
bot stays silent from then on, and (3) sends the receptionist a WhatsApp alert. The
receptionist replies to the patient from their own phone, then sends "done <id>" to the bot
number (or calls POST /admin/handoffs/<id>/release) to give the chat back to the bot.
"""
from __future__ import annotations

from datetime import datetime
from typing import Callable

from sqlalchemy import Engine, text

Notifier = Callable[[str, str], None]  # (to, body)

REASONS = {
    "asked_for_human": "Patient asked for a person",
    "medical": "Medical question / symptoms",
    "complaint": "Complaint",
    "not_sure": "Bot had no reliable answer",
}


def _now(now: datetime) -> str:
    return now.strftime("%Y-%m-%dT%H:%M")


def is_human_owned(engine: Engine, phone: str) -> bool:
    with engine.connect() as conn:
        owner = conn.execute(text("SELECT owner FROM conversations WHERE phone = :p"), {"p": phone}).scalar()
    return owner == "human"


def start(engine: Engine, phone: str, name: str, reason: str, last_message: str, now: datetime,
          notify: Notifier | None = None, staff_to: str = "") -> int:
    with engine.begin() as conn:
        handoff_id = conn.execute(text(
            "INSERT INTO handoffs (phone, reason, last_message, created_at) VALUES (:p, :r, :m, :t)"),
            {"p": phone, "r": reason, "m": last_message, "t": _now(now)}).lastrowid
        conn.execute(text(
            "INSERT INTO conversations (phone, owner, updated_at) VALUES (:p, 'human', :t) "
            "ON CONFLICT(phone) DO UPDATE SET owner = 'human', updated_at = :t"),
            {"p": phone, "t": _now(now)})
    if notify and staff_to:
        digits = "".join(ch for ch in phone if ch.isdigit())
        notify(staff_to,
               f"🔔 Handoff #{handoff_id} — {REASONS.get(reason, reason)}\n"
               f"Patient: {name or 'unknown'} ({phone})\n"
               f"Last message: {last_message}\n"
               f"Reply to them: https://wa.me/{digits}\n"
               f"When finished, send: done {handoff_id}")
    return int(handoff_id)


def release(engine: Engine, handoff_id: int, now: datetime) -> str | None:
    """Give the conversation back to the bot. Returns the patient's phone, or None if unknown."""
    with engine.begin() as conn:
        phone = conn.execute(text("SELECT phone FROM handoffs WHERE id = :i"), {"i": handoff_id}).scalar()
        if phone is None:
            return None
        conn.execute(text("UPDATE handoffs SET status = 'resolved', resolved_at = :t "
                          "WHERE phone = :p AND status = 'open'"), {"p": phone, "t": _now(now)})
        conn.execute(text("UPDATE conversations SET owner = 'bot', updated_at = :t WHERE phone = :p"),
                     {"p": phone, "t": _now(now)})
    return phone


def open_handoffs(engine: Engine) -> list[dict]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT id, phone, reason, last_message, created_at FROM handoffs "
                                 "WHERE status = 'open' ORDER BY id")).mappings().all()
    return [dict(r) for r in rows]
