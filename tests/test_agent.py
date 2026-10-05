from clinic import handoff, llm
from clinic.agent import numbers_are_grounded
from tests.conftest import NOW

PHONE = "+96560001111"


def test_answers_price_from_the_knowledge_base(agent):
    reply = agent.chat(PHONE, "بكم تنظيف الأسنان؟")
    assert reply.route == "faq" and "25" in reply.answer


def test_unknown_question_hands_off_and_alerts_staff(agent, alerts):
    reply = agent.chat(PHONE, "هل يوجد خصم للطلاب؟")
    assert reply.route == "handoff" and reply.handoff_id
    assert alerts and alerts[0][0] == "whatsapp:+96511112222" and PHONE in alerts[0][1]


def test_medical_question_always_hands_off_even_mid_booking(agent):
    agent.chat(PHONE, "ابي احجز تنظيف")
    reply = agent.chat(PHONE, "بس عندي ألم قوي بضرسي شنو آخذ؟")
    assert reply.route == "handoff" and "112" in reply.answer
    assert PHONE not in agent.flows


def test_bot_stays_silent_until_staff_releases(agent, engine):
    hid = agent.chat(PHONE, "ابي اكلم موظف").handoff_id
    assert agent.chat(PHONE, "هلا؟").route == "silent"
    handoff.release(engine, hid, NOW)
    assert agent.chat(PHONE, "السلام عليكم").route == "smalltalk"


def test_full_booking_flow_needs_explicit_yes(agent):
    reply = agent.chat(PHONE, "أبي موعد تنظيف باجر العصر", "Fatma")
    assert reply.route == "booking" and "1)" in reply.answer
    assert "(نعم / لا)" in agent.chat(PHONE, "2").answer
    assert agent.chat(PHONE, "ما فهمت").route in ("booking", "faq")  # not booked yet
    done = agent.chat(PHONE, "نعم")
    assert "BN-" in done.answer
    assert "BN-" in agent.chat(PHONE, "متى موعدي؟").answer


def test_saying_no_does_not_book(agent):
    agent.chat(PHONE, "ابي موعد كشف باجر الصبح")
    agent.chat(PHONE, "1")
    reply = agent.chat(PHONE, "لا")
    assert "ما حجزت" in reply.answer
    assert "ما عندك مواعيد" in agent.chat(PHONE, "متى موعدي؟").answer


def test_cancel_flow(agent):
    agent.chat(PHONE, "ابي موعد كشف باجر الصبح")
    agent.chat(PHONE, "1")
    agent.chat(PHONE, "اي")
    assert agent.chat(PHONE, "ابي الغي موعدي").route == "cancel"
    assert "تم إلغاء" in agent.chat(PHONE, "نعم").answer


def test_english_conversation_gets_english_replies(agent):
    reply = agent.chat(PHONE, "I want to book a botox appointment tomorrow evening")
    assert reply.route == "booking" and "Free times" in reply.answer


def test_side_question_during_booking_is_answered_and_flow_continues(agent):
    agent.chat(PHONE, "ابي احجز تبييض")
    reply = agent.chat(PHONE, "التبييض يسبب حساسية؟")
    assert reply.route == "faq" and "أي يوم يناسبك" in reply.answer


def test_llm_answer_with_invented_number_is_rejected(agent, monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda q, f: "التنظيف بـ 17 د.ك بس 😍")
    reply = agent.chat(PHONE, "بكم تنظيف الأسنان؟")
    assert not reply.used_llm and "17 د.ك بس" not in reply.answer


def test_llm_no_answer_becomes_handoff(agent, monkeypatch):
    monkeypatch.setattr(llm, "generate", lambda q, f: llm.NO_ANSWER)
    assert agent.chat(PHONE, "بكم تنظيف الأسنان؟").route == "handoff"


def test_grounding_check():
    facts = "تنظيف أسنان: 25 د.ك. الدوام 9:00 الصبح."
    assert numbers_are_grounded("التنظيف بـ ٢٥ د.ك ونفتح 9 الصبح", facts)
    assert not numbers_are_grounded("التنظيف بـ 20 د.ك", facts)
