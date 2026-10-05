# Demo video: script and reuse

One 60–90 second screen recording of a real WhatsApp chat, reused three ways.

## Before recording

- Put `GEMINI_API_KEY` in `.env` so the replies sound natural (without it the bot pastes whole articles).
- Run `python -m data.seed` so the calendar is fresh.
- Start `uvicorn clinic.api:app --port 8000` and `ngrok http 8000`, then set the webhook. Use the Meta Cloud API
  steps in the README (free test number), or Twilio where its trial is available.
- If you can, set `STAFF_WHATSAPP` to a second phone so the receptionist alert appears in the video. Send one
  message from that phone to the bot first, so the alert can be delivered.
- The free Gemini tier allows only a few requests per minute. Pause about 10 s between questions; booking steps
  don't use Gemini.
- Phone: Do Not Disturb on, and save the bot's number as a contact named "عيادة بسمة ونضارة".
- Record with the phone's built-in screen recorder, or show WhatsApp Web next to the terminal logs.

## Script (about 75 s)

| # | Patient types | What it shows | ~sec |
|---|---|---|---|
| 1 | السلام عليكم | Dialect welcome menu | 5 |
| 2 | بكم تنظيف الأسنان؟ | Price straight from the clinic's information | 8 |
| 3 | تقبلون تأمين الوفرة؟ | Grounded insurance answer | 8 |
| 4 | أبي موعد تنظيف باجر العصر | Real free slots from the calendar | 8 |
| 5 | 2 | Summary + "أأكد لك هالموعد؟" | 5 |
| 6 | نعم | Booked ✅ with a reference number | 6 |
| 7 | عندكم خصم للطلاب؟ | **Not in the info → "I'd rather not guess" → hands off** | 10 |
| 8 | (cut to staff phone) | 🔔 Handoff alert with a wa.me link | 6 |
| 9 | عندي ألم قوي بضرسي شنو آخذ؟ (send `done <id>` from the staff phone first) | No medical advice → handoff + 112 | 10 |

Captions to overlay, one per beat: *"Answers only from the clinic's info"*, *"Books real slots — asks before
saving"*, *"Doesn't know? Doesn't guess — hands off to a human"*.

## LinkedIn post (draft)

> Most AI chatbots fail clinics in one way: they make things up. A wrong price or a made-up policy on
> WhatsApp costs a clinic real patients.
>
> I built a WhatsApp receptionist for a (fictional) Kuwaiti dental & skin clinic that:
> ✅ replies in Kuwaiti dialect or English
> ✅ answers only from the clinic's own information, and checks every price against it
> ✅ books, lists and cancels real appointments, and asks before saving anything
> ✅ hands the chat to a human when it isn't sure, or when someone describes symptoms
>
> On 66 test messages: 98.5% routed correctly and 0 wrong answers. 🎥 60-second demo below.
> Code: github.com/JanaEmad1/whatsapp-clinic-assistant
>
> If you run a clinic or salon in the Gulf and your team answers the same WhatsApp questions all day, let's talk.
> #AI #WhatsApp #Kuwait #Chatbot #LLM

## Upwork portfolio item

**Title:** Arabic/English WhatsApp AI receptionist: bookings plus no made-up answers

**Description:** A WhatsApp assistant for a clinic that answers in Gulf Arabic or English from the business's
own information, books and cancels appointments against a real calendar, and hands off to staff whenever it is
unsure. Every price and number in its replies is checked against the source. Evaluated on 66 dialect messages:
98.5% correct routing, 0 wrong answers. Stack: Python, FastAPI, Twilio WhatsApp, Gemini, SQLite, Docker, CI.

**Skills:** Chatbot development, WhatsApp API, Twilio, LLM, RAG, Arabic NLP, Python, FastAPI

## Outreach message (draft, Arabic)

> هلا والله 👋 أنا جنى، أبني مساعدين ذكاء اصطناعي للواتساب للعيادات والصالونات.
> المساعد يرد على الأسئلة المتكررة (الأسعار، الدوام، التأمين) باللهجة الكويتية من معلوماتكم أنتم بس،
> ويحجز المواعيد، ويحول للموظف إذا ما كان متأكد، فما يعطي أي معلومة غلط للعميل.
> مرفق فيديو قصير (دقيقة) يوضح الفكرة. إذا يناسبكم أسويلكم نسخة تجريبية على معلومات عيادتكم مجاناً.
