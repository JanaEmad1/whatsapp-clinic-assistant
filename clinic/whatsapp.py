"""Twilio WhatsApp glue: check that a webhook really comes from Twilio, build the TwiML
reply, and send messages that are not replies (the receptionist alert)."""
from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from xml.sax.saxutils import escape

import httpx

from clinic import config

log = logging.getLogger(__name__)


def signature_ok(url: str, params: dict[str, str], signature: str, auth_token: str) -> bool:
    """Twilio's scheme: base64(HMAC-SHA1(auth_token, url + each POST param name+value sorted by name))."""
    payload = url + "".join(k + params[k] for k in sorted(params))
    digest = hmac.new(auth_token.encode(), payload.encode("utf-8"), hashlib.sha1).digest()
    return hmac.compare_digest(base64.b64encode(digest).decode(), signature or "")


def twiml(message: str | None) -> str:
    if not message:
        return '<?xml version="1.0" encoding="UTF-8"?><Response/>'
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(message)}</Message></Response>'


def send_message(to: str, body: str) -> None:
    """Send a WhatsApp message through Twilio's REST API. Without credentials it only logs."""
    if not (config.TWILIO_ACCOUNT_SID and config.TWILIO_AUTH_TOKEN):
        log.info("Twilio not configured — would send to %s: %s", to, body.splitlines()[0])
        return
    url = f"https://api.twilio.com/2010-04-01/Accounts/{config.TWILIO_ACCOUNT_SID}/Messages.json"
    try:
        httpx.post(url, data={"From": config.TWILIO_WHATSAPP_FROM, "To": to, "Body": body},
                   auth=(config.TWILIO_ACCOUNT_SID, config.TWILIO_AUTH_TOKEN), timeout=15).raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Twilio send failed: %s", exc)
