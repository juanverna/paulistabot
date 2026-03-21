import os
import logging

logger = logging.getLogger(__name__)

def _require(key: str) -> str:
    value = os.getenv(key)
    if not value:
        raise EnvironmentError(f"Variable de entorno requerida no encontrada: {key}")
    return value

TELEGRAM_BOT_TOKEN = _require("TELEGRAM_BOT_TOKEN")
EMAIL_ADDRESS      = _require("EMAIL_ADDRESS")
EMAIL_PASSWORD     = _require("EMAIL_PASSWORD")
CC_EMAIL           = os.getenv("CC_EMAIL")          # opcional
PHASH_THRESHOLD    = int(os.getenv("PHASH_THRESHOLD", "8"))
