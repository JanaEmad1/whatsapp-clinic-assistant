"""Booking tools: understand dates/services in Gulf Arabic or English, find free slots,
book and cancel.

Everything here is deterministic code over the database — the LLM is never involved in
booking, so it can't invent a time slot or double-book a doctor. All SQL is fixed and
parameterised; a patient can only see and cancel appointments made from their own number.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from sqlalchemy import Engine, text

from clinic.text import has_any, normalize, tokens

# --------------------------------------------------------------------------- services
# Words patients use for each bookable service (longest match wins, so "تنظيف بشرة" beats "تنظيف").
SERVICE_ALIASES = {
    "checkup": ["كشف اسنان", "فحص اسنان", "فحص", "كشف", "checkup", "check-up", "check up", "dental exam"],
    "cleaning": ["تنظيف اسنان", "تنظيف الاسنان", "تنظيف", "جير", "cleaning", "scaling", "polish"],
    "filling": ["حشوه", "حشوات", "تسوس", "filling", "cavity"],
    "root_canal": ["علاج عصب", "عصب", "root canal"],
    "whitening": ["تبييض", "تبيض", "whitening", "bleaching"],
    "ortho": ["تقويم", "braces", "orthodont"],
    "skin_consult": ["استشاره جلديه", "جلديه", "دكتوره جلديه", "حب الشباب", "كلف", "تصبغات", "dermatolog", "skin consult", "acne"],
    "hydrafacial": ["تنظيف بشره", "تنظيف البشره", "هيدرافيشل", "فيشل", "hydrafacial", "facial"],
    "laser": ["ليزر", "ازاله شعر", "ازاله الشعر", "laser", "hair removal"],
    "botox": ["بوتكس", "بوتوكس", "botox"],
}


@dataclass(frozen=True)
class Service:
    code: str
    department: str
    name_ar: str
    name_en: str
    minutes: int
    doctor_ids: tuple[int, ...]

    def name(self, lang: str) -> str:
        return self.name_ar if lang == "ar" else self.name_en


@dataclass(frozen=True)
class Slot:
    doctor_id: int
    doctor_ar: str
    doctor_en: str
    start: datetime
    end: datetime

    def doctor(self, lang: str) -> str:
        return self.doctor_ar if lang == "ar" else self.doctor_en


class SlotTaken(Exception):
    """Someone else booked the slot between offering it and the patient's 'yes'."""


def load_services(engine: Engine) -> list[Service]:
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT code, department, name_ar, name_en, minutes, doctor_ids "
                                 "FROM services ORDER BY department, rowid")).all()
    return [Service(r[0], r[1], r[2], r[3], r[4], tuple(int(d) for d in r[5].split(","))) for r in rows]


def find_service(message: str, services: list[Service]) -> Service | None:
    norm = normalize(message)
    best, best_len = None, 0
    by_code = {s.code: s for s in services}
    for code, aliases in SERVICE_ALIASES.items():
        for alias in aliases:
            a = normalize(alias)
            hit = a in norm if (" " in a or len(a) >= 5) else has_any(norm, [a])
            if hit and len(a) > best_len and code in by_code:
                best, best_len = by_code[code], len(a)
    return best


# --------------------------------------------------------------------------- dates & times
_AR_DAYS = ["الإثنين", "الثلاثاء", "الأربعاء", "الخميس", "الجمعة", "السبت", "الأحد"]
_EN_DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
_WEEKDAY_WORDS = {
    0: ["الاثنين", "الاتنين", "الثنين", "يوم اثنين", "monday"],
    1: ["الثلاثا", "يوم ثلاثا", "tuesday"],
    2: ["الاربعا", "يوم اربعا", "wednesday"],
    3: ["الخميس", "يوم خميس", "thursday"],
    4: ["الجمعه", "يوم جمعه", "friday"],
    5: ["السبت", "يوم سبت", "saturday"],
    6: ["الاحد", "يوم احد", "sunday"],
}
MORNING_WORDS = ["الصبح", "صباحا", "الصباح", "صبح", "الظهر", "ظهر", "morning", "am"]
EVENING_WORDS = ["العصر", "عصر", "المسا", "مساء", "المغرب", "بالليل", "الليل", "evening", "afternoon", "night", "pm"]


def parse_day(message: str, today: date) -> date | None:
    norm = normalize(message)
    if has_any(norm, ["عقب باجر", "بعد باجر", "بعد بكره", "day after tomorrow"]):
        return today + timedelta(days=2)
    if has_any(norm, ["باجر", "بكره", "بكرا", "غدا", "tomorrow"]):
        return today + timedelta(days=1)
    if has_any(norm, ["اليوم", "today", "الحين"]):
        return today
    for weekday, words in _WEEKDAY_WORDS.items():
        if has_any(norm, words):
            return today + timedelta(days=(weekday - today.weekday()) % 7)
    m = re.search(r"\b(\d{1,2})[/\-.](\d{1,2})\b", norm)
    if m:
        try:
            d = date(today.year, int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None
        return d if d >= today else date(today.year + 1, d.month, d.day)
    return None


def parse_period(message: str) -> str | None:
    if has_any(message, EVENING_WORDS):
        return "evening"
    if has_any(message, MORNING_WORDS):
        return "morning"
    return None


def parse_hour(message: str) -> tuple[int, int] | None:
    """'الساعة 5' / 'at 5' / '4:30' → (hour, minute) in 24h, assuming clinic hours (9–21)."""
    norm = normalize(message)
    m = re.search(r"\b(\d{1,2}):(\d{2})\b", norm) or re.search(r"(?:الساعه|at)\s*(\d{1,2})\b", norm)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.lastindex and m.lastindex >= 2 else 0
    if 1 <= hour <= 8:
        hour += 12  # "5" at a clinic open 9–21 means 5 PM
    return (hour, minute) if 0 <= hour <= 23 and minute < 60 else None


def fmt_day(d: date, lang: str) -> str:
    if lang == "ar":
        return f"{_AR_DAYS[d.weekday()]} {d.day}/{d.month}"
    return f"{_EN_DAYS[d.weekday()]} {d.day}/{d.month}"


def fmt_time(t: datetime, lang: str) -> str:
    h12 = t.hour % 12 or 12
    clock = f"{h12}:{t.minute:02d}"
    if lang != "ar":
        return f"{clock} {'AM' if t.hour < 12 else 'PM'}"
    part = "الصبح" if t.hour < 12 else "الظهر" if t.hour < 15 else "العصر" if t.hour < 18 else "بالليل"
    return f"{clock} {part}"


def pick_number(message: str, upto: int) -> int | None:
    """The patient's choice from a numbered list: '2', '٢', 'الثاني', 'second' → index 1."""
    ordinals = [["الاول", "اول", "first", "1st"], ["الثاني", "ثاني", "second", "2nd"],
                ["الثالث", "ثالث", "third", "3rd"]]
    for tok in tokens(message):
        if tok.isdigit() and 1 <= int(tok) <= upto:
            return int(tok) - 1
    for i, words in enumerate(ordinals[:upto]):
        if has_any(message, words):
            return i
    return None


# --------------------------------------------------------------------------- calendar
def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M")


def free_slots(engine: Engine, service: Service, day: date, now: datetime, period: str | None = None,
               near: tuple[int, int] | None = None, limit: int = 3) -> list[Slot]:
    ids = ",".join(str(i) for i in service.doctor_ids)  # ints from our own table, safe to inline
    with engine.connect() as conn:
        shifts = conn.execute(text(
            f'SELECT s.doctor_id, d.name_ar, d.name_en, s.start, s."end" FROM shifts s '
            f"JOIN doctors d ON d.id = s.doctor_id WHERE s.weekday = :wd AND s.doctor_id IN ({ids})"),
            {"wd": day.weekday()}).all()
        booked = conn.execute(text(
            f'SELECT doctor_id, start, "end" FROM appointments WHERE status = \'booked\' '
            f"AND doctor_id IN ({ids}) AND start >= :d0 AND start < :d1"),
            {"d0": day.isoformat(), "d1": (day + timedelta(days=1)).isoformat()}).all()

    earliest = now.replace(tzinfo=None) + timedelta(hours=1)
    length = timedelta(minutes=service.minutes)
    found: dict[datetime, Slot] = {}
    for doc, name_ar, name_en, s, e in shifts:
        t = datetime.combine(day, datetime.strptime(s, "%H:%M").time())
        stop = datetime.combine(day, datetime.strptime(e, "%H:%M").time())
        while t + length <= stop:
            busy = any(b[0] == doc and b[1] < _iso(t + length) and b[2] > _iso(t) for b in booked)
            in_period = period is None or (t.hour < 14) == (period == "morning")
            if not busy and in_period and t >= earliest and t not in found:
                found[t] = Slot(doc, name_ar, name_en, t, t + length)
            t += timedelta(minutes=30)

    slots = sorted(found.values(), key=lambda sl: sl.start)
    if near:
        target = datetime.combine(day, datetime.min.time()).replace(hour=near[0], minute=near[1])
        slots = sorted(sorted(slots, key=lambda sl: abs(sl.start - target))[:limit], key=lambda sl: sl.start)
    return slots[:limit]


def next_free_slots(engine: Engine, service: Service, from_day: date, now: datetime,
                    period: str | None = None, horizon: int = 14) -> tuple[date | None, list[Slot]]:
    for offset in range(horizon):
        day = from_day + timedelta(days=offset)
        slots = free_slots(engine, service, day, now, period)
        if slots:
            return day, slots
    return None, []


def book(engine: Engine, phone: str, name: str, service: Service, slot: Slot, now: datetime) -> int:
    with engine.begin() as conn:
        clash = conn.execute(text(
            'SELECT COUNT(*) FROM appointments WHERE doctor_id = :doc AND status = \'booked\' '
            'AND start < :end AND "end" > :start'),
            {"doc": slot.doctor_id, "start": _iso(slot.start), "end": _iso(slot.end)}).scalar()
        if clash:
            raise SlotTaken
        result = conn.execute(text(
            'INSERT INTO appointments (phone, patient_name, doctor_id, service_code, start, "end", created_at) '
            "VALUES (:phone, :name, :doc, :code, :start, :end, :now)"),
            {"phone": phone, "name": name or "WhatsApp patient", "doc": slot.doctor_id, "code": service.code,
             "start": _iso(slot.start), "end": _iso(slot.end), "now": _iso(now)})
        return int(result.lastrowid)


@dataclass(frozen=True)
class Appointment:
    id: int
    service_ar: str
    service_en: str
    doctor_ar: str
    doctor_en: str
    start: datetime

    def describe(self, lang: str) -> str:
        service, doctor = (self.service_ar, self.doctor_ar) if lang == "ar" else (self.service_en, self.doctor_en)
        at = "الساعة" if lang == "ar" else "at"
        return f"{service} – {doctor} – {fmt_day(self.start.date(), lang)} {at} {fmt_time(self.start, lang)}"


def upcoming(engine: Engine, phone: str, now: datetime) -> list[Appointment]:
    with engine.connect() as conn:
        rows = conn.execute(text(
            "SELECT a.id, s.name_ar, s.name_en, d.name_ar, d.name_en, a.start FROM appointments a "
            "JOIN services s ON s.code = a.service_code JOIN doctors d ON d.id = a.doctor_id "
            "WHERE a.phone = :phone AND a.status = 'booked' AND a.start >= :now ORDER BY a.start"),
            {"phone": phone, "now": _iso(now)}).all()
    return [Appointment(r[0], r[1], r[2], r[3], r[4], datetime.fromisoformat(r[5])) for r in rows]


def cancel(engine: Engine, appointment_id: int, phone: str) -> bool:
    with engine.begin() as conn:
        result = conn.execute(text(
            "UPDATE appointments SET status = 'cancelled' WHERE id = :id AND phone = :phone AND status = 'booked'"),
            {"id": appointment_id, "phone": phone})
        return result.rowcount == 1
