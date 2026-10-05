"""Create the fictional clinic's database: doctors, shifts, bookable services and some
existing appointments so the calendar doesn't look empty.

    python -m data.seed            # writes data/clinic.db
"""
from __future__ import annotations

import random
from datetime import datetime, timedelta

from sqlalchemy import Engine, text

from clinic import config
from clinic.db import create_schema, make_engine

SAT, SUN, MON, TUE, WED, THU = 5, 6, 0, 1, 2, 3
WORKDAYS = (SAT, SUN, MON, TUE, WED, THU)  # Friday (4) is closed — matches kb/hours.md
MORNING, EVENING = ("09:00", "13:00"), ("16:00", "21:00")

DOCTORS = [
    (1, "د. نورة العنزي", "Dr. Noura Al-Anzi", "dental"),
    (2, "د. خالد المطيري", "Dr. Khaled Al-Mutairi", "dental"),
    (3, "د. ريم الشمري", "Dr. Reem Al-Shammari", "skin"),
]
# must match kb/doctors.md
SHIFTS = (
    [(1, d, *MORNING) for d in WORKDAYS] + [(1, d, *EVENING) for d in WORKDAYS]
    + [(2, d, *EVENING) for d in WORKDAYS]
    + [(3, d, *EVENING) for d in WORKDAYS] + [(3, SAT, *MORNING)]
)
# code, department, Arabic name, English name, minutes, doctors — must match the price articles
SERVICES = [
    ("checkup", "dental", "كشف وفحص أسنان", "Dental check-up", 30, "1,2"),
    ("cleaning", "dental", "تنظيف أسنان", "Teeth cleaning", 30, "1"),
    ("filling", "dental", "حشوة تجميلية", "Tooth-coloured filling", 30, "1"),
    ("root_canal", "dental", "علاج عصب", "Root canal treatment", 60, "2"),
    ("whitening", "dental", "تبييض أسنان", "Teeth whitening", 60, "1"),
    ("ortho", "dental", "استشارة تقويم", "Orthodontic consultation", 30, "2"),
    ("skin_consult", "skin", "استشارة جلدية", "Dermatology consultation", 30, "3"),
    ("hydrafacial", "skin", "تنظيف بشرة هيدرافيشل", "HydraFacial", 60, "3"),
    ("laser", "skin", "ليزر إزالة الشعر", "Laser hair removal", 30, "3"),
    ("botox", "skin", "بوتوكس", "Botox", 30, "3"),
]


def seed(engine: Engine, busy_days: int = 14, rng_seed: int = 7) -> None:
    create_schema(engine)
    rng = random.Random(rng_seed)
    with engine.begin() as conn:
        for table in ("appointments", "handoffs", "conversations", "shifts", "services", "doctors"):
            conn.execute(text(f"DELETE FROM {table}"))
        conn.execute(text("INSERT INTO doctors VALUES (:id, :ar, :en, :dep)"),
                     [dict(id=i, ar=a, en=e, dep=d) for i, a, e, d in DOCTORS])
        conn.execute(text('INSERT INTO shifts VALUES (:doc, :wd, :s, :e)'),
                     [dict(doc=doc, wd=wd, s=s, e=e) for doc, wd, s, e in SHIFTS])
        conn.execute(text("INSERT INTO services VALUES (:c, :dep, :ar, :en, :m, :docs)"),
                     [dict(c=c, dep=d, ar=a, en=e, m=m, docs=docs) for c, d, a, e, m, docs in SERVICES])

        # ~40% of the 30-minute slots in the next two weeks are already taken
        today = datetime.now(config.TZ).date()
        now = datetime.now(config.TZ).isoformat(timespec="minutes")
        rows = []
        for offset in range(busy_days):
            day = today + timedelta(days=offset)
            for doc, wd, start, end in SHIFTS:
                if wd != day.weekday():
                    continue
                t = datetime.combine(day, datetime.strptime(start, "%H:%M").time())
                stop = datetime.combine(day, datetime.strptime(end, "%H:%M").time())
                while t < stop:
                    if rng.random() < 0.4:
                        code = rng.choice([s[0] for s in SERVICES if str(doc) in s[5] and s[4] == 30])
                        rows.append(dict(phone="+96550000000", name="Existing patient", doc=doc, code=code,
                                         start=t.isoformat(timespec="minutes"),
                                         end=(t + timedelta(minutes=30)).isoformat(timespec="minutes"), now=now))
                    t += timedelta(minutes=30)
        if rows:
            conn.execute(text("INSERT INTO appointments (phone, patient_name, doctor_id, service_code, start, \"end\", "
                              "created_at) VALUES (:phone, :name, :doc, :code, :start, :end, :now)"), rows)


if __name__ == "__main__":
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    seed(make_engine())
    print(f"Seeded {config.DB_PATH}")
