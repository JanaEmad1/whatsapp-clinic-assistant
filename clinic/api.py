"""HTTP API.  Run:  uvicorn clinic.api:app --reload

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

from fastapi import FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from clinic import config, handoff, llm, whatsapp
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
    return Agent(get_engine(), notify=whatsapp.send_message)


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
            "whatsapp": "twilio" if config.TWILIO_ACCOUNT_SID else "not configured"}


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

    # the receptionist gives a chat back to the bot by sending "done <id>"
    if config.STAFF_WHATSAPP and sender == config.STAFF_WHATSAPP and (m := STAFF_RELEASE.match(body)):
        released = handoff.release(get_engine(), int(m.group(1)), get_agent().clock())
        text = f"✅ Handoff #{m.group(1)} closed — the bot is answering {released} again." if released \
            else f"No handoff #{m.group(1)} found."
        return Response(whatsapp.twiml(text), media_type="application/xml")

    result = _handle(phone, body, form.get("ProfileName", ""))
    return Response(whatsapp.twiml(result["answer"]), media_type="application/xml")


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
