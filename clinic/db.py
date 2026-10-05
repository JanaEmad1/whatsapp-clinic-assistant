"""Database connection and schema."""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine, text

from clinic import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS doctors (
    id         INTEGER PRIMARY KEY,
    name_ar    TEXT NOT NULL,
    name_en    TEXT NOT NULL,
    department TEXT NOT NULL            -- dental / skin
);
CREATE TABLE IF NOT EXISTS shifts (
    doctor_id INTEGER NOT NULL REFERENCES doctors(id),
    weekday   INTEGER NOT NULL,         -- Python weekday: 0 = Monday ... 4 = Friday, 5 = Saturday
    start     TEXT NOT NULL,            -- HH:MM, Kuwait time
    "end"     TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS services (
    code       TEXT PRIMARY KEY,
    department TEXT NOT NULL,
    name_ar    TEXT NOT NULL,
    name_en    TEXT NOT NULL,
    minutes    INTEGER NOT NULL,
    doctor_ids TEXT NOT NULL            -- comma-separated doctors who give this service
);
CREATE TABLE IF NOT EXISTS appointments (
    id           INTEGER PRIMARY KEY,
    phone        TEXT NOT NULL,
    patient_name TEXT NOT NULL,
    doctor_id    INTEGER NOT NULL REFERENCES doctors(id),
    service_code TEXT NOT NULL REFERENCES services(code),
    start        TEXT NOT NULL,         -- ISO, Kuwait time, e.g. 2026-10-06T16:30
    "end"        TEXT NOT NULL,
    status       TEXT NOT NULL DEFAULT 'booked',   -- booked / cancelled
    created_at   TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS conversations (
    phone      TEXT PRIMARY KEY,
    owner      TEXT NOT NULL DEFAULT 'bot',        -- bot / human
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS handoffs (
    id          INTEGER PRIMARY KEY,
    phone       TEXT NOT NULL,
    reason      TEXT NOT NULL,          -- asked_for_human / medical / complaint / not_sure
    last_message TEXT NOT NULL,         -- already redacted by guardrails
    status      TEXT NOT NULL DEFAULT 'open',      -- open / resolved
    created_at  TEXT NOT NULL,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_appt_doctor_start ON appointments(doctor_id, start);
CREATE INDEX IF NOT EXISTS ix_appt_phone ON appointments(phone);
"""


def make_engine(url: str | None = None) -> Engine:
    return create_engine(url or config.DB_URL, future=True)


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine()


def create_schema(engine: Engine) -> None:
    with engine.begin() as conn:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                conn.execute(text(statement))
