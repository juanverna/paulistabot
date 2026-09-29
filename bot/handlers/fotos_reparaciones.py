"""
fotos_reparaciones.py
---------------------
Paso de fotos de las reparaciones de cada tanque (Limpieza y Presupuestos).

Después de que el operario escribe las reparaciones de un tanque, el bot le pide
las fotos de esas reparaciones (puede mandar varias). Si escribe "Listo" sin haber
mandado ninguna, el paso queda trabado hasta que mande una foto o ingrese el
código diario del encargado (ver bot/services/destrabe.py).

Las fotos quedan en user_data["fotos_reparaciones"][sufijo] (sufijo: main/alt1/alt2).
"""

import re
import logging
import unicodedata
from telegram import Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import (REPAIR_PHOTOS, SUGGESTIONS_MAIN, SUGGESTIONS_ALT1, SUGGESTIONS_ALT2)
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import push_state, back_handler, check_special_commands
from bot.services import destrabe

logger = logging.getLogger(__name__)

# sufijo → (clave de reparaciones en user_data, clave del nombre del tanque)
TANQUES = {
    "main": ("repairs",     "selected_category"),
    "alt1": ("repair_alt1", "alternative_1"),
    "alt2": ("repair_alt2", "alternative_2"),
}

# Paso siguiente en el flujo manual: sugerencias del mismo tanque
SIGUIENTE_MANUAL = {
    "main": (SUGGESTIONS_MAIN, "selected_category"),
    "alt1": (SUGGESTIONS_ALT1, "alternative_1"),
    "alt2": (SUGGESTIONS_ALT2, "alternative_2"),
}

ITEM = "reparaciones"

_SIN_REPARACIONES = re.compile(
    r"(no|nada|ninguna|ninguno|-|n/?a|no aplica|sin reparacion(es)?"
    r"|no (tiene|hay|requiere|necesita|lleva)( reparacion(es)?| nada)?"
    r"|ninguna reparacion|no hay que reparar nada)"
)


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.lower()).strip(" .!,;")


def necesita_fotos(reparaciones) -> bool:
    """True si el texto de reparaciones describe alguna reparación."""
    if not reparaciones or not str(reparaciones).strip():
        return False
    return not _SIN_REPARACIONES.fullmatch(_normalizar(str(reparaciones)))


def _nombre_tanque(context: CallbackContext, sufijo: str) -> str:
    return context.user_data.get(TANQUES[sufijo][1], "").capitalize()


def _fotos(context: CallbackContext, sufijo: str) -> list:
    return context.user_data.setdefault("fotos_reparaciones", {}).setdefault(sufijo, [])


def _send(update: Update, context: CallbackContext, text: str) -> None:
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=apply_bold_keywords(text),
        parse_mode=ParseMode.HTML,
    )


def texto_pedido(context: CallbackContext, sufijo: str) -> str:
    return (f"📷 Mandá las fotos de las reparaciones de {_nombre_tanque(context, sufijo)} "
            "(podés mandar varias).\nCuando termines, escribí <b>Listo</b>.")


def pedir_fotos(update: Update, context: CallbackContext, sufijo: str, modo: str) -> int:
    """
    Arranca el paso de fotos de reparaciones de un tanque.
    modo: "manual" (sigue con sugerencias) o "voz" (vuelve al flujo de voz).
    """
    context.user_data["rep_fotos"] = {"sufijo": sufijo, "modo": modo, "trabado": False}
    _send(update, context, texto_pedido(context, sufijo))
    context.user_data["current_state"] = REPAIR_PHOTOS
    return REPAIR_PHOTOS


def reanudar_manual(update: Update, context: CallbackContext, sufijo: str) -> None:
    """Vuelve a este paso con "atrás" desde sugerencias (flujo manual). Las fotos se conservan."""
    context.user_data["rep_fotos"] = {"sufijo": sufijo, "modo": "manual", "trabado": False}
    n = len(_fotos(context, sufijo))
    extra = f"\nYa tenés {n} foto(s) cargada(s)." if n else ""
    _send(update, context, texto_pedido(context, sufijo) + extra)


def pendiente_voz(user_data: dict):
    """Primer tanque (flujo de voz) con reparaciones que todavía no pasó por el paso de fotos."""
    hechos = user_data.get("fotos_reparaciones_hechas", [])
    for sufijo, (clave, _) in TANQUES.items():
        if sufijo not in hechos and necesita_fotos(user_data.get(clave)):
            return sufijo
    return None


def _continuar(update: Update, context: CallbackContext) -> int:
    ctx = context.user_data.pop("rep_fotos", {})
    sufijo = ctx.get("sufijo", "main")
    hechos = context.user_data.setdefault("fotos_reparaciones_hechas", [])
    if sufijo not in hechos:
        hechos.append(sufijo)

    if ctx.get("modo") == "voz":
        from bot.handlers.voice_handler import _go_to_contact
        return _go_to_contact(update, context)

    push_state(context, REPAIR_PHOTOS)
    siguiente, clave_nombre = SIGUIENTE_MANUAL[sufijo]
    nombre = context.user_data.get(clave_nombre, "").capitalize()
    _send(update, context, f"Indique sugerencias p/ la próx limpieza para {nombre}:")
    context.user_data["current_state"] = siguiente
    return siguiente


def _trabar(update: Update, context: CallbackContext, ctx: dict) -> int:
    ctx["trabado"] = True
    nombre = _nombre_tanque(context, ctx["sufijo"])
    _send(update, context, "⚠️ " + destrabe.mensaje_trabado(
        f"Falta la foto de las reparaciones de {nombre}"))
    return REPAIR_PHOTOS


def _es_imagen(update: Update) -> bool:
    if update.message.photo:
        return True
    doc = update.message.document
    return bool(doc and (doc.mime_type or "").startswith("image/"))


def _file_id(update: Update) -> str:
    if update.message.photo:
        return update.message.photo[-1].file_id
    return update.message.document.file_id


def handle_repair_photos(update: Update, context: CallbackContext) -> int:
    ctx = context.user_data.get("rep_fotos")
    if not ctx:
        # No debería pasar: sin contexto no sabemos de qué tanque es
        logger.warning("REPAIR_PHOTOS sin contexto")
        return back_handler(update, context)
    sufijo = ctx["sufijo"]

    # ---------- Fotos ----------
    if update.message.photo or update.message.document:
        if not _es_imagen(update):
            update.message.reply_text("Eso no es una foto. Mandá una foto de la galería.")
            return REPAIR_PHOTOS
        fotos = _fotos(context, sufijo)
        fotos.append(_file_id(update))
        ctx["trabado"] = False
        # Un álbum llega como varios mensajes: respondemos una sola vez por álbum
        grupo = update.message.media_group_id
        if grupo and grupo == ctx.get("ultimo_album"):
            return REPAIR_PHOTOS
        ctx["ultimo_album"] = grupo
        recibido = "✅ Fotos recibidas." if grupo else f"✅ Foto recibida (total: {len(fotos)})."
        update.message.reply_text(
            apply_bold_keywords(f"{recibido} Mandá más o escribí <b>Listo</b>."),
            parse_mode=ParseMode.HTML,
        )
        return REPAIR_PHOTOS

    # ---------- Texto ----------
    text = (update.message.text or "").strip()
    if not text:
        update.message.reply_text("Mandá una foto o escribí Listo.")
        return REPAIR_PHOTOS
    if check_special_commands(text, update, context):
        return ConversationHandler.END

    normal = _normalizar(text)
    if normal == "atras":
        if ctx.get("modo") == "voz":
            update.message.reply_text(
                "En este paso no se puede volver atrás. Si hay que corregir algo, "
                "usá 'Modificar algo' en el resumen final.")
            return REPAIR_PHOTOS
        # Vuelve a pedir el texto de reparaciones: las fotos de este tanque se descartan
        context.user_data.get("fotos_reparaciones", {}).pop(sufijo, None)
        context.user_data.pop("rep_fotos", None)
        return back_handler(update, context)

    if ctx.get("trabado") and destrabe.parece_codigo(text):
        resultado = destrabe.intentar_destrabe(context.user_data, text)
        if resultado == destrabe.OK:
            destrabe.registrar_destrabe(context.user_data, _nombre_tanque(context, sufijo),
                                        ITEM, destrabe.MOTIVO_FOTO_FALTANTE)
            update.message.reply_text("✅ Código correcto. Seguimos.")
            return _continuar(update, context)
        if resultado == destrabe.BLOQUEADO:
            update.message.reply_text(destrabe.mensaje_bloqueado())
            return REPAIR_PHOTOS
        update.message.reply_text("❌ Código incorrecto. Pedile el código de hoy al encargado.")
        return REPAIR_PHOTOS

    if normal == "listo" or normal.startswith("no tengo"):
        if _fotos(context, sufijo):
            return _continuar(update, context)
        return _trabar(update, context, ctx)

    if ctx.get("trabado"):
        return _trabar(update, context, ctx)
    update.message.reply_text(
        apply_bold_keywords("Mandá una foto o escribí <b>Listo</b>."),
        parse_mode=ParseMode.HTML,
    )
    return REPAIR_PHOTOS
