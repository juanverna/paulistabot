"""
final_summary.py
----------------
Muestra un resumen completo del formulario antes de enviarlo.

"Modificar algo": el operario elige con botones qué campo cambiar y el bot le vuelve a hacer
esa misma pregunta, con los mismos controles (medida validada, menú de reparaciones y sus
fotos, hora con botones...). Al terminar ese campo vuelve al resumen (common.terminar_edicion).
Botones: "ed:menu", "ed:hora", "ed:h:<inicio|fin>", "ed:c" (contacto), "ed:t:<sufijo>",
"ed:f:<sufijo>:<campo>" y "ed:volver".
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import FINAL_SUMMARY, PHOTOS, SUGGESTIONS_MAIN, SUGGESTIONS_ALT1, SUGGESTIONS_ALT2
from bot.utils.helpers import apply_bold_keywords
from bot.services.email_service import send_email

logger = logging.getLogger(__name__)

def build_full_summary(user_data: dict) -> str:
    """Construye el resumen completo del formulario."""
    selected = user_data.get("selected_category", "").capitalize()
    alt1     = user_data.get("alternative_1", "").capitalize()
    alt2     = user_data.get("alternative_2", "").capitalize()

    lines = ["📋 *RESUMEN COMPLETO DEL REPORTE*\n"]

    # Datos generales (sin datos del QR — son internos)
    lines.append("*Datos generales:*")
    if user_data.get("start_time"):
        lines.append(f"  • Hora inicio: {user_data['start_time']}")
    if user_data.get("end_time"):
        lines.append(f"  • Hora fin: {user_data['end_time']}")
    if user_data.get("contact"):
        lines.append(f"  • Contacto: {user_data['contact']}")
    lines.append("")

    # Tanque principal
    def add_tank(name: str, suffix: str):
        fields = {
            f"measure_{suffix}":          "Medida",
            f"tapas_inspeccion_{suffix}":  "Tapas inspección",
            f"tapas_acceso_{suffix}":      "Tapas acceso",
            f"sealing_{suffix}":           "Sellado",
        }
        # Para main los keys son distintos
        if suffix == "main":
            fields = {
                "measure_main":          "Medida",
                "tapas_inspeccion_main": "Tapas inspección",
                "tapas_acceso_main":     "Tapas acceso",
                "sealing_main":          "Sellado",
                "repairs":               "Reparaciones",
                "suggestions":           "Sugerencias",
            }
        elif suffix == "alt1":
            fields = {
                "measure_alt1":          "Medida",
                "tapas_inspeccion_alt1": "Tapas inspección",
                "tapas_acceso_alt1":     "Tapas acceso",
                "sealing_alt1":          "Sellado",
                "repair_alt1":           "Reparaciones",
                "suggestions_alt1":      "Sugerencias",
            }
        elif suffix == "alt2":
            fields = {
                "measure_alt2":          "Medida",
                "tapas_inspeccion_alt2": "Tapas inspección",
                "tapas_acceso_alt2":     "Tapas acceso",
                "sealing_alt2":          "Sellado",
                "repair_alt2":           "Reparaciones",
                "suggestions_alt2":      "Sugerencias",
            }

        section = [(label, user_data[key]) for key, label in fields.items()
                   if user_data.get(key)]
        fotos_rep = user_data.get("fotos_reparaciones", {}).get(suffix, [])
        if fotos_rep:
            from bot.services.email_service import _detalle_revision
            section.append(("Fotos reparaciones", f"{len(fotos_rep)}{_detalle_revision(fotos_rep)}"))
        for d in user_data.get("destrabes", []):
            if d["tanque"] == name:
                section.append(("Destrabado por encargado", f"{d['motivo']} ({d['hora']})"))
        if section:
            lines.append(f"*{name}:*")
            for label, val in section:
                lines.append(f"  • {label}: {val}")
            lines.append("")

    add_tank(selected, "main")

    if any(user_data.get(k) for k in ["measure_alt1", "tapas_inspeccion_alt1",
                                        "tapas_acceso_alt1", "sealing_alt1"]):
        add_tank(alt1, "alt1")

    if any(user_data.get(k) for k in ["measure_alt2", "tapas_inspeccion_alt2",
                                        "tapas_acceso_alt2", "sealing_alt2"]):
        add_tank(alt2, "alt2")

    total_fotos = len(user_data.get("photos", []))
    lines.append(f"*Fotos generales:* {total_fotos}")

    return "\n".join(lines)


def show_final_summary(update: Update, context: CallbackContext) -> int:
    """Muestra el resumen final con botones Enviar / Modificar."""
    summary = build_full_summary(context.user_data)

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Enviar reporte", callback_data="final_send"),
        InlineKeyboardButton("✏️ Modificar algo", callback_data="final_edit"),
    ]])

    chat_id = update.effective_chat.id
    context.bot.send_message(
        chat_id=chat_id,
        text=summary,
        reply_markup=keyboard,
        parse_mode=ParseMode.MARKDOWN,
    )
    context.user_data["current_state"] = FINAL_SUMMARY
    return FINAL_SUMMARY


# Campos de cada tanque que se pueden modificar, en el orden en que se preguntan
CAMPOS_TANQUE = (("medida", "Medida"), ("insp", "Tapas inspección"), ("acceso", "Tapas acceso"),
                 ("sellado", "Sellado"), ("reparaciones", "Reparaciones"), ("sugerencias", "Sugerencias"))
SUGERENCIAS = {"main": (SUGGESTIONS_MAIN, "suggestions"), "alt1": (SUGGESTIONS_ALT1, "suggestions_alt1"),
               "alt2": (SUGGESTIONS_ALT2, "suggestions_alt2")}


def _tanques_cargados(user_data: dict) -> list:
    """Sufijos de los tanques del reporte: el principal y los alternativos que tienen datos."""
    from bot.handlers.campos_tanque import PASOS
    sufijos = []
    for sufijo, paso in PASOS.items():
        claves = [paso[c][1] for c in ("medida", "insp", "acceso", "sellado", "reparaciones")]
        if sufijo == "main" or any(user_data.get(k) for k in claves + [SUGERENCIAS[sufijo][1]]):
            sufijos.append(sufijo)
    return sufijos


def _menu(user_data: dict, nivel: str):
    """(texto, botones) del menú de "Modificar algo"."""
    from bot.handlers.campos_tanque import PASOS
    volver = [InlineKeyboardButton("← Volver", callback_data="ed:menu")]
    if nivel == "hora":
        return "¿Qué hora querés cambiar?", InlineKeyboardMarkup([
            [InlineKeyboardButton("Hora de inicio", callback_data="ed:h:inicio"),
             InlineKeyboardButton("Hora de fin", callback_data="ed:h:fin")], volver])
    if nivel in PASOS:
        tanque = user_data.get(PASOS[nivel]["tanque"], "").capitalize()
        botones = [InlineKeyboardButton(nombre, callback_data=f"ed:f:{nivel}:{campo}")
                   for campo, nombre in CAMPOS_TANQUE]
        filas = [botones[i:i + 2] for i in range(0, len(botones), 2)] + [volver]
        return f"¿Qué querés cambiar de {tanque}?", InlineKeyboardMarkup(filas)
    filas = [[InlineKeyboardButton("🕒 Horario", callback_data="ed:hora"),
              InlineKeyboardButton("👤 Contacto", callback_data="ed:c")]]
    filas += [[InlineKeyboardButton(f"🛢 {user_data.get(PASOS[s]['tanque'], '').capitalize()}",
                                    callback_data=f"ed:t:{s}")] for s in _tanques_cargados(user_data)]
    filas.append([InlineKeyboardButton("← Volver al resumen", callback_data="ed:volver")])
    return "✏️ ¿Qué querés modificar?", InlineKeyboardMarkup(filas)


def _editar_campo(update: Update, context: CallbackContext, data: str) -> int:
    """Vuelve a hacer la pregunta del campo elegido; al terminarlo se vuelve al resumen."""
    from bot.handlers import campos_tanque
    from bot.handlers.shared import pedir_hora
    ud = context.user_data
    ud["editando"] = len(ud.get("state_stack", []))  # "atrás" en el primer paso vuelve al resumen
    partes = data.split(":")
    if partes[1] == "h":
        return pedir_hora(update, context, partes[2])
    if partes[1] == "c":
        return campos_tanque.preguntar_contacto(update, context)
    sufijo, campo = partes[2], partes[3]
    if campo == "medida":
        return campos_tanque.preguntar_medida(update, context, sufijo)
    if campo == "reparaciones":
        return campos_tanque.preguntar_reparaciones(update, context, sufijo)
    if campo == "sugerencias":
        estado, _ = SUGERENCIAS[sufijo]
        tanque = ud.get(campos_tanque.PASOS[sufijo]["tanque"], "").capitalize()
        campos_tanque._enviar(update, context, f"Indique sugerencias p/ la próx limpieza para {tanque}:",
                              campos_tanque.teclado_atras())
        ud["current_state"] = estado
        return estado
    return campos_tanque.preguntar_texto(update, context, sufijo, campo)


def handle_final_summary_callback(update: Update, context: CallbackContext) -> int:
    """Maneja los botones del resumen final y del menú de "Modificar algo"."""
    query = update.callback_query
    query.answer()
    data = query.data

    if data == "final_send":
        query.edit_message_text("✅ Enviando reporte...", parse_mode=ParseMode.HTML)
        from bot.services import dataset_fotos
        dataset_fotos.registrar(context.user_data)  # fotos + análisis, para entrenar la IA más adelante
        send_email(context.user_data, update, context)
        return ConversationHandler.END

    if data in ("final_edit", "ed:menu"):
        nivel = "menu"
    elif data == "ed:hora":
        nivel = "hora"
    elif data.startswith("ed:t:"):
        nivel = data.split(":")[2]
    elif data == "ed:volver":
        query.edit_message_reply_markup(reply_markup=None)
        return show_final_summary(update, context)
    elif data.startswith(("ed:h:", "ed:f:")) or data == "ed:c":
        query.edit_message_reply_markup(reply_markup=None)
        return _editar_campo(update, context, data)
    else:
        return FINAL_SUMMARY

    texto, botones = _menu(context.user_data, nivel)
    if data == "final_edit":  # el resumen queda a la vista; el menú va en un mensaje nuevo
        query.edit_message_reply_markup(reply_markup=None)
        context.bot.send_message(chat_id=update.effective_chat.id, text=texto, reply_markup=botones)
    else:
        query.edit_message_text(texto, reply_markup=botones)
    return FINAL_SUMMARY


def handle_final_text(update: Update, context: CallbackContext) -> int:
    """Texto en el resumen final: los cambios se hacen con los botones."""
    update.message.reply_text("👆 Usá los botones del resumen: «Enviar reporte» o «Modificar algo».")
    return FINAL_SUMMARY
