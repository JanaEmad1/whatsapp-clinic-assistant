"""Meta WhatsApp Cloud API glue: verify the webhook, check that a request really comes from
Meta, pull the text messages out of a webhook payload, and send replies.

Unlike Twilio, Meta doesn't take the reply in the HTTP response: we answer the webhook with
200 straight away and send the reply with a separate API call.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
from dataclasses import dataclass

import httpx

from clinic import config

log = logging.getLogger(__name__)

GRAPH_URL = "https://graph.facebook.com/v21.0"


def configured() -> bool:
    return bool(config.META_ACCESS_TOKEN and config.META_PHONE_NUMBER_ID)


def signature_ok(raw_body: bytes, header: str, app_secret: str) -> bool:
    """Meta signs each webhook: X-Hub-Signature-256: sha256=<HMAC-SHA256(app secret, raw body)>."""
    expected = "sha256=" + hmac.new(app_secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, header or "")


@dataclass(frozen=True)
class Incoming:
    message_id: str
    phone: str      # E.164 without "+", as Meta sends it, e.g. 96550001234
    name: str
    text: str


def parse(payload: dict) -> list[Incoming]:
    """Text messages in a webhook payload. Delivery/read status updates and media are ignored."""
    out = []
    for entry in payload.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            names = {c.get("wa_id"): c.get("profile", {}).get("name", "") for c in value.get("contacts", [])}
            for msg in value.get("messages", []):
                if msg.get("type") == "text":
                    out.append(Incoming(msg["id"], msg["from"], names.get(msg["from"], ""), msg["text"]["body"]))
    return out


def send_message(to: str, body: str) -> None:
    """Send a free-form text. Only delivered inside the 24 h window after the person last wrote to us."""
    to = "".join(ch for ch in to if ch.isdigit())
    if not configured():
        log.info("Meta WhatsApp not configured — would send to %s: %s", to, body.splitlines()[0])
        return
    try:
        httpx.post(f"{GRAPH_URL}/{config.META_PHONE_NUMBER_ID}/messages", timeout=15,
                   headers={"Authorization": f"Bearer {config.META_ACCESS_TOKEN}"},
                   json={"messaging_product": "whatsapp", "to": to, "type": "text",
                         "text": {"body": body}}).raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Meta send failed: %s", exc)
