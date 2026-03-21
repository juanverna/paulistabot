import logging
import numpy as np
import cv2
from io import BytesIO

from telegram import Update
from telegram.ext import CallbackContext
from telegram import ParseMode

from bot.states import SCAN_QR, START_TIME
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import push_state

logger = logging.getLogger(__name__)


def scan_qr(update: Update, context: CallbackContext) -> int:
    # Descargar foto
    bio = BytesIO()
    update.message.photo[-1].get_file().download(out=bio)

    # Decodificar QR
    arr = np.frombuffer(bio.getvalue(), dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    detector = cv2.QRCodeDetector()
    data, _, _ = detector.detectAndDecode(img)

    if not data:
        update.message.reply_text(
            "No encontré un QR válido. Por favor, intentá de nuevo.",
            parse_mode=ParseMode.HTML,
        )
        return SCAN_QR

    data = data.strip().rstrip("|")
    parts = data.split("|")

    if len(parts) != 4:
        update.message.reply_text(
            "El contenido del QR no tiene el formato correcto.",
            parse_mode=ParseMode.HTML,
        )
        return SCAN_QR

    numero_evt, direccion_evt, codigo_evt, tipo_evt = parts
    context.user_data.update({
        "numero_evento":  numero_evt,
        "direccion_qr":   direccion_evt,
        "codigo_interno": codigo_evt,
        "tipo_evento_qr": tipo_evt,
    })

    update.message.reply_text("✅ Datos del QR cargados con éxito.")
    push_state(context, SCAN_QR)
    update.message.reply_text(
        apply_bold_keywords("¿A qué hora empezaste el trabajo? (formato HH:MM)"),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = START_TIME
    return START_TIME
