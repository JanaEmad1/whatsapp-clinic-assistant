"""Settings, read from environment variables (and a local .env file if present)."""
from __future__ import annotations

import os
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Tiny .env reader so we don't need an extra dependency."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv(ROOT / ".env")

DB_PATH = Path(os.getenv("CLINIC_DB", ROOT / "data" / "clinic.db"))
DB_URL = f"sqlite:///{DB_PATH.as_posix()}"
KB_DIR = ROOT / "clinic" / "kb"
REPORTS_DIR = ROOT / "reports"

# Kuwait is UTC+3 all year (no daylight saving), so a fixed offset is exact.
TZ = timezone(timedelta(hours=3), "Asia/Kuwait")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# Twilio WhatsApp (sandbox or a real sender). Without them the bot still works over /chat.
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
TWILIO_WHATSAPP_FROM = os.getenv("TWILIO_WHATSAPP_FROM", "whatsapp:+14155238886")  # sandbox number
# Public URL Twilio calls (e.g. your ngrok https URL + /whatsapp); needed to check signatures.
PUBLIC_WEBHOOK_URL = os.getenv("PUBLIC_WEBHOOK_URL", "")
# The receptionist's WhatsApp number, e.g. whatsapp:+965XXXXXXXX. Gets a message on every handoff.
STAFF_WHATSAPP = os.getenv("STAFF_WHATSAPP", "")
ADMIN_TOKEN = os.getenv("ADMIN_TOKEN", "")

# Below this retrieval score the bot does not answer from the knowledge base — it hands off.
# Chosen from the sweep in reports/eval.md.
ANSWER_THRESHOLD = float(os.getenv("CLINIC_ANSWER_THRESHOLD", "0.10"))
