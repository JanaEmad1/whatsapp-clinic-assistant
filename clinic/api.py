"""HTTP API.  Run:  uvicorn clinic.api:app --reload

    GET  /meta, POST /meta              Meta WhatsApp Cloud API webhook (verify, then messages)
    POST /whatsapp                      Twilio webhook (form-encoded), replies with TwiML
    POST /chat                          JSON, for local testing without WhatsApp
    GET  /health
    GET  /admin/handoffs                open handoffs          (header X-Admin-Token)
    POST /admin/handoffs/{id}/release   give the chat back to the bot
"""
from __future__ import annotations

import logging
import re
import time
from functools import lru_cache

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field

from clinic import config, handoff, llm, meta_whatsapp, whatsapp
from clinic.agent import Agent
from clinic.db import get_engine

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("clinic.api")

app = FastAPI(title="Clinic WhatsApp Assistant",
              description="Gulf-Arabic WhatsApp assistant for a fictional Kuwaiti clinic")

STAFF_RELEASE = re.compile(r"^\s*(?:done|release|تم)\s*#?\s*(\d+)\s*$", re.I)


class ChatRequest(BaseModel):
    phone: str = Field(..., min_length=4, max_length=32, examples=["+96550001234"])
    message: str = Field(..., min_length=1, max_length=1000, examples=["بكم تنظيف الأسنان؟"])
    name: str = Field("", max_length=64, examples=["Fatma"])


@lru_cache(maxsize=1)
def get_agent() -> Agent:
    # staff alerts go out on whichever WhatsApp channel is configured
    notify = meta_whatsapp.send_message if meta_whatsapp.configured() else whatsapp.send_message
    return Agent(get_engine(), notify=notify)


def _digits(number: str) -> str:
    return "".join(ch for ch in number if ch.isdigit())


def _is_staff(sender: str) -> bool:
    return bool(config.STAFF_WHATSAPP) and _digits(sender) == _digits(config.STAFF_WHATSAPP)


def _staff_release(body: str) -> str | None:
    """The receptionist gives a chat back to the bot by sending "done <id>"."""
    m = STAFF_RELEASE.match(body)
    if not m:
        return None
    released = handoff.release(get_engine(), int(m.group(1)), get_agent().clock())
    return (f"✅ Handoff #{m.group(1)} closed — the bot is answering {released} again." if released
            else f"No handoff #{m.group(1)} found.")


def _handle(phone: str, message: str, name: str) -> dict:
    start = time.perf_counter()
    reply = get_agent().chat(phone, message, name)
    latency_ms = round((time.perf_counter() - start) * 1000)
    # log decisions and latency, never the raw message (it may contain personal data)
    log.info("chat route=%s sources=%s score=%s llm=%s redacted=%s latency_ms=%s",
             reply.route, reply.sources, reply.score, reply.used_llm, reply.redacted, latency_ms)
    return {**reply.to_dict(), "latency_ms": latency_ms}


@app.get("/health")
def health() -> dict:
    agent = get_agent()
    return {"status": "ok", "answer_threshold": agent.threshold, "articles": len(agent.retriever.articles),
            "llm": "gemini" if llm.available() else "template-only",
            "whatsapp": "meta" if meta_whatsapp.configured() else "twilio" if config.TWILIO_ACCOUNT_SID
            else "not configured"}


@app.post("/chat")
def chat(request: ChatRequest) -> dict:
    return _handle(request.phone, request.message, request.name)


@app.post("/whatsapp")
async def whatsapp_webhook(request: Request) -> Response:
    form = {k: str(v) for k, v in (await request.form()).items()}
    if config.TWILIO_AUTH_TOKEN:
        url = config.PUBLIC_WEBHOOK_URL or str(request.url)
        if not whatsapp.signature_ok(url, form, request.headers.get("X-Twilio-Signature", ""),
                                     config.TWILIO_AUTH_TOKEN):
            raise HTTPException(403, "bad Twilio signature")

    sender, body = form.get("From", ""), form.get("Body", "").strip()
    phone = sender.removeprefix("whatsapp:")
    if not phone or not body:
        return Response(whatsapp.twiml(None), media_type="application/xml")

    if _is_staff(sender) and (text := _staff_release(body)):
        return Response(whatsapp.twiml(text), media_type="application/xml")

    result = _handle(phone, body, form.get("ProfileName", ""))
    return Response(whatsapp.twiml(result["answer"]), media_type="application/xml")


# ---------------------------------------------------------------- Meta WhatsApp Cloud API
_seen_message_ids: set[str] = set()  # Meta retries a webhook if it's slow, so ignore repeats


@app.get("/meta")
def meta_verify(request: Request) -> PlainTextResponse:
    """One-time handshake when you save the webhook URL in the Meta app dashboard."""
    q = request.query_params
    if (q.get("hub.mode") == "subscribe" and config.META_VERIFY_TOKEN
            and q.get("hub.verify_token") == config.META_VERIFY_TOKEN):
        return PlainTextResponse(q.get("hub.challenge", ""))
    raise HTTPException(403, "verify token mismatch")


def _reply_meta(msg: meta_whatsapp.Incoming) -> None:
    if _is_staff(msg.phone) and (text := _staff_release(msg.text)):
        meta_whatsapp.send_message(msg.phone, text)
        return
    result = _handle("+" + msg.phone, msg.text, msg.name)
    if result["answer"]:  # empty while a human owns the chat
        meta_whatsapp.send_message(msg.phone, result["answer"])


@app.post("/meta")
async def meta_webhook(request: Request, background: BackgroundTasks) -> dict:
    raw = await request.body()
    if config.META_APP_SECRET and not meta_whatsapp.signature_ok(
            raw, request.headers.get("X-Hub-Signature-256", ""), config.META_APP_SECRET):
        raise HTTPException(403, "bad Meta signature")
    for msg in meta_whatsapp.parse(await request.json()):
        if msg.message_id in _seen_message_ids:
            continue
        _seen_message_ids.add(msg.message_id)
        background.add_task(_reply_meta, msg)  # answer Meta with 200 now, reply right after
    return {"status": "ok"}


def _check_admin(token: str | None) -> None:
    if not config.ADMIN_TOKEN or token != config.ADMIN_TOKEN:
        raise HTTPException(401, "set ADMIN_TOKEN and send it as X-Admin-Token")


@app.get("/admin/handoffs")
def list_handoffs(x_admin_token: str | None = Header(None)) -> list[dict]:
    _check_admin(x_admin_token)
    return handoff.open_handoffs(get_engine())


@app.post("/admin/handoffs/{handoff_id}/release")
def release_handoff(handoff_id: int, x_admin_token: str | None = Header(None)) -> dict:
    _check_admin(x_admin_token)
    phone = handoff.release(get_engine(), handoff_id, get_agent().clock())
    if phone is None:
        raise HTTPException(404, "no such handoff")
    return {"released": handoff_id, "phone": phone}
