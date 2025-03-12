import logging
import os
import smtplib
import re
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import (Updater, MessageHandler, Filters, CallbackQueryHandler,
                          ConversationHandler, CallbackContext)

# =============================================================================
# FUNCION AUXILIAR PARA NEGRITA
# =============================================================================
def apply_bold_keywords(text: str) -> str:
    """
    Envuelve en <b></b> las palabras 'CISTERNA', 'RESERVA' e 'INTERMEDIARIO' (case-insensitive).
    """
    pattern = r"(?i)\b(CISTERNA|RESERVA|INTERMEDIARIO)\b"
    return re.sub(pattern, lambda m: f"<b>{m.group(0)}</b>", text)

# =============================================================================
# CONFIGURACIÓN DEL LOGGING
# =============================================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # Puedes cambiar a INFO para menos detalle
)
logger = logging.getLogger(__name__)

# =============================================================================
# VARIABLES DE CONFIGURACIÓN
# =============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7650702859:AAHZfGk5ff5bfPbV3VzMK-XPKOkerjliM8M")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "botpaulista25@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "fxvq jgue rkia gmtg")

# =============================================================================
# DEFINICIÓN DE ESTADOS
# =============================================================================
(CODE, ORDER, ADDRESS, SERVICE, FUMIGATION, TANK_TYPE, 
 REPAIR_FIRST, ASK_SECOND, ASK_THIRD, PHOTOS, CONTACT, AVISOS_MENU, AVISOS_TEXT,
 FUM_OBS, FUM_PHOTOS, FUM_AVISOS, FUM_AVISOS_MENU, FUM_AVISOS_TEXT,
 MEASURE_MAIN, TAPAS_INSPECCION_MAIN, TAPAS_ACCESO_MAIN,
 MEASURE_ALT1, TAPAS_INSPECCION_ALT1, TAPAS_ACCESO_ALT1, REPAIR_ALT1,
 MEASURE_ALT2, TAPAS_INSPECCION_ALT2, TAPAS_ACCESO_ALT2, REPAIR_ALT2,
 TASK_SCHEDULE) = range(30)

# =============================================================================
# DICTIONARIO DE RETROCESO ("ATRÁS")
# =============================================================================
BACK_MAP = {
    # Comunes
    ORDER: CODE,
    ADDRESS: ORDER,
    SERVICE: ADDRESS,
    # Fumigación
    FUMIGATION: SERVICE,
    FUM_OBS: FUMIGATION,
    FUM_PHOTOS: FUM_OBS,
    FUM_AVISOS: FUM_PHOTOS,
    FUM_AVISOS_MENU: FUM_AVISOS,
    FUM_AVISOS_TEXT: FUM_AVISOS_MENU,
    # Limpieza/Reparación – principal
    TANK_TYPE: SERVICE,
    MEASURE_MAIN: TANK_TYPE,
    TAPAS_INSPECCION_MAIN: MEASURE_MAIN,
    TAPAS_ACCESO_MAIN: TAPAS_INSPECCION_MAIN,
    REPAIR_FIRST: TAPAS_ACCESO_MAIN,
    # Limpieza/Reparación – alternativas
    ASK_SECOND: REPAIR_FIRST,
    MEASURE_ALT1: ASK_SECOND,
    TAPAS_INSPECCION_ALT1: MEASURE_ALT1,
    TAPAS_ACCESO_ALT1: TAPAS_INSPECCION_ALT1,
    REPAIR_ALT1: TAPAS_ACCESO_ALT1,
    ASK_THIRD: REPAIR_FIRST,
    MEASURE_ALT2: ASK_THIRD,
    TAPAS_INSPECCION_ALT2: MEASURE_ALT2,
    TAPAS_ACCESO_ALT2: TAPAS_INSPECCION_ALT2,
    REPAIR_ALT2: TAPAS_ACCESO_ALT2,
    # Resto
    PHOTOS: REPAIR_FIRST,
    CONTACT: PHOTOS,
    TASK_SCHEDULE: CONTACT,
    AVISOS_MENU: TASK_SCHEDULE,
    AVISOS_TEXT: AVISOS_MENU
}

# =============================================================================
# FUNCIONES DE RETROCESO (back_handler Y re_ask)
# =============================================================================
def back_handler(update: Update, context: CallbackContext) -> int:
    logger.debug("back_handler: Estado actual: %s", context.user_data.get("current_state"))
    if update.callback_query:
        update.callback_query.answer()
    current_state = context.user_data.get("current_state", CODE)
    previous_state = BACK_MAP.get(current_state)
    if previous_state is None:
        re_ask(current_state, update, context)
        return current_state
    else:
        context.user_data["current_state"] = previous_state
        logger.debug("Retrocediendo a estado: %s", previous_state)
        re_ask(previous_state, update, context)
        return previous_state

def re_ask(state: int, update: Update, context: CallbackContext):
    chat_id = update.effective_chat.id
    logger.debug("re_ask: Estado %s", state)
    if state == CODE:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("¡Hola! Inserte su código (solo números):"), 
            parse_mode=ParseMode.HTML
        )
    elif state == ORDER:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Escriba el número de la orden de trabajo (7 dígitos):"), 
            parse_mode=ParseMode.HTML
        )
    elif state == ADDRESS:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Escriba la dirección:"), 
            parse_mode=ParseMode.HTML
        )
    elif state == SERVICE:
        keyboard = [
            [InlineKeyboardButton("Fumigación", callback_data='Fumigacion')],
            [InlineKeyboardButton("Limpieza y reparación de tanques", callback_data='limpieza')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("¿Qué servicio se realizó?"), 
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif state == FUMIGATION:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("¿Qué unidades contienen insectos?"), 
            parse_mode=ParseMode.HTML
        )
    elif state == FUM_OBS:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Marque las observaciones para la próxima visita:"), 
            parse_mode=ParseMode.HTML
        )
    elif state == FUM_PHOTOS:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO:"), 
            parse_mode=ParseMode.HTML
        )
    elif state == FUM_AVISOS:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Entregaste avisos para el próximo mes en la dirección en la que hiciste el trabajo?"), 
            parse_mode=ParseMode.HTML
        )
    elif state == FUM_AVISOS_MENU:
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Entregaste avisos en otras direcciones?"), 
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif state == FUM_AVISOS_TEXT:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("¿En qué direcciones? (Separe las direcciones con una coma)"), 
            parse_mode=ParseMode.HTML
        )
    elif state == TANK_TYPE:
        keyboard = [
            [InlineKeyboardButton("CISTERNA", callback_data='CISTERNA')],
            [InlineKeyboardButton("RESERVA", callback_data='RESERVA')],
            [InlineKeyboardButton("INTERMEDIARIO", callback_data='INTERMEDIARIO')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Seleccione el tipo de tanque:"), 
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif state == MEASURE_MAIN:
        selected = context.user_data.get("selected_category", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords(f"Indique la medida del tanque de {selected} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
            parse_mode=ParseMode.HTML
        )
    elif state == TAPAS_INSPECCION_MAIN:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Indique TAPAS INSPECCIÓN (30 40 50 60 80):"), 
            parse_mode=ParseMode.HTML
        )
    elif state == TAPAS_ACCESO_MAIN:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"), 
            parse_mode=ParseMode.HTML
        )
    elif state == REPAIR_FIRST:
        selected = context.user_data.get("selected_category", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords(f"Indique las observaciones y reparación de {selected}:"),
            parse_mode=ParseMode.HTML
        )
    elif state == ASK_SECOND:
        alt1 = context.user_data.get("alternative_1")
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords(f"¿Quiere comentar algo sobre {alt1.capitalize()}?"),
            parse_mode=ParseMode.HTML
        )
    elif state == MEASURE_ALT1:
        alt1 = context.user_data.get("alternative_1")
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords(f"Indique la medida del tanque para {alt1.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
            parse_mode=ParseMode.HTML
        )
    elif state == TAPAS_INSPECCION_ALT1:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
            parse_mode=ParseMode.HTML
        )
    elif state == TAPAS_ACCESO_ALT1:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Indique TAPAS ACCESO para esta opción (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
            parse_mode=ParseMode.HTML
        )
    elif state == REPAIR_ALT1:
        alt1 = context.user_data.get("alternative_1")
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords(f"Indique las observaciones y reparación de {alt1.capitalize()}:"),
            parse_mode=ParseMode.HTML
        )
    elif state == ASK_THIRD:
        alt2 = context.user_data.get("alternative_2")
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2.capitalize()}?"),
            parse_mode=ParseMode.HTML
        )
    elif state == MEASURE_ALT2:
        alt2 = context.user_data.get("alternative_2")
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords(f"Indique la medida del tanque para {alt2.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
            parse_mode=ParseMode.HTML
        )
    elif state == TAPAS_INSPECCION_ALT2:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
            parse_mode=ParseMode.HTML
        )
    elif state == TAPAS_ACCESO_ALT2:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Indique TAPAS ACCESO para esta opción(4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
            parse_mode=ParseMode.HTML
        )
    elif state == REPAIR_ALT2:
        alt2 = context.user_data.get("alternative_2")
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords(f"Indique las observaciones y reparación de {alt2.capitalize()}:"),
            parse_mode=ParseMode.HTML
        )
    elif state == PHOTOS:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES.\nSi ha terminado, escriba 'Listo'."), 
            parse_mode=ParseMode.HTML
        )
    elif state == CONTACT:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"), 
            parse_mode=ParseMode.HTML
        )
    elif state == TASK_SCHEDULE:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Indique el Horario de INICIO y FIN de tareas:"), 
            parse_mode=ParseMode.HTML
        )
    elif state == AVISOS_MENU:
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Entregaste avisos en otras direcciones?"), 
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif state == AVISOS_TEXT:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Indique qué direcciones (separadas por una coma):"), 
            parse_mode=ParseMode.HTML
        )
    else:
        context.bot.send_message(
            chat_id=chat_id, 
            text=apply_bold_keywords("Error: Estado desconocido."), 
            parse_mode=ParseMode.HTML
        )

# =============================================================================
# FUNCIONES PARA VALIDAR CAMPOS NUMÉRICOS (get_code y get_order)
# =============================================================================
def get_code(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if not text.isdigit():
        update.message.reply_text(
            apply_bold_keywords("El código debe ser numérico. Por favor, inténtalo de nuevo:"),
            parse_mode=ParseMode.HTML
        )
        return CODE
    context.user_data["code"] = text
    update.message.reply_text(
        apply_bold_keywords("Por favor, ingrese el número de orden (7 dígitos):"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = ORDER
    return ORDER

def get_order(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if not text.isdigit() or len(text) != 7:
        update.message.reply_text(
            apply_bold_keywords("El número de orden debe ser numérico y contener 7 dígitos. Por favor, inténtalo de nuevo:"),
            parse_mode=ParseMode.HTML
        )
        return ORDER
    context.user_data["order"] = text
    update.message.reply_text(
        apply_bold_keywords("Ingrese la dirección:"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = ADDRESS
    return ADDRESS

# =============================================================================
# FUNCIONES DEL FLUJO DE CONVERSACIÓN
# =============================================================================
def start_conversation(update: Update, context: CallbackContext) -> int:
    logger.debug("Inicio de conversación.")
    context.user_data.clear()
    update.message.reply_text(
        apply_bold_keywords("¡Hola! Inserte su código (solo números):"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = CODE
    return CODE

def get_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['address'] = text
    keyboard = [
        [InlineKeyboardButton("Fumigación", callback_data='Fumigacion')],
        [InlineKeyboardButton("Limpieza y reparación de tanques", callback_data='limpieza')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        apply_bold_keywords("¿Qué servicio se realizó?"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = SERVICE
    return SERVICE

def service_selection(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data == "back":
        return back_handler(update, context)
    service_type = query.data
    context.user_data['service'] = service_type
    if service_type == "Fumigacion":
        query.edit_message_text(
            apply_bold_keywords("Servicio seleccionado: Fumigación\n¿Qué unidades contienen insectos?"),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = FUMIGATION
        return FUMIGATION
    else:
        query.edit_message_text(
            apply_bold_keywords("Servicio seleccionado: Limpieza y reparación de tanques"),
            parse_mode=ParseMode.HTML
        )
        keyboard = [
            [InlineKeyboardButton("CISTERNA", callback_data='CISTERNA')],
            [InlineKeyboardButton("RESERVA", callback_data='RESERVA')],
            [InlineKeyboardButton("INTERMEDIARIO", callback_data='INTERMEDIARIO')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Seleccione el tipo de tanque:"),
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = TANK_TYPE
        return TANK_TYPE

# =============================================================================
# FUNCIONES PARA FUMIGACIÓN (se mantienen sin cambios, con formato aplicado)
# =============================================================================
def fumigation_data(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['fumigated_units'] = text
    update.message.reply_text(
        apply_bold_keywords("Marque las observaciones para la próxima visita:"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = FUM_OBS
    return FUM_OBS

def get_fum_obs(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['fum_obs'] = text
    update.message.reply_text(
        apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO:"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = FUM_PHOTOS
    return FUM_PHOTOS

def get_fum_avisos(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['fum_avisos'] = text
    keyboard = [
        [InlineKeyboardButton("Si", callback_data='si'),
         InlineKeyboardButton("No", callback_data='no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        apply_bold_keywords("Entregaste avisos para el próximo mes en la dirección en la que hiciste el trabajo?"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = FUM_AVISOS_MENU
    return FUM_AVISOS_MENU

def handle_fum_avisos_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        query.edit_message_text(
            apply_bold_keywords("¿En qué direcciones? (Separe las direcciones con una coma)"),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = FUM_AVISOS_TEXT
        return FUM_AVISOS_TEXT
    else:
        query.edit_message_text(
            apply_bold_keywords("Gracias!"),
            parse_mode=ParseMode.HTML
        )
        send_email(context.user_data, update, context)
        return ConversationHandler.END

def handle_fum_avisos_callback(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    context.user_data['fum_avisos'] = query.data
    return ConversationHandler.END

# =============================================================================
# FUNCIONES PARA LIMPIEZA Y REPARACIÓN (TANQUES)
# =============================================================================
def handle_tank_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data == "back":
        return back_handler(update, context)
    selected = query.data
    context.user_data["selected_category"] = selected
    alternatives = [x for x in ["CISTERNA", "RESERVA", "INTERMEDIARIO"] if x != selected]
    context.user_data["alternative_1"] = alternatives[0]
    context.user_data["alternative_2"] = alternatives[1]
    query.edit_message_text(
        apply_bold_keywords(f"Tipo de tanque seleccionado: {selected.capitalize()}"),
        parse_mode=ParseMode.HTML
    )
    context.bot.send_message(
        chat_id=query.message.chat.id, 
        text=apply_bold_keywords(f"Indique la medida del tanque de {selected.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = MEASURE_MAIN
    return MEASURE_MAIN

def get_measure_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['measure_main'] = text
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS INSPECCIÓN (30 40 50 60 80):"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = TAPAS_INSPECCION_MAIN
    return TAPAS_INSPECCION_MAIN

def get_tapas_inspeccion_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_main'] = text
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = TAPAS_ACCESO_MAIN
    return TAPAS_ACCESO_MAIN

def get_tapas_acceso_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_main'] = text
    selected = context.user_data.get("selected_category", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique las observaciones y reparación de {selected}:"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = REPAIR_FIRST
    return REPAIR_FIRST

def get_repair_first(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    sel = context.user_data.get("selected_category")
    context.user_data[f'repair_{sel}'] = text
    alt1 = context.user_data.get("alternative_1")
    keyboard = [
        [InlineKeyboardButton("Si", callback_data='si'),
         InlineKeyboardButton("No", callback_data='no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        apply_bold_keywords(f"¿Quiere comentar algo sobre {alt1.capitalize()}?"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = ASK_SECOND
    return ASK_SECOND

def handle_ask_second(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        alt1 = context.user_data.get("alternative_1")
        query.edit_message_text(
            apply_bold_keywords(f"Indique la medida del tanque para {alt1.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = MEASURE_ALT1
        return MEASURE_ALT1
    elif query.data.lower() == "no":
        alt2 = context.user_data.get("alternative_2")
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(
            apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2.capitalize()}?"),
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = ASK_THIRD
        return ASK_THIRD
    else:
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Respuesta no reconocida, se asume 'No'."),
            parse_mode=ParseMode.HTML
        )
        update.effective_chat.send_message(
            apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:"),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

def get_measure_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['measure_alt1'] = text
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = TAPAS_INSPECCION_ALT1
    return TAPAS_INSPECCION_ALT1

def get_tapas_inspeccion_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_alt1'] = text
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS ACCESO para esta opción (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = TAPAS_ACCESO_ALT1
    return TAPAS_ACCESO_ALT1

def get_tapas_acceso_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_alt1'] = text
    alt1 = context.user_data.get("alternative_1")
    update.message.reply_text(
        apply_bold_keywords(f"Indique las observaciones y reparación de {alt1.capitalize()}:"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = REPAIR_ALT1
    return REPAIR_ALT1

def get_repair_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['repair_alt1'] = text
    alt2 = context.user_data.get("alternative_2")
    if alt2:
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(
            apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2.capitalize()}?"),
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = ASK_THIRD
        return ASK_THIRD
    else:
        update.message.reply_text(
            apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:"),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

def handle_ask_third(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        alt2 = context.user_data.get("alternative_2")
        query.edit_message_text(
            apply_bold_keywords(f"Indique la medida del tanque para {alt2.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = MEASURE_ALT2
        return MEASURE_ALT2
    elif query.data.lower() == "no":
        update.effective_chat.send_message(
            apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:"),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = PHOTOS
        return PHOTOS
    else:
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Respuesta no reconocida, se asume 'No'."),
            parse_mode=ParseMode.HTML
        )
        update.effective_chat.send_message(
            apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:"),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

def get_measure_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['measure_alt2'] = text
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = TAPAS_INSPECCION_ALT2
    return TAPAS_INSPECCION_ALT2

def get_tapas_inspeccion_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_alt2'] = text
    update.message.reply_text(
        apply_bold_keywords("Indique TAPAS ACCESO para esta opción (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = TAPAS_ACCESO_ALT2
    return TAPAS_ACCESO_ALT2

def get_tapas_acceso_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_alt2'] = text
    alt2 = context.user_data.get("alternative_2")
    update.message.reply_text(
        apply_bold_keywords(f"Indique las observaciones y reparación de {alt2.capitalize()}:"), 
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = REPAIR_ALT2
    return REPAIR_ALT2

def get_repair_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['repair_alt2'] = text
    update.message.reply_text(
        apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:"),
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = PHOTOS
    return PHOTOS

# =============================================================================
# NUEVA FUNCIÓN PARA HORARIO
# =============================================================================
def get_task_schedule(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['task_schedule'] = text
    keyboard = [
        [InlineKeyboardButton("Si", callback_data='si'),
         InlineKeyboardButton("No", callback_data='no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(
        apply_bold_keywords("Entregaste avisos en otras direcciones?"),
        reply_markup=reply_markup,
        parse_mode=ParseMode.HTML
    )
    context.user_data["current_state"] = AVISOS_MENU
    return AVISOS_MENU

# =============================================================================
# FUNCIONES PARA MANEJO DE FOTOS
# =============================================================================
def handle_photos(update: Update, context: CallbackContext) -> int:
    service = context.user_data.get('service')
    if service == "Fumigacion":
        if not update.message.photo:
            update.message.reply_text(
                apply_bold_keywords("Por favor, adjunte una imagen válida."),
                parse_mode=ParseMode.HTML
            )
            return FUM_PHOTOS
        photos = context.user_data.get("photos", [])
        file_id = update.message.photo[-1].file_id
        photos.append(file_id)
        context.user_data["photos"] = photos
        if len(photos) < 2:
            update.message.reply_text(
                apply_bold_keywords("Por favor cargue la segunda foto."),
                parse_mode=ParseMode.HTML
            )
            return FUM_PHOTOS
        else:
            update.message.reply_text(
                apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
                parse_mode=ParseMode.HTML
            )
            context.user_data["current_state"] = CONTACT
            return CONTACT
    else:
        if update.message.text and update.message.text.lower().strip() == "listo":
            if "photos" not in context.user_data or len(context.user_data["photos"]) == 0:
                update.message.reply_text(
                    apply_bold_keywords("Debe cargar al menos una foto antes de escribir 'Listo'."),
                    parse_mode=ParseMode.HTML
                )
                return PHOTOS
            else:
                update.message.reply_text(
                    apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
                    parse_mode=ParseMode.HTML
                )
                context.user_data["current_state"] = CONTACT
                return CONTACT
        elif update.message.photo:
            photos = context.user_data.get("photos", [])
            file_id = update.message.photo[-1].file_id
            photos.append(file_id)
            context.user_data["photos"] = photos
            update.message.reply_text(
                apply_bold_keywords("Foto recibida. Puede enviar más fotos o escriba 'Listo' para continuar."),
                parse_mode=ParseMode.HTML
            )
            return PHOTOS
        else:
            update.message.reply_text(
                apply_bold_keywords("Por favor, envíe una foto o escriba 'Listo' para continuar."),
                parse_mode=ParseMode.HTML
            )
            return PHOTOS

# =============================================================================
# FUNCIONES PARA MANEJO DE AVISOS
# =============================================================================
def handle_avisos_menu(update: Update, context: CallbackContext) -> int:
    if update.message and update.message.text and update.message.text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Indique qué direcciones (separadas por una coma):"),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = AVISOS_TEXT
        return AVISOS_TEXT
    else:
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Gracias!"),
            parse_mode=ParseMode.HTML
        )
        send_email(context.user_data, update, context)
        return ConversationHandler.END

def get_aviso_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['avisos_address'] = text
    send_email(context.user_data, update, context)
    update.message.reply_text(
        apply_bold_keywords("Gracias!"),
        parse_mode=ParseMode.HTML
    )
    return ConversationHandler.END

# =============================================================================
# FUNCIONES FALTANTES: get_contact y send_email
# =============================================================================
def get_contact(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data["contact"] = text
    if context.user_data.get("service", "").lower() == "fumigacion":
        update.message.reply_text(
            apply_bold_keywords("Gracias por proporcionar el contacto."),
            parse_mode=ParseMode.HTML
        )
        send_email(context.user_data, update, context)
        return ConversationHandler.END
    else:
        update.message.reply_text(
            apply_bold_keywords("Ingrese el Horario de INICIO y FIN de tareas:"),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = TASK_SCHEDULE
        return TASK_SCHEDULE

def send_email(user_data, update: Update, context: CallbackContext):
    subject = "Reporte de Servicio"
    body = "Detalles del reporte:\n"
    # Diccionario para mostrar etiquetas amigables en el correo
    field_mapping = {
        "code": "Código",
        "order": "Número de Orden",
        "address": "Dirección",
        "service": "Servicio",
        "fumigated_units": "Unidades con insectos",
        "fum_obs": "Observaciones de fumigación",
        "contact": "Contacto",
        "task_schedule": "Horario de tareas",
        "selected_category": "Tipo de tanque",
        "measure_main": "Medida principal",
        "tapas_inspeccion_main": "Tapas inspección principal",
        "tapas_acceso_main": "Tapas acceso principal",
        "measure_alt1": "Medida alternativa 1",
        "tapas_inspeccion_alt1": "Tapas inspección alternativa 1",
        "tapas_acceso_alt1": "Tapas acceso alternativa 1",
        "repair_alt1": "Reparación alternativa 1",
        "measure_alt2": "Medida alternativa 2",
        "tapas_inspeccion_alt2": "Tapas inspección alternativa 2",
        "tapas_acceso_alt2": "Tapas acceso alternativa 2",
        "repair_alt2": "Reparación alternativa 2",
        "avisos_address": "Direcciones avisos"
    }
    for key, label in field_mapping.items():
        if key in user_data:
            value = user_data[key]
            body += f"{label}: {value}\n"

    # Crear el mensaje de correo (multipart para incluir texto e imágenes)
    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    msg["To"] = "destinatario@example.com"
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    # Adjuntar las imágenes (descargadas a partir de sus file_id)
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
                parse_mode=ParseMode.HTML
            )
        else:
            context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=apply_bold_keywords("Correo enviado exitosamente."),
                parse_mode=ParseMode.HTML
            )
    except Exception as e:
        logger.error("Error al enviar email: %s", e)
        if update.message:
            update.message.reply_text(
                apply_bold_keywords("Error al enviar correo."),
                parse_mode=ParseMode.HTML
            )
        else:
            context.bot.send_message(
                chat_id=update.effective_chat.id, 
                text=apply_bold_keywords("Error al enviar correo."),
                parse_mode=ParseMode.HTML
            )

# =============================================================================
# FUNCIÓN MAIN
# =============================================================================
def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(Filters.regex("(?i)^hola$"), start_conversation)],
        states={
            CODE: [MessageHandler(Filters.text & ~Filters.command, get_code)],
            ORDER: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_order)
            ],
            ADDRESS: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_address)
            ],
            SERVICE: [
                CallbackQueryHandler(service_selection),
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)
            ],
            FUMIGATION: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, fumigation_data)
            ],
            FUM_OBS: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_fum_obs)
            ],
            FUM_PHOTOS: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.photo, handle_photos),
                MessageHandler(Filters.text & ~Filters.command, handle_photos)
            ],
            FUM_AVISOS: [
                CallbackQueryHandler(handle_fum_avisos_callback),
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_fum_avisos)
            ],
            FUM_AVISOS_MENU: [
                CallbackQueryHandler(handle_fum_avisos_menu),
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)
            ],
            FUM_AVISOS_TEXT: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_aviso_address)
            ],
            TANK_TYPE: [
                CallbackQueryHandler(handle_tank_type),
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)
            ],
            MEASURE_MAIN: [MessageHandler(Filters.text & ~Filters.command, get_measure_main)],
            TAPAS_INSPECCION_MAIN: [MessageHandler(Filters.text & ~Filters.command, get_tapas_inspeccion_main)],
            TAPAS_ACCESO_MAIN: [MessageHandler(Filters.text & ~Filters.command, get_tapas_acceso_main)],
            REPAIR_FIRST: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_repair_first)
            ],
            ASK_SECOND: [
                CallbackQueryHandler(handle_ask_second),
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)
            ],
            MEASURE_ALT1: [MessageHandler(Filters.text & ~Filters.command, get_measure_alt1)],
            TAPAS_INSPECCION_ALT1: [MessageHandler(Filters.text & ~Filters.command, get_tapas_inspeccion_alt1)],
            TAPAS_ACCESO_ALT1: [MessageHandler(Filters.text & ~Filters.command, get_tapas_acceso_alt1)],
            REPAIR_ALT1: [MessageHandler(Filters.text & ~Filters.command, get_repair_alt1)],
            ASK_THIRD: [
                CallbackQueryHandler(handle_ask_third),
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)
            ],
            MEASURE_ALT2: [MessageHandler(Filters.text & ~Filters.command, get_measure_alt2)],
            TAPAS_INSPECCION_ALT2: [MessageHandler(Filters.text & ~Filters.command, get_tapas_inspeccion_alt2)],
            TAPAS_ACCESO_ALT2: [MessageHandler(Filters.text & ~Filters.command, get_tapas_acceso_alt2)],
            REPAIR_ALT2: [MessageHandler(Filters.text & ~Filters.command, get_repair_alt2)],
            PHOTOS: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.photo, handle_photos),
                MessageHandler(Filters.text & ~Filters.command, handle_photos)
            ],
            CONTACT: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_contact)
            ],
            TASK_SCHEDULE: [MessageHandler(Filters.text & ~Filters.command, get_task_schedule)],
            AVISOS_MENU: [
                CallbackQueryHandler(handle_avisos_menu),
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)
            ],
            AVISOS_TEXT: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_aviso_address)
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
