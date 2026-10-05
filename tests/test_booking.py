from datetime import date, datetime

import pytest

from clinic import booking
from tests.conftest import NOW

SUNDAY = date(2026, 10, 4)


@pytest.mark.parametrize("message, expected", [
    ("باجر", date(2026, 10, 5)),
    ("بكرة العصر", date(2026, 10, 5)),
    ("عقب باجر", date(2026, 10, 6)),
    ("يوم الخميس", date(2026, 10, 8)),
    ("السبت الصبح", date(2026, 10, 10)),
    ("12/10", date(2026, 10, 12)),
    ("tomorrow", date(2026, 10, 5)),
    ("اليوم", SUNDAY),
])
def test_parse_day(message, expected):
    assert booking.parse_day(message, SUNDAY) == expected


def test_parse_hour_assumes_pm_for_small_numbers():
    assert booking.parse_hour("الساعة 5") == (17, 0)
    assert booking.parse_hour("٤:٣٠") == (16, 30)
    assert booking.parse_hour("الساعة 10") == (10, 0)


def test_find_service_prefers_longest_match(engine):
    services = booking.load_services(engine)
    assert booking.find_service("ابي تنظيف بشرة", services).code == "hydrafacial"
    assert booking.find_service("ابي تنظيف", services).code == "cleaning"
    assert booking.find_service("كشف جلدية", services).code == "skin_consult"


def test_no_slots_on_friday_and_none_in_the_past(engine):
    services = {s.code: s for s in booking.load_services(engine)}
    assert booking.free_slots(engine, services["checkup"], date(2026, 10, 9), NOW) == []  # Friday
    today = booking.free_slots(engine, services["checkup"], SUNDAY, NOW, limit=50)
    assert all(s.start >= datetime(2026, 10, 4, 11, 0) for s in today)


def test_double_booking_is_impossible(engine):
    service = {s.code: s for s in booking.load_services(engine)}["cleaning"]
    slot = booking.free_slots(engine, service, date(2026, 10, 5), NOW)[0]
    booking.book(engine, "+96511111111", "A", service, slot, NOW)
    with pytest.raises(booking.SlotTaken):
        booking.book(engine, "+96522222222", "B", service, slot, NOW)
    assert slot.start not in [s.start for s in booking.free_slots(engine, service, date(2026, 10, 5), NOW)]


def test_patient_cannot_cancel_someone_elses_appointment(engine):
    service = booking.load_services(engine)[0]
    slot = booking.free_slots(engine, service, date(2026, 10, 5), NOW)[0]
    appt = booking.book(engine, "+96511111111", "A", service, slot, NOW)
    assert not booking.cancel(engine, appt, "+96599999999")
    assert booking.cancel(engine, appt, "+96511111111")
