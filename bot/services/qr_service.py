import logging
import numpy as np
import cv2
from io import BytesIO

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext

from bot.states import SCAN_QR, TANK_TYPE
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import push_state

logger = logging.getLogger(__name__)


def _fix_encoding(text: str) -> str:
    """Corrige caracteres mal codificados en el QR (ej: # → Ñ)."""
    return text.replace("#", "Ñ")


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

    numero_orden, direccion, codigo_cliente, tipo_trabajo = [_fix_encoding(p) for p in parts]
    service = context.user_data.get("service", "")

    # Guardar campos del QR — mismo formato para Fumigaciones y Limpieza
    context.user_data.update({
        "numero_evento":  numero_orden,
        "direccion_qr":   direccion,
        "codigo_interno": codigo_cliente,
        "tipo_evento_qr": tipo_trabajo,
    })

    push_state(context, SCAN_QR)
    update.message.reply_text("✅ QR leído correctamente.")

    # Fumigaciones → sigue con hora de inicio (flujo original)
    if service == "Fumigaciones":
        from bot.states import START_TIME
        update.message.reply_text(
            apply_bold_keywords("¿A qué hora empezaste el trabajo? (formato HH:MM)"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = START_TIME
        return START_TIME

    # Limpieza de Tanques → muestra botonera tipo de tanque primero
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("CISTERNA",      callback_data="CISTERNA"),
         InlineKeyboardButton("RESERVA",       callback_data="RESERVA"),
         InlineKeyboardButton("INTERMEDIARIO", callback_data="INTERMEDIARIO")],
        [InlineKeyboardButton("ATRAS",         callback_data="back")],
    ])
    update.message.reply_text(
        apply_bold_keywords("Seleccione el tipo de tanque:"),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = TANK_TYPE
    return TANK_TYPE
