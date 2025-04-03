import logging
import os
import smtplib
import re
from io import BytesIO
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import (Updater, MessageHandler, Filters, CallbackQueryHandler,
                          ConversationHandler, CallbackContext)

# =============================================================================
# Función auxiliar para aplicar negritas a palabras clave
# =============================================================================
def apply_bold_keywords(text: str) -> str:
    pattern = r"(?i)\b(CISTERNA|RESERVA|INTERMEDIARIO)\b"
    return re.sub(pattern, lambda m: f"<b>{m.group(0)}</b>", text)

# =============================================================================
# Configuración del logging
# =============================================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# =============================================================================
# Variables de configuración
# =============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TU_TOKEN_AQUI")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "botpaulista25@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "fxvq jgue rkia gmtg")

# =============================================================================
# Definición de estados
# =============================================================================
(CODE, SERVICE, ORDER, ADDRESS, FUMIGATION, FUM_OBS, FUM_PHOTOS, CONTACT,
 TANK_TYPE, MEASURE_MAIN, TAPAS_INSPECCION_MAIN, TAPAS_ACCESO_MAIN, REPAIR_MAIN,
 SUGGESTIONS_MAIN, ASK_SECOND, MEASURE_ALT1, TAPAS_INSPECCION_ALT1, TAPAS_ACCESO_ALT1,
 REPAIR_ALT1, SUGGESTIONS_ALT1, ASK_THIRD, MEASURE_ALT2, TAPAS_INSPECCION_ALT2,
 TAPAS_ACCESO_ALT2, REPAIR_ALT2, SUGGESTIONS_ALT2, PHOTOS, AVISOS_CODE,
 AVISOS_ADDRESS, AVISOS_PHOTOS) = range(30)

# =============================================================================
# Mapeo de estados a claves en user_data para eliminar respuesta actual al "atras"
# =============================================================================
STATE_KEYS = {
    CODE: "code",
    ORDER: "order",
    ADDRESS: "address",
    FUMIGATION: "fumigated_units",
    FUM_OBS: "fum_obs",
    MEASURE_MAIN: "measure_main",
    TAPAS_INSPECCION_MAIN: "tapas_inspeccion_main",
    TAPAS_ACCESO_MAIN: "tapas_acceso_main",
    SUGGESTIONS_MAIN: "suggestions",
    REPAIR_MAIN: "repairs",
    MEASURE_ALT1: "measure_alt1",
    TAPAS_INSPECCION_ALT1: "tapas_inspeccion_alt1",
    TAPAS_ACCESO_ALT1: "tapas_acceso_alt1",
    SUGGESTIONS_ALT1: "suggestions_alt1",
    REPAIR_ALT1: "repair_alt1",
    MEASURE_ALT2: "measure_alt2",
    TAPAS_INSPECCION_ALT2: "tapas_inspeccion_alt2",
    TAPAS_ACCESO_ALT2: "tapas_acceso_alt2",
    SUGGESTIONS_ALT2: "suggestions_alt2",
    REPAIR_ALT2: "repair_alt2",
    CONTACT: "contact",
    AVISOS_ADDRESS: "avisos_address",
}

# =============================================================================
# Funciones para manejar el historial (stack) de estados
# =============================================================================
def push_state(context: CallbackContext, state: int):
    if "state_stack" not in context.user_data:
        context.user_data["state_stack"] = []
    context.user_data["state_stack"].append(state)
    logger.debug("push_state: Se guardó el estado %s. Stack actual: %s", state, context.user_data["state_stack"])

def pop_state(context: CallbackContext):
    if "state_stack" in context.user_data and context.user_data["state_stack"]:
        prev = context.user_data["state_stack"].pop()
        logger.debug("pop_state: Se extrajo el estado %s. Stack actual: %s", prev, context.user_data["state_stack"])
        return prev
    logger.debug("pop_state: Stack vacío")
    return None

# =============================================================================
# Función para revisar comandos especiales ("terminar")
# =============================================================================
def check_special_commands(text: str, update: Update, context: CallbackContext) -> bool:
    lower_text = text.lower().replace("á", "a")
    if "terminar" in lower_text:
        context.user_data.clear()
        update.message.reply_text("Formulario cancelado. Empezando de nuevo.")
        start_conversation(update, context)
        return True
    return False

# =============================================================================
# Funciones de inicio y retroceso usando el stack
# =============================================================================
def start_conversation(update: Update, context: CallbackContext) -> int:
    logger.debug("Inicio de conversación.")
    context.user_data.clear()
    context.user_data["state_stack"] = []
    update.message.reply_text(
        apply_bold_keywords("¡Hola! Inserte su código (solo números):"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = CODE
    return CODE

def back_handler(update: Update, context: CallbackContext) -> int:
    logger.debug("Se activó el comando ATRAS.")
    # Eliminar la respuesta del estado actual, si corresponde
    current_state = context.user_data.get("current_state")
    if current_state in STATE_KEYS:
        context.user_data.pop(STATE_KEYS[current_state], None)
    prev = pop_state(context)
    if prev is None:
        prev = CODE
    context.user_data["current_state"] = prev
    re_ask(prev, update, context)
    return prev

def re_ask(state: int, update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    # Reenvía el mensaje original para cada estado (con menú si es necesario)
    if state == CODE:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("¡Hola! Inserte su código (solo números):"),
            parse_mode=ParseMode.HTML)
    elif state == SERVICE:
        keyboard = [
            [
                InlineKeyboardButton("Fumigaciones", callback_data="Fumigaciones"),
                InlineKeyboardButton("Limpieza y Reparacion de Tanques", callback_data="Limpieza y Reparacion de Tanques")
            ],
            [
                InlineKeyboardButton("Presupuestos", callback_data="Presupuestos"),
                InlineKeyboardButton("Avisos", callback_data="Avisos")
            ],
            [InlineKeyboardButton("ATRAS", callback_data="back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("¿Qué servicio se realizó?"),
            reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    elif state == TANK_TYPE:
        keyboard = [
            [
                InlineKeyboardButton("CISTERNA", callback_data="CISTERNA"),
                InlineKeyboardButton("RESERVA", callback_data="RESERVA"),
                InlineKeyboardButton("INTERMEDIARIO", callback_data="INTERMEDIARIO")
            ],
            [InlineKeyboardButton("ATRAS", callback_data="back")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Seleccione el tipo de tanque:"),
            reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    # Agregar más casos según sea necesario para otros estados con menú

# =============================================================================
# Funciones del flujo de conversación
# =============================================================================
def get_code(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    if not text.isdigit():
        update.message.reply_text(
            apply_bold_keywords("El código debe ser numérico. Por favor, inténtalo de nuevo:"),
            parse_mode=ParseMode.HTML)
        return CODE
    context.user_data["code"] = text
    push_state(context, CODE)
    keyboard = [
        [
            InlineKeyboardButton("Fumigaciones", callback_data="Fumigaciones"),
            InlineKeyboardButton("Limpieza y Reparacion de Tanques", callback_data="Limpieza y Reparacion de Tanques")
        ],
        [
            InlineKeyboardButton("Presupuestos", callback_data="Presupuestos"),
            InlineKeyboardButton("Avisos", callback_data="Avisos")
        ],
        [InlineKeyboardButton("ATRAS", callback_data="back")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        apply_bold_keywords("¿Qué servicio se realizó?"),
        reply_markup=reply_markup, parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SERVICE
    return SERVICE

def service_selection(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    push_state(context, SERVICE)
    service_type = query.data
    context.user_data['service'] = service_type
    if service_type == "Fumigaciones":
        query.edit_message_text(
            apply_bold_keywords("Servicio seleccionado: Fumigaciones"),
            parse_mode=ParseMode.HTML)
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Por favor, ingrese el número de orden (7 dígitos):"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = ORDER
        return ORDER
    elif service_type == "Limpieza y Reparacion de Tanques":
        query.edit_message_text(
            apply_bold_keywords("Servicio seleccionado: Limpieza y Reparacion de Tanques"),
            parse_mode=ParseMode.HTML)
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Por favor indique su número de orden (7 dígitos):"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = ORDER
        return ORDER
    elif service_type == "Presupuestos":
        query.edit_message_text(
            apply_bold_keywords("Servicio seleccionado: Presupuestos"),
            parse_mode=ParseMode.HTML)
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Ingrese la dirección:"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = ADDRESS
        return ADDRESS
    elif service_type == "Avisos":
        query.edit_message_text(
            apply_bold_keywords("Servicio seleccionado: Avisos"),
            parse_mode=ParseMode.HTML)
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Indique dirección/es donde se entregaron avisos:"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = AVISOS_ADDRESS
        return AVISOS_ADDRESS

def get_order(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        context.user_data.pop("order", None)
        return back_handler(update, context)
    if not text.isdigit() or len(text) != 7:
        update.message.reply_text(
            apply_bold_keywords("El número de orden debe ser numérico y contener 7 dígitos. Por favor, inténtalo de nuevo:"),
            parse_mode=ParseMode.HTML)
        return ORDER
    context.user_data["order"] = text
    push_state(context, ORDER)
    update.message.reply_text(
        apply_bold_keywords("Ingrese la dirección:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = ADDRESS
    return ADDRESS

def get_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['address'] = text
    push_state(context, ADDRESS)
    service = context.user_data.get("service")
    if service == "Fumigaciones":
        update.message.reply_text(
            apply_bold_keywords("¿Qué unidades contienen insectos?"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = FUMIGATION
        return FUMIGATION
    elif service in ["Limpieza y Reparacion de Tanques", "Presupuestos"]:
        keyboard = [
            [
                InlineKeyboardButton("CISTERNA", callback_data='CISTERNA'),
                InlineKeyboardButton("RESERVA", callback_data='RESERVA'),
                InlineKeyboardButton("INTERMEDIARIO", callback_data='INTERMEDIARIO')
            ],
            [InlineKeyboardButton("ATRAS", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            apply_bold_keywords("Seleccione el tipo de tanque:"),
            reply_markup=reply_markup, parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = TANK_TYPE
        return TANK_TYPE

def fumigation_data(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['fumigated_units'] = text
    push_state(context, FUMIGATION)
    update.message.reply_text(
        apply_bold_keywords("Marque las observaciones para la próxima visita:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = FUM_OBS
    return FUM_OBS

def get_fum_obs(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['fum_obs'] = text
    push_state(context, FUM_OBS)
    update.message.reply_text(
        apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = FUM_PHOTOS
    return FUM_PHOTOS

def handle_tank_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    push_state(context, TANK_TYPE)
    selected = query.data
    context.user_data["selected_category"] = selected
    alternatives = [x for x in ["CISTERNA", "RESERVA", "INTERMEDIARIO"] if x != selected]
    context.user_data["alternative_1"] = alternatives[0]
    context.user_data["alternative_2"] = alternatives[1]
    query.edit_message_text(
        apply_bold_keywords(f"Tipo de tanque seleccionado: {selected.capitalize()}"),
        parse_mode=ParseMode.HTML)
    context.bot.send_message(
        chat_id=query.message.chat.id,
        text=apply_bold_keywords(f"Indique la medida del tanque de {selected.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = MEASURE_MAIN
    return MEASURE_MAIN

def get_measure_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['measure_main'] = text
    push_state(context, MEASURE_MAIN)
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS INSPECCIÓN (30 40 50 60 80):"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_INSPECCION_MAIN
    return TAPAS_INSPECCION_MAIN

def get_tapas_inspeccion_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_main'] = text
    push_state(context, TAPAS_INSPECCION_MAIN)
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_ACCESO_MAIN
    return TAPAS_ACCESO_MAIN

def get_tapas_acceso_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_main'] = text
    push_state(context, TAPAS_ACCESO_MAIN)
    selected = context.user_data.get("selected_category", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {selected}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SUGGESTIONS_MAIN
    return SUGGESTIONS_MAIN

def get_suggestions_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['suggestions'] = text
    push_state(context, SUGGESTIONS_MAIN)
    selected = context.user_data.get("selected_category", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {selected}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = REPAIR_MAIN
    return REPAIR_MAIN

def get_repair_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        context.user_data.pop("repairs", None)
        return back_handler(update, context)
    context.user_data['repairs'] = text
    push_state(context, REPAIR_MAIN)
    alt1 = context.user_data.get("alternative_1", "").capitalize()
    keyboard = [
        [
            InlineKeyboardButton("Si", callback_data='si'),
            InlineKeyboardButton("No", callback_data='no')
        ],
        [InlineKeyboardButton("ATRAS", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        apply_bold_keywords(f"¿Quiere comentar algo sobre {alt1}?"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = ASK_SECOND
    return ASK_SECOND

# Funciones para Alternativa 1
def get_tapas_inspeccion_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_alt1'] = text
    push_state(context, TAPAS_INSPECCION_ALT1)
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_ACCESO_ALT1
    return TAPAS_ACCESO_ALT1

def get_tapas_acceso_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_alt1'] = text
    push_state(context, TAPAS_ACCESO_ALT1)
    alt1 = context.user_data.get("alternative_1", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {alt1}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SUGGESTIONS_ALT1
    return SUGGESTIONS_ALT1

def get_suggestions_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['suggestions_alt1'] = text
    push_state(context, SUGGESTIONS_ALT1)
    alt1 = context.user_data.get("alternative_1", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {alt1}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = REPAIR_ALT1
    return REPAIR_ALT1

def get_repair_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        context.user_data.pop("repair_alt1", None)
        return back_handler(update, context)
    context.user_data['repair_alt1'] = text
    push_state(context, REPAIR_ALT1)
    alt2 = context.user_data.get("alternative_2", "").capitalize()
    keyboard = [
        [
            InlineKeyboardButton("Si", callback_data='si'),
            InlineKeyboardButton("No", callback_data='no')
        ],
        [InlineKeyboardButton("ATRAS", callback_data='back')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2}?"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = ASK_THIRD
    return ASK_THIRD

# Funciones para Alternativa 2
def get_tapas_inspeccion_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_alt2'] = text
    push_state(context, TAPAS_INSPECCION_ALT2)
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_ACCESO_ALT2
    return TAPAS_ACCESO_ALT2

def get_tapas_acceso_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_alt2'] = text
    push_state(context, TAPAS_ACCESO_ALT2)
    alt2 = context.user_data.get("alternative_2", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {alt2}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SUGGESTIONS_ALT2
    return SUGGESTIONS_ALT2

def get_suggestions_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['suggestions_alt2'] = text
    push_state(context, SUGGESTIONS_ALT2)
    alt2 = context.user_data.get("alternative_2", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {alt2}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = REPAIR_ALT2
    return REPAIR_ALT2

def get_repair_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        context.user_data.pop("repair_alt2", None)
        return back_handler(update, context)
    context.user_data['repair_alt2'] = text
    push_state(context, REPAIR_ALT2)
    if context.user_data.get("service") == "Presupuestos":
        update.message.reply_text(
            apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = CONTACT
        return CONTACT
    else:
        update.message.reply_text(
            apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:\nSi ha terminado, escriba 'Listo'."),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

# Funciones para el flujo de Avisos
def get_avisos_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["avisos_address"] = text
    push_state(context, AVISOS_ADDRESS)
    update.message.reply_text(
        apply_bold_keywords("Adjunte las fotos de los avisos junto a la chapa con numeración del edificio:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = AVISOS_PHOTOS
    return AVISOS_PHOTOS

def handle_avisos_photos(update: Update, context: CallbackContext) -> int:
    # Se permite usar "Listo" para terminar o "atras" para retroceder
    if update.message.text:
        txt = update.message.text.lower().replace("á", "a").strip()
        if txt == "atras":
            return back_handler(update, context)
        if txt == "listo":
            if "photos" not in context.user_data or len(context.user_data["photos"]) == 0:
                update.message.reply_text(
                    apply_bold_keywords("Debe cargar al menos una foto antes de escribir 'Listo'."),
                    parse_mode=ParseMode.HTML)
                return AVISOS_PHOTOS
            else:
                send_email(context.user_data, update, context)
                return ConversationHandler.END
    if update.message.photo:
        photos = context.user_data.get("photos", [])
        file_id = update.message.photo[-1].file_id
        photos.append(file_id)
        context.user_data["photos"] = photos
        update.message.reply_text(
            apply_bold_keywords("Foto recibida. Puede enviar más fotos o escriba 'Listo' para continuar."),
            parse_mode=ParseMode.HTML)
        return AVISOS_PHOTOS
    else:
        update.message.reply_text(
            apply_bold_keywords("Por favor, envíe una foto o escriba 'Listo' para continuar."),
            parse_mode=ParseMode.HTML)
        return AVISOS_PHOTOS

# Función para manejar la respuesta en el paso ASK_SECOND
def handle_ask_second(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        alt1 = context.user_data.get("alternative_1")
        query.edit_message_text(
            apply_bold_keywords(f"Indique la medida del tanque para {alt1.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = MEASURE_ALT1
        return MEASURE_ALT1
    elif query.data.lower() == "no":
        alt2 = context.user_data.get("alternative_2")
        keyboard = [
            [
                InlineKeyboardButton("Si", callback_data='si'),
                InlineKeyboardButton("No", callback_data='no')
            ],
            [InlineKeyboardButton("ATRAS", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
            apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2.capitalize()}?"),
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = ASK_THIRD
        return ASK_THIRD
    else:
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Respuesta no reconocida, se asume 'No'."),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

# Función para manejar la respuesta en el paso ASK_THIRD
def handle_ask_third(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        alt2 = context.user_data.get("alternative_2")
        query.edit_message_text(
            apply_bold_keywords(f"Indique la medida del tanque para {alt2.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = MEASURE_ALT2
        return MEASURE_ALT2
    elif query.data.lower() == "no":
        query.edit_message_text(
            apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = PHOTOS
        return PHOTOS
    else:
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Respuesta no reconocida, se asume 'No'."),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

# Funciones para obtener medidas en Alternativa 1 y 2
def get_measure_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        context.user_data.pop("measure_alt1", None)
        return back_handler(update, context)
    context.user_data['measure_alt1'] = text
    push_state(context, MEASURE_ALT1)
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_INSPECCION_ALT1
    return TAPAS_INSPECCION_ALT1

def get_measure_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        context.user_data.pop("measure_alt2", None)
        return back_handler(update, context)
    context.user_data['measure_alt2'] = text
    push_state(context, MEASURE_ALT2)
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_INSPECCION_ALT2
    return TAPAS_INSPECCION_ALT2

# Función para manejo de fotos (TANQUES y FUMIGACIONES)
def handle_photos(update: Update, context: CallbackContext) -> int:
    service = context.user_data.get('service')
    if service == "Fumigaciones":
        if not update.message.photo:
            update.message.reply_text(
                apply_bold_keywords("Por favor, adjunte una imagen válida."),
                parse_mode=ParseMode.HTML)
            return FUM_PHOTOS
        photos = context.user_data.get("photos", [])
        file_id = update.message.photo[-1].file_id
        photos.append(file_id)
        context.user_data["photos"] = photos
        if len(photos) < 2:
            update.message.reply_text(
                apply_bold_keywords("Por favor cargue la segunda foto."),
                parse_mode=ParseMode.HTML)
            return FUM_PHOTOS
        else:
            update.message.reply_text(
                apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
                parse_mode=ParseMode.HTML)
            context.user_data["current_state"] = CONTACT
            return CONTACT
    else:
        if update.message.text:
            txt = update.message.text.lower().replace("á", "a").strip()
            if txt == "atras":
                return back_handler(update, context)
            if txt == "listo":
                if "photos" not in context.user_data or len(context.user_data["photos"]) == 0:
                    update.message.reply_text(
                        apply_bold_keywords("Debe cargar al menos una foto antes de escribir 'Listo'."),
                        parse_mode=ParseMode.HTML)
                    return PHOTOS
                else:
                    update.message.reply_text(
                        apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
                        parse_mode=ParseMode.HTML)
                    context.user_data["current_state"] = CONTACT
                    return CONTACT
        elif update.message.photo:
            photos = context.user_data.get("photos", [])
            file_id = update.message.photo[-1].file_id
            photos.append(file_id)
            context.user_data["photos"] = photos
            update.message.reply_text(
                apply_bold_keywords("Foto recibida. Puede enviar más fotos o escriba 'Listo' para continuar."),
                parse_mode=ParseMode.HTML)
            return PHOTOS
        else:
            update.message.reply_text(
                apply_bold_keywords("Por favor, envíe una foto o escriba 'Listo' para continuar."),
                parse_mode=ParseMode.HTML)
            return PHOTOS

# Funciones para contacto y envío de email
def get_contact(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data["contact"] = text
    push_state(context, CONTACT)
    update.message.reply_text(
        apply_bold_keywords("Gracias por proporcionar el contacto."),
        parse_mode=ParseMode.HTML)
    send_email(context.user_data, update, context)
    return ConversationHandler.END

def send_email(user_data, update: Update, context: CallbackContext):
    service = user_data.get("service", "")
    subject = "Reporte de Servicio: " + service
    lines = []
    # Agregar la fecha actual (campo interno)
    fecha = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines.append(f"Fecha: {fecha}")
    if "code" in user_data:
        lines.append(f"Código: {user_data['code']}")
    if service == "Avisos":
        if "avisos_address" in user_data:
            lines.append(f"Dirección/es: {user_data['avisos_address']}")
    else:
        ordered_fields = []
        if service in ["Fumigaciones", "Limpieza y Reparacion de Tanques"]:
            ordered_fields.append(("order", "Número de Orden"))
        ordered_fields.extend([
            ("address", "Dirección"),
            ("service", "Servicio seleccionado")
        ])
        if service in ["Limpieza y Reparacion de Tanques", "Presupuestos"]:
            selected = user_data.get("selected_category", "")
            alt1 = user_data.get("alternative_1", "")
            alt2 = user_data.get("alternative_2", "")
            ordered_fields.extend([
                ("selected_category", "Tipo de tanque"),
                ("measure_main", "Medida principal"),
                ("tapas_inspeccion_main", "Tapas inspección"),
                ("tapas_acceso_main", "Tapas acceso"),
                ("suggestions", f"Sugerencias {selected}"),
                ("repairs", f"Reparaciones {selected}"),
                ("measure_alt1", "Medida " + alt1),
                ("tapas_inspeccion_alt1", "Tapas inspección " + alt1),
                ("tapas_acceso_alt1", "Tapas acceso " + alt1),
                ("suggestions_alt1", f"Sugerencias {alt1}"),
                ("repair_alt1", f"Reparaciones {alt1}"),
                ("measure_alt2", "Medida " + alt2),
                ("tapas_inspeccion_alt2", "Tapas inspección " + alt2),
                ("tapas_acceso_alt2", "Tapas acceso " + alt2),
                ("suggestions_alt2", f"Sugerencias {alt2}"),
                ("repair_alt2", f"Reparaciones {alt2}")
            ])
        if service == "Fumigaciones":
            ordered_fields.extend([
                ("fumigated_units", "Unidades con insectos"),
                ("fum_obs", "Observaciones")
            ])
        ordered_fields.append(("contact", "Contacto"))
        for key, label in ordered_fields:
            if key in user_data:
                lines.append(f"{label}: {user_data[key]}")
    body = "Detalles del reporte:\n" + "\n".join(lines)

    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = EMAIL_ADDRESS
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    photos = user_data.get("photos", [])
    for idx, file_id in enumerate(photos):
        try:
            file = context.bot.get_file(file_id)
            bio = BytesIO()
            file.download(out=bio)
            bio.seek(0)
            image = MIMEImage(bio.read(), _subtype="jpeg")
            image.add_header('Content-Disposition', 'attachment', filename=f"foto_{idx+1}.jpg")
            msg.attach(image)
        except Exception as e:
            logger.error("Error al descargar/adjuntar imagen: %s", e)

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        logger.info("Correo enviado exitosamente.")
        if update.message:
            update.message.reply_text(
                apply_bold_keywords("Correo enviado exitosamente."),
                parse_mode=ParseMode.HTML)
        else:
            context.bot.send_message(chat_id=update.effective_chat.id,
                text=apply_bold_keywords("Correo enviado exitosamente."),
                parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Error al enviar email: %s", e)
        if update.message:
            update.message.reply_text(
                apply_bold_keywords("Error al enviar correo."),
                parse_mode=ParseMode.HTML)
        else:
            context.bot.send_message(chat_id=update.effective_chat.id,
                text=apply_bold_keywords("Error al enviar correo."),
                parse_mode=ParseMode.HTML)

def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex("(?i)^hola$"), start_conversation)],
        states={
            CODE: [
                MessageHandler(Filters.text & ~Filters.command, get_code)
            ],
            SERVICE: [
                CallbackQueryHandler(service_selection),
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler)
            ],
            ORDER: [
                MessageHandler(Filters.text & ~Filters.command, get_order),
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler)
            ],
            ADDRESS: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_address)
            ],
            FUMIGATION: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, fumigation_data)
            ],
            FUM_OBS: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_fum_obs)
            ],
            FUM_PHOTOS: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.photo, handle_photos),
                MessageHandler(Filters.text & ~Filters.command, handle_photos)
            ],
            TANK_TYPE: [
                CallbackQueryHandler(handle_tank_type),
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler)
            ],
            MEASURE_MAIN: [
                MessageHandler(Filters.text & ~Filters.command, get_measure_main)
            ],
            TAPAS_INSPECCION_MAIN: [
                MessageHandler(Filters.text & ~Filters.command, get_tapas_inspeccion_main)
            ],
            TAPAS_ACCESO_MAIN: [
                MessageHandler(Filters.text & ~Filters.command, get_tapas_acceso_main)
            ],
            SUGGESTIONS_MAIN: [
                MessageHandler(Filters.text & ~Filters.command, get_suggestions_main)
            ],
            REPAIR_MAIN: [
                MessageHandler(Filters.text & ~Filters.command, get_repair_main)
            ],
            ASK_SECOND: [
                CallbackQueryHandler(handle_ask_second),
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler)
            ],
            MEASURE_ALT1: [
                MessageHandler(Filters.text & ~Filters.command, get_measure_alt1)
            ],
            TAPAS_INSPECCION_ALT1: [
                MessageHandler(Filters.text & ~Filters.command, get_tapas_inspeccion_alt1)
            ],
            TAPAS_ACCESO_ALT1: [
                MessageHandler(Filters.text & ~Filters.command, get_tapas_acceso_alt1)
            ],
            SUGGESTIONS_ALT1: [
                MessageHandler(Filters.text & ~Filters.command, get_suggestions_alt1)
            ],
            REPAIR_ALT1: [
                MessageHandler(Filters.text & ~Filters.command, get_repair_alt1)
            ],
            ASK_THIRD: [
                CallbackQueryHandler(handle_ask_third),
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler)
            ],
            MEASURE_ALT2: [
                MessageHandler(Filters.text & ~Filters.command, get_measure_alt2)
            ],
            TAPAS_INSPECCION_ALT2: [
                MessageHandler(Filters.text & ~Filters.command, get_tapas_inspeccion_alt2)
            ],
            TAPAS_ACCESO_ALT2: [
                MessageHandler(Filters.text & ~Filters.command, get_tapas_acceso_alt2)
            ],
            SUGGESTIONS_ALT2: [
                MessageHandler(Filters.text & ~Filters.command, get_suggestions_alt2)
            ],
            REPAIR_ALT2: [
                MessageHandler(Filters.text & ~Filters.command, get_repair_alt2)
            ],
            PHOTOS: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.photo, handle_photos),
                MessageHandler(Filters.text & ~Filters.command, handle_photos)
            ],
            CONTACT: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_contact)
            ],
            AVISOS_ADDRESS: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_avisos_address)
            ],
            AVISOS_PHOTOS: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.photo, handle_avisos_photos),
                MessageHandler(Filters.text & ~Filters.command, handle_avisos_photos)
            ]
        },
        fallbacks=[]
    )
    dp.add_handler(conv_handler)
    logger.debug("Iniciando polling...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
