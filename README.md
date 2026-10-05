# Clinic WhatsApp Assistant (Gulf Arabic / English)

[![CI](https://github.com/JanaEmad1/whatsapp-clinic-assistant/actions/workflows/ci.yml/badge.svg)](https://github.com/JanaEmad1/whatsapp-clinic-assistant/actions/workflows/ci.yml)

A WhatsApp receptionist for a **fictional** Kuwaiti dental & skin clinic. It speaks Kuwaiti dialect
and English, and it does three things:

1. **Answers only from the clinic's own information.** If it isn't written down, the bot doesn't guess.
2. **Books, lists and cancels appointments** against a real calendar, with no double bookings and nothing
   saved until the patient says yes.
3. **Hands off to a human** when it isn't sure, when someone describes symptoms or makes a complaint, or
   when the patient asks for a person. The receptionist gets a WhatsApp alert and the bot stays silent in
   that chat until the receptionist gives it back.

> 🎥 **Demo video:** _(add the link to the 60–90 s screen recording here)_

It reuses the design of [FinPilot](https://github.com/JanaEmad1/finpilot): the code decides what to do, the
LLM only phrases the answer, every number is checked against the facts, and a release gate runs in CI.

```
patient on WhatsApp ──► Twilio ──► POST /whatsapp
                                      │
         human owns this chat? ───────┤──► stay silent
         prompt injection? ───────────┤──► polite refusal
         symptoms / complaint / "a person please" ──► HANDOFF (alert to reception)
         booking / cancel in progress? ┤──► continue the flow (deterministic, confirm before saving)
         "أبي موعد" / "الغي موعدي" ─────┤──► booking tools (SQL, no LLM)
         question ────────────────────┘
               │ knowledge-base search (char + word TF-IDF)
               ├─ best match too weak ─────────────────────► HANDOFF ("I'd rather not guess")
               ├─ Gemini phrases answer from the facts only
               │     says NO_ANSWER ───────────────────────► HANDOFF
               │     number not in the facts ──────────────► use the article text instead
               └─ reply in the patient's language/dialect
```

## Why it doesn't make things up: three layers

| Layer | What it does | Where |
|---|---|---|
| 1. Retrieval threshold | If no article matches well enough, hand off without calling the LLM | `clinic/rag.py`, `ANSWER_THRESHOLD` |
| 2. Facts-only prompt | Gemini sees only the matching articles and must reply `NO_ANSWER` if they don't answer the question | `clinic/llm.py` |
| 3. Number check | Any price, time or number in the reply that is not in the facts → the LLM reply is thrown away | `numbers_are_grounded` in `clinic/agent.py` |

Bookings never go through the LLM at all. Free slots come from SQL over doctors' shifts and existing
appointments, and a booking is re-checked inside the transaction so two patients can't get the same slot.

## Results

From `python -m eval.run` (66 hand-written Gulf-Arabic and English messages, LLM off). The full report is in [reports/eval.md](reports/eval.md).

| Metric | Value |
|---|---|
| Correct route (answer / book / cancel / handoff / …) | **98.5%** |
| Knowledge-base questions answered from the right article | **97.6%** |
| **Wrong answers** (answered when it should have handed off, or from the wrong article) | **0** |

The threshold (0.10) is the value with zero wrong answers and the most questions answered; the sweep is in the
report. CI fails if a change brings back any wrong answer. Caveat: the threshold was tuned on the same 66
messages, so treat these numbers as optimistic until real chats are added.

## Run it

```bash
python -m venv .venv && .venv/Scripts/activate      # Windows; on Mac/Linux: source .venv/bin/activate
pip install -r requirements.txt
python -m data.seed            # creates data/clinic.db (doctors, shifts, services, busy calendar)
pytest                         # 37 tests, offline
python -m eval.run             # writes reports/eval.md
python -m clinic.cli           # chat in the terminal
uvicorn clinic.api:app --reload
```

Copy `.env.example` to `.env` and add `GEMINI_API_KEY` for natural dialect replies. Without a key the
bot still works and replies with the article text.

```bash
curl -X POST localhost:8000/chat -H "content-type: application/json" \
     -d '{"phone": "+96550001234", "message": "بكم تنظيف الأسنان؟"}'
```

### Connect WhatsApp (Twilio sandbox, ~10 minutes)

1. Create a free Twilio account. Go to **Messaging → Try it out → Send a WhatsApp message**, and from your
   phone send the `join <code>` message it shows to the sandbox number.
2. Start the API and expose it: `uvicorn clinic.api:app --port 8000`, then `ngrok http 8000`.
3. In the sandbox settings, set **When a message comes in** to `https://<your-ngrok>.ngrok-free.app/whatsapp` (POST).
4. In `.env`, set `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `PUBLIC_WEBHOOK_URL` (the exact URL from step 3,
   used to verify Twilio's signature). Optionally set `STAFF_WHATSAPP` to the receptionist's number, which
   must also join the sandbox.
5. Message the sandbox number: «السلام عليكم».

The receptionist gets an alert like `🔔 Handoff #3 — Medical question` with a wa.me link to the patient.
They reply from their own phone, then send `done 3` to the bot number to give the chat back to the bot.
Open handoffs are also available at `GET /admin/handoffs` (header `X-Admin-Token`).

### Docker

```bash
docker build -t clinic-assistant . && docker run -p 8000:8000 --env-file .env clinic-assistant
```

## Project layout

```
clinic/
  agent.py        routing, booking/cancel conversations, handoff decisions
  booking.py      Arabic/English date & service parsing, free slots, book/cancel (SQL)
  rag.py          knowledge-base loading and retrieval (character + word TF-IDF)
  llm.py          Gemini REST client, facts-only prompt
  guardrails.py   PII redaction (civil ID, phone, card, email) and prompt-injection checks
  handoff.py      human takeover, staff alert, release
  whatsapp.py     Twilio signature check, TwiML, outbound messages
  text.py         Arabic normalisation (hamza, ta marbuta, Arabic-Indic digits)
  api.py          FastAPI: /whatsapp, /chat, /health, /admin/handoffs
  cli.py          terminal chat
  kb/*.md         the clinic's information: 14 short articles, Arabic + English
data/seed.py      fictional clinic: 3 doctors, shifts, 10 bookable services
eval/             66 test messages + evaluation and CI gate
tests/            unit and API tests
```

## Adapting it to a real clinic or salon

- Replace `clinic/kb/*.md` with the business's own information (same format), and edit `data/seed.py` for its
  staff, shifts and services.
- Add the business's real customer questions to `eval/cases.jsonl` and re-run `python -m eval.run` to re-pick
  the threshold.
- Move from the Twilio sandbox to an approved WhatsApp Business sender.

## Limitations and next steps

- Booking conversations are kept in memory, so a server restart forgets a half-finished booking. Booked
  appointments and handoffs are stored in the database. A small Redis or DB table would fix this.
- Keyword rules decide *booking vs. question vs. handoff*. They are transparent and testable, but they will miss
  some phrasings. Logging misses and adding them to the eval set is the intended loop.
- The number check catches invented numbers, not invented words. That is why the prompt must reply
  `NO_ANSWER` and why the retrieval threshold comes first.
- No reminders yet. A day-before WhatsApp reminder needs a Twilio-approved message template.

All names, numbers, doctors and insurers in this repo are fictional.
