"""The assistant's brain: decides what to do with each WhatsApp message.

    message
      → conversation owned by a human?          → stay silent
      → guardrails (redact personal data, flag prompt injection)
      → symptoms / complaint / "I want a person" → hand off to reception (always, even mid-booking)
      → in the middle of booking or cancelling?  → continue that flow
      → book / cancel / "my appointments"        → booking tools (deterministic, confirm before writing)
      → greeting / thanks                        → short reply
      → question                                 → knowledge base
            best match too weak?                 → hand off ("I'd rather not guess")
            LLM phrases the answer from the facts; it may say NO_ANSWER (→ hand off),
            and any number not in the facts rejects the LLM answer (→ article text instead)
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime
from typing import Callable

from sqlalchemy import Engine

from clinic import booking, config, guardrails, handoff, llm
from clinic.booking import Service, Slot
from clinic.rag import Retriever
from clinic.text import has_any, is_arabic, to_latin_digits, tokens

# --------------------------------------------------------------------------- intent words
# Written as people type them on WhatsApp; matching is on normalised text (see text.py).
HUMAN = ["موظف", "موظفه", "اكلم الاستقبال", "ابي الاستقبال", "حولني", "حولوني", "انسان", "شخص حقيقي", "اكلم احد", "اكلم شخص", "ابي اكلم", "كلموني",
         "اتصلوا علي", "تتصلون علي", "human", "agent", "real person", "receptionist", "speak to someone",
         "talk to someone", "call me"]
MEDICAL = ["الم", "الالم", "يعور", "يعورني", "عوار", "وجع", "توجع", "نزيف", "ينزف", "ورم", "متورم", "انتفاخ",
           "منتفخ", "التهاب", "ملتهب", "خراج", "حراره", "دوا", "دواء", "مضاد", "مسكن", "تشخيص", "شنو اخذ",
           "طارئ", "طوارئ", "حالة طارئه", "pain", "painful", "hurts", "bleeding", "swollen", "swelling",
           "infection", "antibiotic", "painkiller", "medicine", "diagnos", "emergency", "urgent", "fever"]
COMPLAINT = ["شكوى", "شكوي", "اشتكي", "زعلان", "مو راضي", "تعامل سيء", "خدمه سيئه", "complain", "refund",
             "استرجاع", "ابي فلوسي", "rude", "terrible service"]
CANCEL = ["الغي", "الغاء", "كنسل", "اكنسل", "cancel"]
CANCEL_POLICY = ["سياسه", "policy", "رسوم", "fee", "قبل كم", "how early"]
MY_BOOKINGS = ["موعدي", "مواعيدي", "حجزي", "حجوزاتي", "my appointment", "my booking", "when is my"]
BOOK = ["احجز", "حجز", "موعد", "ابي موعد", "ابغي موعد", "ودي موعد", "appointment", "book"]
GREETING = ["مرحبا", "هلا", "اهلا", "السلام", "سلام", "هاي", "صباح الخير", "مساء الخير", "hi", "hello", "hey",
            "good morning", "good evening"]
THANKS = ["شكرا", "مشكور", "مشكوره", "يعطيك العافيه", "تسلم", "تسلمين", "thanks", "thank you", "thx"]
YES = ["نعم", "اي", "ايه", "ايوه", "ايوا", "اكيد", "تمام", "اوكي", "اوك", "ok", "okay", "yes", "yeah", "yep",
       "sure", "confirm", "اكد", "ماشي", "زين", "ابشر", "يب"]
NO = ["لا", "لاء", "no", "nope", "مو", "ماابي", "ما ابي", "مابي"]
ABORT = ["خلاص", "بطلت", "ما ابي", "مابي", "stop", "never mind", "forget it"]


@dataclass
class Reply:
    answer: str
    route: str = ""   # faq / booking / cancel / my_bookings / handoff / refusal / smalltalk / silent
    sources: list[str] = field(default_factory=list)
    score: float | None = None
    used_llm: bool = False
    redacted: list[str] = field(default_factory=list)
    handoff_id: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Flow:
    """A booking or cancellation in progress for one phone number."""
    kind: str                      # booking / cancel
    lang: str
    step: str = ""                 # service / day / slot / confirm / choose / confirm_cancel
    service: Service | None = None
    day: date | None = None
    period: str | None = None
    near: tuple[int, int] | None = None
    slots: list[Slot] = field(default_factory=list)
    chosen: Slot | None = None
    appointments: list[booking.Appointment] = field(default_factory=list)
    target: booking.Appointment | None = None


def _t(lang: str, ar: str, en: str) -> str:
    return ar if lang == "ar" else en


class Agent:
    def __init__(self, engine: Engine, retriever: Retriever | None = None,
                 notify: handoff.Notifier | None = None, clock: Callable[[], datetime] | None = None,
                 threshold: float | None = None, staff_to: str | None = None):
        self.engine = engine
        self.retriever = retriever or Retriever()
        self.notify = notify
        self.clock = clock or (lambda: datetime.now(config.TZ))
        self.threshold = config.ANSWER_THRESHOLD if threshold is None else threshold
        self.staff_to = config.STAFF_WHATSAPP if staff_to is None else staff_to
        self.services = booking.load_services(engine)
        self.flows: dict[str, Flow] = {}

    # ------------------------------------------------------------------ entry point
    def chat(self, phone: str, message: str, name: str = "") -> Reply:
        now = self.clock().replace(tzinfo=None)
        flow = self.flows.get(phone)
        lang = "ar" if is_arabic(message) else ("en" if re.search(r"[A-Za-z]", message) or not flow else flow.lang)

        if handoff.is_human_owned(self.engine, phone):
            return Reply("", route="silent")

        guard = guardrails.check(message)
        msg = guard.text
        if guard.injection:
            return Reply(_t(lang, "أقدر أساعدك بس بمواعيدك ومعلومات العيادة 😊 شلون أقدر أخدمك؟",
                            "I can only help with your appointments and clinic information. How can I help?"),
                         route="refusal", redacted=guard.redacted)

        reason = self._handoff_reason(msg)
        if reason:
            self.flows.pop(phone, None)
            return self._handoff(phone, name, reason, msg, lang, now, guard.redacted)

        if flow and has_any(msg, MY_BOOKINGS):  # "when is my appointment?" ends whatever was in progress
            self.flows.pop(phone, None)
            flow = None
        if flow:
            reply = self._continue_flow(phone, flow, msg, lang, name, now)
            if reply:
                reply.redacted = guard.redacted
                return reply
            # the message didn't fit the flow — maybe it's a side question ("how much is it?")
            faq = self._faq(phone, name, msg, lang, now, allow_handoff=False)
            prompt = self._flow_prompt(flow, flow.lang)
            if faq:
                faq.answer += "\n\n" + prompt
                return faq
            return Reply(_t(flow.lang, "ما فهمت عليك 🙏 ", "Sorry, I didn't get that. ") + prompt, route=flow.kind)

        reply = self._route(phone, msg, lang, name, now)
        reply.redacted = guard.redacted
        return reply

    # ------------------------------------------------------------------ routing
    def _handoff_reason(self, msg: str) -> str | None:
        if has_any(msg, MEDICAL):
            return "medical"
        if has_any(msg, COMPLAINT):
            return "complaint"
        if has_any(msg, HUMAN):
            return "asked_for_human"
        return None

    def _route(self, phone: str, msg: str, lang: str, name: str, now: datetime) -> Reply:
        n_tokens = len(tokens(msg))
        if has_any(msg, CANCEL) and not has_any(msg, CANCEL_POLICY):
            return self._start_cancel(phone, lang, now)
        if has_any(msg, MY_BOOKINGS):
            return self._my_bookings(phone, lang, now)
        if has_any(msg, BOOK):
            return self._start_booking(phone, msg, lang, now)
        if has_any(msg, THANKS) and n_tokens <= 5:
            return Reply(_t(lang, "العفو، حياك الله 🌷 إذا تحتاج أي شي ثاني أنا موجود.",
                            "You're welcome! Anything else, just message me."), route="smalltalk")
        if has_any(msg, GREETING) and (n_tokens <= 3 or self.retriever.search(msg, k=1)[0][1] < self.threshold):
            return Reply(self._welcome(lang, name), route="smalltalk")  # "السلام عليكم ورحمة الله" — no question
        if has_any(msg, YES) and n_tokens <= 2:
            return Reply(_t(lang, "👍 أي خدمة ثانية؟", "👍 Anything else I can help with?"), route="smalltalk")
        return self._faq(phone, name, msg, lang, now)

    def _welcome(self, lang: str, name: str) -> str:
        first = name.split()[0] if name else ""
        return _t(lang,
                  f"هلا والله {first} 👋 معاك مساعد عيادة بسمة ونضارة للأسنان والجلدية.\n"
                  "أقدر أساعدك في:\n• الأسعار والخدمات والتأمين\n• حجز موعد أو إلغاؤه\n"
                  "• تحويلك لموظف الاستقبال\nشلون أقدر أخدمك؟",
                  f"Hi {first} 👋 I'm the assistant of Basma & Nadara Dental and Skin Clinic.\n"
                  "I can help with:\n• prices, services and insurance\n• booking or cancelling an appointment\n"
                  "• connecting you to reception\nHow can I help?").replace("  ", " ")

    # ------------------------------------------------------------------ knowledge base
    def _faq(self, phone: str, name: str, msg: str, lang: str, now: datetime,
             allow_handoff: bool = True) -> Reply | None:
        results = self.retriever.search(msg, k=2)
        best, score = results[0]
        if score < self.threshold:
            return self._handoff(phone, name, "not_sure", msg, lang, now, score=score) if allow_handoff else None
        used = [a for a, s in results if s >= self.threshold]
        facts = "\n\n".join(f"[{a.title}]\n{a.ar}\n{a.en}" for a in used)
        sources = [a.slug for a in used]

        answer = llm.generate(msg, facts)
        if answer and llm.NO_ANSWER in answer:
            return self._handoff(phone, name, "not_sure", msg, lang, now, score=score) if allow_handoff else None
        if answer and numbers_are_grounded(answer, facts):
            return Reply(answer, route="faq", sources=sources, score=round(score, 3), used_llm=True)
        greeting = _t(lang, "هلا والله! ", "Hi! ") if has_any(msg, GREETING) else ""
        return Reply(greeting + best.text(lang), route="faq", sources=[best.slug], score=round(score, 3))

    # ------------------------------------------------------------------ handoff
    def _handoff(self, phone: str, name: str, reason: str, msg: str, lang: str, now: datetime,
                 redacted: list[str] | None = None, score: float | None = None) -> Reply:
        hid = handoff.start(self.engine, phone, name, reason, msg, now, self.notify, self.staff_to)
        text = {
            "medical": _t(lang,
                          "سلامتك 🙏 ما أقدر أعطي استشارة طبية عن طريق الواتساب، حولت محادثتك لفريق العيادة "
                          "وبيتواصلون معك بأقرب وقت.\nإذا الحالة طارئة اتصل على 112 أو توجه لأقرب طوارئ.",
                          "Sorry to hear that 🙏 I can't give medical advice over WhatsApp, so I've passed your "
                          "chat to our clinic team and they'll contact you shortly.\nIf it's an emergency, "
                          "call 112 or go to the nearest emergency department."),
            "complaint": _t(lang,
                            "آسفين جداً على هالتجربة 🙏 حولت رسالتك لمسؤول الاستقبال وبيتواصل معك شخصياً.",
                            "We're really sorry about this 🙏 I've passed your message to the reception "
                            "manager, who will contact you personally."),
            "asked_for_human": _t(lang,
                                  "أبشر، حولت محادثتك لموظف الاستقبال 👩‍💼 وبيردون عليك هني بأقرب وقت.",
                                  "Sure — I've passed your chat to our receptionist 👩‍💼 They'll reply here shortly."),
            "not_sure": _t(lang,
                           "سؤال حلو! بس ما عندي معلومة أكيدة عنه، وما أبي أعطيك جواب غلط 🙏\n"
                           "حولت سؤالك لموظف الاستقبال وبيرد عليك هني بأقرب وقت.",
                           "Good question! I don't have a confirmed answer, and I'd rather not guess 🙏\n"
                           "I've passed it to our receptionist, who will reply here shortly."),
        }[reason]
        return Reply(text, route="handoff", handoff_id=hid, redacted=redacted or [],
                     score=None if score is None else round(score, 3))

    # ------------------------------------------------------------------ booking flow
    def _start_booking(self, phone: str, msg: str, lang: str, now: datetime) -> Reply:
        flow = Flow("booking", lang, service=booking.find_service(msg, self.services),
                    day=booking.parse_day(msg, now.date()), period=booking.parse_period(msg),
                    near=booking.parse_hour(msg))
        self.flows[phone] = flow
        return self._advance_booking(phone, flow, now)

    def _advance_booking(self, phone: str, flow: Flow, now: datetime, note: str = "") -> Reply:
        lang = flow.lang
        if flow.service is None:
            flow.step = "service"
        elif flow.day is None:
            flow.step = "day"
        else:
            if flow.near and not flow.period:
                flow.period = "morning" if flow.near[0] < 14 else "evening"
            day, slots = flow.day, booking.free_slots(self.engine, flow.service, flow.day, now, flow.period, flow.near)
            if not slots:
                day, slots = booking.next_free_slots(self.engine, flow.service, flow.day, now, flow.period)
                if day is None:
                    self.flows.pop(phone, None)
                    return self._handoff(phone, "", "not_sure", f"booking: no free slot for {flow.service.code}",
                                         lang, now)
                closed = flow.day.weekday() == 4
                note += _t(lang,
                           "يوم الجمعة العيادة مسكرة. " if closed else
                           f"ما في مواعيد فاضية يوم {booking.fmt_day(flow.day, lang)}. ",
                           "We're closed on Fridays. " if closed else
                           f"No free times on {booking.fmt_day(flow.day, lang)}. ")
                flow.day = day
            flow.slots, flow.step = slots, "slot"
        return Reply(note + self._flow_prompt(flow, lang), route="booking")

    def _flow_prompt(self, flow: Flow, lang: str) -> str:
        if flow.step == "service":
            lines = [f"{i}) {s.name(lang)}" for i, s in enumerate(self.services, 1)]
            return _t(lang, "أبشر! أي خدمة تبي تحجز لها؟ اكتب رقمها أو اسمها 👇\n",
                      "Sure! Which service would you like to book? Send the number or name 👇\n") + "\n".join(lines)
        if flow.step == "day":
            return _t(lang, f"تمام، {flow.service.name(lang)} ✅ أي يوم يناسبك؟ (مثلاً: باجر، الأحد، 12/10) "
                            "وتفضل الصبح ولا العصر؟",
                      f"Great, {flow.service.name(lang)} ✅ Which day suits you? (e.g. tomorrow, Sunday, 12/10) "
                      "Morning or evening?")
        if flow.step == "slot":
            lines = [f"{i}) {booking.fmt_time(s.start, lang)} – {s.doctor(lang)}" for i, s in enumerate(flow.slots, 1)]
            return (_t(lang, f"المواعيد المتاحة لـ{flow.service.name(lang)} يوم {booking.fmt_day(flow.day, lang)}:\n",
                       f"Free times for {flow.service.name(lang)} on {booking.fmt_day(flow.day, lang)}:\n")
                    + "\n".join(lines) + _t(lang, "\nاختار رقم الموعد 👇", "\nReply with the number 👇"))
        if flow.step == "confirm":
            s = flow.chosen
            at = "الساعة" if lang == "ar" else "at"
            return _t(lang, "أأكد لك هالموعد؟\n", "Shall I confirm this appointment?\n") + (
                f"🦷 {flow.service.name(lang)}\n👩‍⚕️ {s.doctor(lang)}\n"
                f"📅 {booking.fmt_day(s.start.date(), lang)} {at} {booking.fmt_time(s.start, lang)}\n"
            ) + _t(lang, "(نعم / لا)", "(yes / no)")
        if flow.step == "choose":
            lines = [f"{i}) {a.describe(lang)}" for i, a in enumerate(flow.appointments, 1)]
            return _t(lang, "أي موعد تبي تلغي؟\n", "Which appointment would you like to cancel?\n") + "\n".join(lines)
        if flow.step == "confirm_cancel":
            return _t(lang, f"أكيد تبي تلغي هالموعد؟\n{flow.target.describe(lang)}\n(نعم / لا)",
                      f"Are you sure you want to cancel this appointment?\n{flow.target.describe(lang)}\n(yes / no)")
        return ""

    def _continue_flow(self, phone: str, flow: Flow, msg: str, lang: str, name: str, now: datetime) -> Reply | None:
        is_no = has_any(msg, NO)
        is_yes = has_any(msg, YES) and not is_no
        aborting = has_any(msg, ABORT) or (flow.kind == "booking" and has_any(msg, CANCEL))
        if aborting and not (flow.step in ("confirm", "confirm_cancel") and is_no):
            self.flows.pop(phone, None)
            return Reply(_t(flow.lang, "تمام، لغيت الطلب 👍 إذا تحتاج شي ثاني أنا موجود.",
                            "OK, I've stopped that 👍 Message me if you need anything else."), route=flow.kind)

        if flow.kind == "cancel":
            return self._continue_cancel(phone, flow, msg, is_yes, is_no, now)

        if flow.step == "service":
            idx = booking.pick_number(msg, len(self.services))
            flow.service = booking.find_service(msg, self.services) or (self.services[idx] if idx is not None else None)
            if flow.service is None:
                return None
            flow.day = flow.day or booking.parse_day(msg, now.date())
            flow.period = flow.period or booking.parse_period(msg)
            return self._advance_booking(phone, flow, now)

        if flow.step == "day":
            day, period, near = booking.parse_day(msg, now.date()), booking.parse_period(msg), booking.parse_hour(msg)
            if day is None and period is None and near is None:
                return None
            flow.day, flow.period, flow.near = day or now.date(), period or flow.period, near
            return self._advance_booking(phone, flow, now)

        if flow.step == "slot":
            new_day, near = booking.parse_day(msg, now.date()), booking.parse_hour(msg)
            idx = None if new_day else booking.pick_number(msg, len(flow.slots))
            if idx is None and near:  # "4:30" or "الساعة 5" matching an offered time
                idx = next((i for i, s in enumerate(flow.slots) if (s.start.hour, s.start.minute) == near), None)
            if idx is not None:
                flow.chosen, flow.step = flow.slots[idx], "confirm"
                return Reply(self._flow_prompt(flow, flow.lang), route="booking")
            if new_day or near or booking.parse_period(msg):
                flow.day = new_day or flow.day
                flow.near = near
                flow.period = booking.parse_period(msg) or (None if new_day else flow.period)
                return self._advance_booking(phone, flow, now)
            return None

        if flow.step == "confirm":
            if is_yes:
                self.flows.pop(phone, None)
                try:
                    appt_id = booking.book(self.engine, phone, name, flow.service, flow.chosen, now)
                except booking.SlotTaken:
                    flow.near = (flow.chosen.start.hour, flow.chosen.start.minute)
                    self.flows[phone] = flow
                    return self._advance_booking(phone, flow, now, _t(
                        flow.lang, "للأسف هالموعد انحجز قبل شوي 😅 ", "Sorry, that time was just taken 😅 "))
                s, lang_ = flow.chosen, flow.lang
                at = "الساعة" if lang_ == "ar" else "at"
                return Reply(_t(lang_, "تم الحجز ✅\n", "Booked ✅\n")
                             + f"🦷 {flow.service.name(lang_)}\n👩‍⚕️ {s.doctor(lang_)}\n"
                               f"📅 {booking.fmt_day(s.start.date(), lang_)} {at} {booking.fmt_time(s.start, lang_)}\n"
                             + _t(lang_, f"رقم الحجز: BN-{appt_id:04d}\n"
                                         "ياريت تكون موجود قبل موعدك بـ 10 دقايق. ولو حبيت تلغي، بس اكتب \"الغي موعدي\".",
                                  f"Booking ref: BN-{appt_id:04d}\n"
                                  "Please arrive 10 minutes early. To cancel, just send \"cancel my appointment\"."),
                             route="booking")
            if is_no:
                flow.chosen, flow.day, flow.near, flow.step = None, None, None, "day"
                return Reply(_t(flow.lang, "تمام، ما حجزت شي. ", "No problem, nothing booked. ")
                             + self._flow_prompt(flow, flow.lang), route="booking")
            return None
        return None

    # ------------------------------------------------------------------ cancel / list
    def _start_cancel(self, phone: str, lang: str, now: datetime) -> Reply:
        appts = booking.upcoming(self.engine, phone, now)
        if not appts:
            return Reply(_t(lang, "ما لقيت مواعيد قادمة مسجلة على هالرقم. تبي أحجز لك موعد؟",
                            "I couldn't find any upcoming appointments for this number. Would you like to book one?"),
                         route="cancel")
        flow = Flow("cancel", lang, appointments=appts)
        if len(appts) == 1:
            flow.target, flow.step = appts[0], "confirm_cancel"
        else:
            flow.step = "choose"
        self.flows[phone] = flow
        return Reply(self._flow_prompt(flow, lang), route="cancel")

    def _continue_cancel(self, phone: str, flow: Flow, msg: str, is_yes: bool, is_no: bool,
                         now: datetime) -> Reply | None:
        lang = flow.lang
        if flow.step == "choose":
            idx = booking.pick_number(msg, len(flow.appointments))
            if idx is None:
                return None
            flow.target, flow.step = flow.appointments[idx], "confirm_cancel"
            return Reply(self._flow_prompt(flow, lang), route="cancel")
        if is_yes:
            self.flows.pop(phone, None)
            booking.cancel(self.engine, flow.target.id, phone)
            return Reply(_t(lang, "تم إلغاء موعدك ✅ تبي أحجز لك موعد ثاني؟",
                            "Your appointment is cancelled ✅ Would you like to book another one?"), route="cancel")
        if is_no:
            self.flows.pop(phone, None)
            return Reply(_t(lang, "تمام، موعدك باقي مثل ما هو 👍", "OK, your appointment stays as it is 👍"),
                         route="cancel")
        return None

    def _my_bookings(self, phone: str, lang: str, now: datetime) -> Reply:
        appts = booking.upcoming(self.engine, phone, now)
        if not appts:
            return Reply(_t(lang, "ما عندك مواعيد قادمة على هالرقم. تبي أحجز لك موعد؟",
                            "You have no upcoming appointments on this number. Would you like to book one?"),
                         route="my_bookings")
        lines = "\n".join(f"• {a.describe(lang)} (BN-{a.id:04d})" for a in appts)
        return Reply(_t(lang, "مواعيدك القادمة:\n", "Your upcoming appointments:\n") + lines, route="my_bookings")


def numbers_are_grounded(answer: str, facts: str) -> bool:
    """Every number in the LLM's answer must appear in the facts. A made-up price or time is
    the worst mistake a clinic assistant can make, so we fall back to the article instead."""
    def numbers(s: str) -> set[str]:
        return {f"{float(n.replace(',', '')):.2f}" for n in re.findall(r"\d[\d,]*(?:\.\d+)?", to_latin_digits(s))}
    return numbers(answer) <= numbers(facts)
