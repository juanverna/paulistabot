"""
final_summary.py
----------------
Muestra un resumen completo del formulario antes de enviarlo.

"Modificar algo": el operario elige con botones qué campo cambiar y el bot le vuelve a hacer
esa misma pregunta, con los mismos controles (medida validada, menú de reparaciones y sus
fotos, hora con botones...). Al terminar ese campo vuelve al resumen (common.terminar_edicion).
Botones: "ed:menu", "ed:hora", "ed:h:<inicio|fin>", "ed:c" (contacto), "ed:t:<sufijo>",
"ed:f:<sufijo>:<campo>", "ed:cb:<tanque>" (cubas) y "ed:volver".
"""

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import FINAL_SUMMARY, PHOTOS, CAMPO_DEL_PASO
from bot.utils.helpers import apply_bold_keywords
from bot.services.email_service import send_email

logger = logging.getLogger(__name__)

def build_full_summary(user_data: dict) -> str:
    """Construye el resumen completo del formulario: datos generales y cada tanque cargado."""
    from bot.services import tanques_reporte as tq
    from bot.services.campos import legible, SIN_REPARACIONES
    from bot.services.email_service import _detalle_revision

    lines = ["📋 *RESUMEN COMPLETO DEL REPORTE*\n"]

    # Datos generales (sin datos del QR — son internos)
    lines.append("*Datos generales:*")
    if user_data.get("start_time"):
        lines.append(f"  • Hora inicio: {user_data['start_time']}")
    if user_data.get("end_time"):
        lines.append(f"  • Hora fin: {user_data['end_time']}")
    if user_data.get("cuerpos", 1) > 1:
        lines.append(f"  • Cuerpos del edificio: {user_data['cuerpos']}")
    if user_data.get("contact"):
        lines.append(f"  • Contacto: {user_data['contact']}")
    lines.append("")

    for tanque in tq.lista(user_data):
        tid = tanque["id"]
        nombre = tq.nombre(user_data, tid)
        section = [("Cubas", tanque["cubas"])] if tanque.get("cubas") else []
        for campo, etiqueta in tq.CAMPOS.items():
            valor = user_data.get(tq.clave(campo, tid))
            if not valor:
                continue
            if campo == "repairs" and valor != SIN_REPARACIONES:
                valor = "; ".join(legible(i) for i in valor.split(", "))
            section.append((etiqueta, valor))
        fotos_rep = user_data.get("fotos_reparaciones", {}).get(tid, [])
        if fotos_rep:
            section.append(("Fotos reparaciones", f"{len(fotos_rep)}{_detalle_revision(fotos_rep)}"))
        for d in user_data.get("destrabes", []):
            if d["tanque"] == nombre:
                section.append(("Destrabado por encargado", f"{d['motivo']} ({d['hora']})"))
        if section:
            lines.append(f"*{nombre}:*")
            for label, val in section:
                lines.append(f"  • {label}: {val}")
            lines.append("")

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


def _menu(user_data: dict, nivel: str):
    """(texto, botones) del menú de "Modificar algo". nivel: "menu", "hora" o el id de un tanque."""
    from bot.services import tanques_reporte as tq
    volver = [InlineKeyboardButton("← Volver", callback_data="ed:menu")]
    if nivel == "hora":
        return "¿Qué hora querés cambiar?", InlineKeyboardMarkup([
            [InlineKeyboardButton("Hora de inicio", callback_data="ed:h:inicio"),
             InlineKeyboardButton("Hora de fin", callback_data="ed:h:fin")], volver])
    if tq.buscar(user_data, nivel):
        botones = [InlineKeyboardButton("Cubas", callback_data=f"ed:cb:{nivel}")]
        botones += [InlineKeyboardButton(etiqueta, callback_data=f"ed:f:{nivel}:{campo}")
                    for campo, etiqueta in tq.CAMPOS.items()]
        filas = [botones[i:i + 2] for i in range(0, len(botones), 2)] + [volver]
        return f"¿Qué querés cambiar de {tq.nombre(user_data, nivel)}?", InlineKeyboardMarkup(filas)
    filas = [[InlineKeyboardButton("🕒 Horario", callback_data="ed:hora"),
              InlineKeyboardButton("👤 Contacto", callback_data="ed:c")]]
    filas += [[InlineKeyboardButton(f"🛢 {tq.nombre(user_data, t['id'])}", callback_data=f"ed:t:{t['id']}")]
              for t in tq.lista(user_data)]
    filas.append([InlineKeyboardButton("← Volver al resumen", callback_data="ed:volver")])
    return "✏️ ¿Qué querés modificar?", InlineKeyboardMarkup(filas)


def _editar_campo(update: Update, context: CallbackContext, data: str) -> int:
    """Vuelve a hacer la pregunta del campo elegido; al terminarlo se vuelve al resumen."""
    from bot.handlers import campos_tanque
    from bot.handlers.shared import pedir_hora
    from bot.services import tanques_reporte as tq
    ud = context.user_data
    partes = data.split(":")
    if partes[1] == "f" and (len(partes) != 4 or not tq.buscar(ud, partes[2]) or partes[3] not in tq.CAMPOS):
        return show_final_summary(update, context)  # botón de un tanque que ya no está
    ud["editando"] = len(ud.get("state_stack", []))  # "atrás" en el primer paso vuelve al resumen
    if partes[1] == "h":
        return pedir_hora(update, context, partes[2])
    if partes[1] == "c":
        return campos_tanque.preguntar_contacto(update, context)
    if partes[1] == "cb" and not tq.buscar(ud, partes[2]):
        ud.pop("editando", None)
        return show_final_summary(update, context)
    ud["tanque_actual"] = partes[2]
    if partes[1] == "cb":
        return campos_tanque.preguntar_cubas(update, context)
    estado = next(e for e, c in CAMPO_DEL_PASO.items() if c == partes[3])
    return campos_tanque.preguntar_paso(update, context, estado)


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
    elif data.startswith(("ed:h:", "ed:f:", "ed:cb:")) or data == "ed:c":
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
