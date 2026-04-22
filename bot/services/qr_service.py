import logging
import numpy as np
import cv2
from io import BytesIO
from PIL import Image

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext

from bot.states import SCAN_QR, TANK_TYPE
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import push_state

logger = logging.getLogger(__name__)


def _fix_encoding(text: str) -> str:
    """Corrige caracteres mal codificados en el QR (ej: # → Ñ)."""
    return text.replace("#", "Ñ")


def _decode_qr_opencv(img_bytes: bytes) -> str:
    """Intenta decodificar el QR con OpenCV."""
    try:
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(img)
        return data or ""
    except Exception as e:
        logger.warning("OpenCV QR falló: %s", e)
        return ""


def _decode_qr_pyzbar(img_bytes: bytes) -> str:
    """Fallback: intenta decodificar con pyzbar."""
    try:
        from pyzbar.pyzbar import decode
        img = Image.open(BytesIO(img_bytes))
        results = decode(img)
        if results:
            return results[0].data.decode("utf-8", errors="replace")
    except Exception as e:
        logger.warning("pyzbar QR falló: %s", e)
    return ""


def _decode_qr_opencv_enhanced(img_bytes: bytes) -> str:
    """Segunda pasada de OpenCV con preprocesamiento de imagen."""
    try:
        arr = np.frombuffer(img_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)

        # Escalar imagen si es muy pequeña
        h, w = img.shape[:2]
        if max(h, w) < 800:
            scale = 800 / max(h, w)
            img = cv2.resize(img, (int(w * scale), int(h * scale)))

        # Convertir a escala de grises y aplicar umbralización
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

        detector = cv2.QRCodeDetector()
        data, _, _ = detector.detectAndDecode(thresh)
        return data or ""
    except Exception as e:
        logger.warning("OpenCV enhanced QR falló: %s", e)
        return ""


def scan_qr(update: Update, context: CallbackContext) -> int:
    # Descargar foto
    bio = BytesIO()
    update.message.photo[-1].get_file().download(out=bio)
    img_bytes = bio.getvalue()

    # Intentar decodificar con múltiples métodos
    data = (
        _decode_qr_opencv(img_bytes) or
        _decode_qr_opencv_enhanced(img_bytes) or
        _decode_qr_pyzbar(img_bytes)
    )

    if not data:
        update.message.reply_text(
            "No encontré un QR válido. Intentá con mejor iluminación o más cerca del código.",
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

    context.user_data.update({
        "numero_evento":  numero_orden,
        "direccion_qr":   direccion,
        "codigo_interno": codigo_cliente,
        "tipo_evento_qr": tipo_trabajo,
    })

    push_state(context, SCAN_QR)
    update.message.reply_text("✅ QR leído correctamente.")

    if service == "Fumigaciones":
        from bot.states import START_TIME
        update.message.reply_text(
            apply_bold_keywords("¿A qué hora empezaste el trabajo? (formato HH:MM)"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = START_TIME
        return START_TIME

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
