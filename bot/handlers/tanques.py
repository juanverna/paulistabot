import logging
from telegram import Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import *
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import push_state, back_handler, check_special_commands
from bot.handlers.fotos_reparaciones import necesita_fotos, pedir_fotos

logger = logging.getLogger(__name__)

# Los pasos de cada tanque (tipo, cuerpo, medida, tapas, sellado, reparaciones, sugerencias y
# "¿hay otro tanque?") están en campos_tanque.py. Acá quedan las fotos generales y la carga de
# reparaciones como texto.


# =============================================================================
# Reparaciones escritas (del tanque actual)
# =============================================================================
# En la carga manual las reparaciones se eligen con un menú (campos_tanque.boton_reparaciones).
# Esto las toma como texto, que es como las cargan los tests del paso de fotos.
def reparaciones_escritas(update: Update, context: CallbackContext) -> int:
    from bot.handlers.campos_tanque import preguntar_sugerencias
    from bot.services.tanques_reporte import clave
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    tanque_id = context.user_data["tanque_actual"]
    context.user_data[clave("repairs", tanque_id)] = text
    push_state(context, REPAIR)
    if not necesita_fotos(text):
        context.user_data.get("fotos_reparaciones", {}).pop(tanque_id, None)
        return preguntar_sugerencias(update, context)
    return pedir_fotos(update, context, tanque_id, "manual")


# =============================================================================
# Fotos (Limpieza / Presupuestos) — mínimo 3, ilimitadas hasta "Listo"
# Acepta fotos comprimidas y archivos.
# =============================================================================
def handle_tank_photos(update: Update, context: CallbackContext) -> int:
    from bot.handlers.final_summary import show_final_summary
    from bot.states import FINAL_SUMMARY

    if update.message.text:
        txt = update.message.text.lower().replace("á", "a").strip()
        if txt == "atras":
            return back_handler(update, context)
        if txt == "listo":
            photos = context.user_data.get("photos", [])
            if len(photos) < 3:
                # Mínimo 3 fotos — no lo decimos explícitamente
                update.message.reply_text(
                    apply_bold_keywords("Agregá más fotos antes de finalizar."),
                    parse_mode=ParseMode.HTML,
                )
                return PHOTOS
            # Ir al resumen final
            return show_final_summary(update, context)
        update.message.reply_text(
            apply_bold_keywords("Por favor, envíe una foto o escriba <b>Listo</b> para finalizar."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        photos = context.user_data.get("photos", [])
        photos.append(file_id)
        context.user_data["photos"] = photos
        update.message.reply_text(
            apply_bold_keywords(f"✅ Foto recibida (total: {len(photos)}). Enviá más o escribí <b>Listo</b>."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    if update.message.document:
        file_id = update.message.document.file_id
        photos = context.user_data.get("photos", [])
        photos.append(file_id)
        context.user_data["photos"] = photos
        update.message.reply_text(
            apply_bold_keywords(f"✅ Archivo recibido (total: {len(photos)}). Enviá más o escribí <b>Listo</b>."),
            parse_mode=ParseMode.HTML,
        )
        return PHOTOS

    update.message.reply_text(
        apply_bold_keywords("Por favor, envíe una foto o escriba <b>Listo</b> para finalizar."),
        parse_mode=ParseMode.HTML,
    )
    return PHOTOS
