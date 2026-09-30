import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import *
from bot.utils.helpers import apply_bold_keywords, is_valid_time
from bot.handlers.common import push_state, back_handler, check_special_commands
from bot.handlers import hora

logger = logging.getLogger(__name__)


def get_code(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    if not text.isdigit():
        update.message.reply_text(
            apply_bold_keywords("El código debe ser numérico. Intentá de nuevo:"),
            parse_mode=ParseMode.HTML,
        )
        return CODE
    context.user_data["code"] = text
    push_state(context, CODE)
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Fumigaciones",                     callback_data="Fumigaciones"),
         InlineKeyboardButton("Limpieza y Reparacion de Tanques", callback_data="Limpieza y Reparacion de Tanques")],
        [InlineKeyboardButton("Presupuestos", callback_data="Presupuestos"),
         InlineKeyboardButton("Avisos",        callback_data="Avisos")],
        [InlineKeyboardButton("ATRAS",         callback_data="back")],
    ])
    update.message.reply_text(
        apply_bold_keywords("¿Qué servicio se realizó?"),
        reply_markup=keyboard,
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = SERVICE
    return SERVICE


def service_selection(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)

    push_state(context, SERVICE)
    service = query.data
    context.user_data["service"] = service
    query.edit_message_text(
        apply_bold_keywords(f"Servicio seleccionado: {service}"),
        parse_mode=ParseMode.HTML,
    )
    chat_id = query.message.chat.id

    if service == "Fumigaciones":
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("📷 Por favor, envíe la foto del código QR:"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = SCAN_QR
        return SCAN_QR

    elif service == "Limpieza y Reparacion de Tanques":
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("📷 Por favor, envíe la foto del código QR de la orden:"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = SCAN_QR
        return SCAN_QR

    elif service == "Presupuestos":
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Ingrese la dirección:"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = ADDRESS
        return ADDRESS

    elif service == "Avisos":
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Indique dirección/es donde se entregaron avisos:"),
            parse_mode=ParseMode.HTML,
        )
        context.user_data["current_state"] = AVISOS_ADDRESS
        return AVISOS_ADDRESS


def get_order(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    if not text.isdigit() or len(text) != 7:
        update.message.reply_text(
            apply_bold_keywords("El número de orden debe ser numérico y tener 7 dígitos. Intentá de nuevo:"),
            parse_mode=ParseMode.HTML,
        )
        return ORDER
    context.user_data["order"] = text
    push_state(context, ORDER)
    update.message.reply_text(
        apply_bold_keywords("Ingrese la dirección:"),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = ADDRESS
    return ADDRESS


def get_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["address"] = text
    push_state(context, ADDRESS)
    # Presupuestos → pide hora (no tiene QR ni nota de voz); otros no deberían llegar acá
    return pedir_hora(update, context, "inicio")


# =============================================================================
# Horario: botones (formato 24 hs) o escrito a mano
# =============================================================================
def _responder(update: Update, context: CallbackContext, texto: str, markup=None) -> None:
    """Sirve tanto para mensajes como para botones (en un botón no hay update.message)."""
    context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=apply_bold_keywords(texto),
        reply_markup=markup,
        parse_mode=ParseMode.HTML,
    )


def pedir_hora(update: Update, context: CallbackContext, campo: str) -> int:
    """Pregunta la hora de inicio o de fin con el teclado de horas."""
    _responder(update, context, hora.texto_pregunta(campo), hora.teclado_horas(campo))
    estado = START_TIME if campo == "inicio" else END_TIME
    context.user_data["current_state"] = estado
    return estado


def _hora_escrita(update: Update, context: CallbackContext, estado: int):
    """Valida la hora escrita. Devuelve la hora, o el estado siguiente si no hay que seguir."""
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    if not is_valid_time(text):
        update.message.reply_text(
            apply_bold_keywords("Formato inválido. Tocá los botones o escribila así: 14:30 (24 hs)."),
            parse_mode=ParseMode.HTML,
        )
        return estado
    return text.strip()


def get_start_time(update: Update, context: CallbackContext) -> int:
    resultado = _hora_escrita(update, context, START_TIME)
    return guardar_hora_inicio(update, context, resultado) if isinstance(resultado, str) else resultado


def get_end_time(update: Update, context: CallbackContext) -> int:
    resultado = _hora_escrita(update, context, END_TIME)
    return guardar_hora_fin(update, context, resultado) if isinstance(resultado, str) else resultado


def guardar_hora_inicio(update: Update, context: CallbackContext, valor: str) -> int:
    context.user_data["start_time"] = valor
    push_state(context, START_TIME)
    return pedir_hora(update, context, "fin")


def guardar_hora_fin(update: Update, context: CallbackContext, valor: str) -> int:
    context.user_data["end_time"] = valor
    push_state(context, END_TIME)
    service = context.user_data.get("service")

    # Si viene del flujo manual post-QR → ir directo a medidas
    if context.user_data.pop("manual_after_qr", False):
        selected = context.user_data.get("selected_category", "").capitalize()
        _responder(update, context, f"Indique la medida del tanque de {selected} (ALTO, ANCHO, PROFUNDO):")
        context.user_data["current_state"] = MEASURE_MAIN
        return MEASURE_MAIN

    if service == "Fumigaciones":
        _responder(update, context, "¿Qué unidades contienen insectos?")
        context.user_data["current_state"] = FUMIGATION
        return FUMIGATION
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("CISTERNA",      callback_data="CISTERNA"),
         InlineKeyboardButton("RESERVA",       callback_data="RESERVA"),
         InlineKeyboardButton("INTERMEDIARIO", callback_data="INTERMEDIARIO")],
        [InlineKeyboardButton("ATRAS",         callback_data="back")],
    ])
    _responder(update, context, "Seleccione el tipo de tanque:", keyboard)
    context.user_data["current_state"] = TANK_TYPE
    return TANK_TYPE


def handle_hora_boton(update: Update, context: CallbackContext) -> int:
    """Botones del teclado de hora: primero la hora, después los minutos."""
    query = update.callback_query
    actual = context.user_data.get("current_state")
    boton = hora.leer_boton(query.data)
    esperado = {START_TIME: "inicio", END_TIME: "fin"}.get(actual)
    if boton is None or boton[0] != esperado:
        query.answer("Ese paso ya terminó.")
        return actual
    campo, accion, hh, mm = boton
    query.answer()
    if accion == "volver":
        query.edit_message_text(apply_bold_keywords(hora.texto_pregunta(campo)),
                                reply_markup=hora.teclado_horas(campo), parse_mode=ParseMode.HTML)
        return actual
    if accion == "h":
        query.edit_message_text(apply_bold_keywords(f"{hora.PREGUNTAS[campo]}\nAhora los minutos:"),
                                reply_markup=hora.teclado_minutos(campo, hh), parse_mode=ParseMode.HTML)
        return actual
    valor = f"{hh}:{mm}"
    query.edit_message_text(f"✅ {hora.ETIQUETAS[campo]}: {valor}")
    if campo == "inicio":
        return guardar_hora_inicio(update, context, valor)
    return guardar_hora_fin(update, context, valor)


def handle_atras_boton(update: Update, context: CallbackContext) -> int:
    """Botón ATRAS del teclado de hora."""
    update.callback_query.answer()
    return back_handler(update, context)


def get_contact(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["contact"] = text
    push_state(context, CONTACT)
    service = context.user_data.get("service")
    if service == "Fumigaciones":
        update.message.reply_text(
            apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, LISTADO y PORTERO ELECTRICO:"),
            parse_mode=ParseMode.HTML,
        )
    elif service == "Avisos":
        update.message.reply_text(
            apply_bold_keywords(
                "Adjunte las fotos de los avisos junto a la chapa del edificio.\n"
                "Cuando termine, escriba 'Listo'."
            ),
            parse_mode=ParseMode.HTML,
        )
    else:
        update.message.reply_text(
            apply_bold_keywords(
                "📎 Adjunte las fotos de <b>ORDEN DE TRABAJO, FICHA y TANQUES</b>.\n"
                "Cuando termine, escriba <b>Listo</b>."
            ),
            parse_mode=ParseMode.HTML,
        )
    context.user_data["current_state"] = PHOTOS
    return PHOTOS
