import logging
import os
import smtplib
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Updater, MessageHandler, Filters, CallbackQueryHandler,
                          ConversationHandler, CallbackContext)

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
# Asegúrate de definir estas variables o configurarlas en el entorno.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7650702859:AAHZfGk5ff5bfPbV3VzMK-XPKOkerjliM8M")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "botpaulista25@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "fxvq jgue rkia gmtg")

# =============================================================================
# DEFINICIÓN DE ESTADOS
# =============================================================================
# Se utilizarán 25 estados (0 a 24) para el flujo del ConversationHandler.
# Los estados son:
#  0: CODE                - Código de empleado (solo números)
#  1: ORDER               - Número de orden (solo números, exactamente 7 dígitos)
#  2: ADDRESS             - Dirección
#  3: SERVICE             - ¿Qué servicio se realizó?
#
# Para Fumigación:
#  4: FUMIGATION         - ¿Qué unidades contienen insectos?
# 13: FUM_OBS            - Observaciones para la próxima visita
# 14: FUM_PHOTOS         - Adjuntar fotos para fumigación
# 15: FUM_AVISOS         - Respuesta a avisos para el próximo mes
# 16: FUM_AVISOS_MENU    - Menú: avisos en otras direcciones
# 17: FUM_AVISOS_TEXT    - En qué direcciones, si respondió afirmativo
#
# Para Limpieza y Reparación:
#  5: TANK_TYPE          - Seleccione el tipo de tanque
#  6: REPAIR_FIRST       - Observaciones y reparación del tanque principal
#  7: ASK_SECOND         - ¿Quiere comentar algo sobre la alternativa 1?
#  8: ASK_THIRD          - ¿Quiere comentar algo sobre la alternativa 2?
#  9: PHOTOS             - Adjuntar fotos (el usuario puede enviar varias fotos y cuando termine escribe "Listo")
# 10: CONTACT            - Nombre y teléfono del encargado
# 11: AVISOS_MENU        - Menú: avisos en otras direcciones
# 12: AVISOS_TEXT        - Direcciones adicionales
#
# Para el tanque principal (medidas combinadas):
# 13: MEASURE_MAIN       - Formato: ALTO, ANCHO, PROFUNDO
# 14: TAPAS_INSPECCION_MAIN
# 15: TAPAS_ACCESO_MAIN
#
# Para la 1ª alternativa:
# 16: MEASURE_ALT1       - Formato: ALTO, ANCHO, PROFUNDO
# 17: TAPAS_INSPECCION_ALT1
# 18: TAPAS_ACCESO_ALT1
# 19: REPAIR_ALT1        - Observaciones y reparación para la alternativa 1
#
# Para la 2ª alternativa:
# 20: MEASURE_ALT2       - Formato: ALTO, ANCHO, PROFUNDO
# 21: TAPAS_INSPECCION_ALT2
# 22: TAPAS_ACCESO_ALT2
# 23: REPAIR_ALT2        - Observaciones y reparación para la alternativa 2
#
# Nueva pregunta para horario:
# 24: TASK_SCHEDULE      - Horario de INICIO y FIN de tareas
(CODE, ORDER, ADDRESS, SERVICE, FUMIGATION, TANK_TYPE, 
 REPAIR_FIRST, ASK_SECOND, ASK_THIRD, PHOTOS, CONTACT, AVISOS_MENU, AVISOS_TEXT,
 FUM_OBS, FUM_PHOTOS, FUM_AVISOS, FUM_AVISOS_MENU, FUM_AVISOS_TEXT,
 MEASURE_MAIN, TAPAS_INSPECCION_MAIN, TAPAS_ACCESO_MAIN,
 MEASURE_ALT1, TAPAS_INSPECCION_ALT1, TAPAS_ACCESO_ALT1, REPAIR_ALT1,
 MEASURE_ALT2, TAPAS_INSPECCION_ALT2, TAPAS_ACCESO_ALT2, REPAIR_ALT2,
 TASK_SCHEDULE) = range(25)

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
        context.bot.send_message(chat_id=chat_id, text="¡Hola! Inserte su código (solo números):")
    elif state == ORDER:
        context.bot.send_message(chat_id=chat_id, text="Escriba el número de la orden de trabajo (7 dígitos):")
    elif state == ADDRESS:
        context.bot.send_message(chat_id=chat_id, text="Escriba la dirección:")
    elif state == SERVICE:
        keyboard = [
            [InlineKeyboardButton("Fumigación", callback_data='Fumigacion')],
            [InlineKeyboardButton("Limpieza y reparación de tanques", callback_data='limpieza')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id, text="¿Qué servicio se realizó?", reply_markup=reply_markup)
    elif state == FUMIGATION:
        context.bot.send_message(chat_id=chat_id, text="¿Qué unidades contienen insectos?")
    elif state == FUM_OBS:
        context.bot.send_message(chat_id=chat_id, text="Marque las observaciones para la próxima visita:")
    elif state == FUM_PHOTOS:
        context.bot.send_message(chat_id=chat_id, text="Adjunte fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO:")
    elif state == FUM_AVISOS:
        context.bot.send_message(chat_id=chat_id, text="Entregaste avisos para el próximo mes en la dirección en la que hiciste el trabajo?")
    elif state == FUM_AVISOS_MENU:
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id, text="Entregaste avisos en otras direcciones?", reply_markup=reply_markup)
    elif state == FUM_AVISOS_TEXT:
        context.bot.send_message(chat_id=chat_id, text="¿En qué direcciones? (Separe las direcciones con una coma)")
    elif state == TANK_TYPE:
        keyboard = [
            [InlineKeyboardButton("CISTERNA", callback_data='cisterna')],
            [InlineKeyboardButton("RESERVA", callback_data='reserva')],
            [InlineKeyboardButton("INTERMEDIARIO", callback_data='intermediario')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id, text="Seleccione el tipo de tanque:", reply_markup=reply_markup)
    elif state == MEASURE_MAIN:
        selected = context.user_data.get("selected_category", "").capitalize()
        context.bot.send_message(chat_id=chat_id, text=f"Indique la medida del tanque de {selected} en el siguiente formato:\nALTO, ANCHO, PROFUNDO")
    elif state == TAPAS_INSPECCION_MAIN:
        context.bot.send_message(chat_id=chat_id, text="Indique TAPAS INSPECCIÓN:")
    elif state == TAPAS_ACCESO_MAIN:
        context.bot.send_message(chat_id=chat_id, text="Indique TAPAS ACCESO:")
    elif state == REPAIR_FIRST:
        selected = context.user_data.get("selected_category", "").capitalize()
        context.bot.send_message(chat_id=chat_id, text=f"Indique las observaciones y reparación de {selected}:")
    elif state == ASK_SECOND:
        alt1 = context.user_data.get("alternative_1")
        context.bot.send_message(chat_id=chat_id, text=f"¿Quiere comentar algo sobre {alt1.capitalize()}?")
    elif state == MEASURE_ALT1:
        alt1 = context.user_data.get("alternative_1")
        context.bot.send_message(chat_id=chat_id, text=f"Indique la medida del tanque para {alt1.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO")
    elif state == TAPAS_INSPECCION_ALT1:
        context.bot.send_message(chat_id=chat_id, text="Indique TAPAS INSPECCIÓN para esta opción:")
    elif state == TAPAS_ACCESO_ALT1:
        context.bot.send_message(chat_id=chat_id, text="Indique TAPAS ACCESO para esta opción:")
    elif state == REPAIR_ALT1:
        alt1 = context.user_data.get("alternative_1")
        context.bot.send_message(chat_id=chat_id, text=f"Indique las observaciones y reparación de {alt1.capitalize()}:")
    elif state == ASK_THIRD:
        alt2 = context.user_data.get("alternative_2")
        context.bot.send_message(chat_id=chat_id, text=f"¿Quiere comentar algo sobre {alt2.capitalize()}?")
    elif state == MEASURE_ALT2:
        alt2 = context.user_data.get("alternative_2")
        context.bot.send_message(chat_id=chat_id, text=f"Indique la medida del tanque para {alt2.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO")
    elif state == TAPAS_INSPECCION_ALT2:
        context.bot.send_message(chat_id=chat_id, text="Indique TAPAS INSPECCIÓN para esta opción:")
    elif state == TAPAS_ACCESO_ALT2:
        context.bot.send_message(chat_id=chat_id, text="Indique TAPAS ACCESO para esta opción:")
    elif state == REPAIR_ALT2:
        alt2 = context.user_data.get("alternative_2")
        context.bot.send_message(chat_id=chat_id, text=f"Indique las observaciones y reparación de {alt2.capitalize()}:")
    elif state == PHOTOS:
        context.bot.send_message(chat_id=chat_id, text="Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES.\nSi ha terminado, escriba 'Listo'.")
    elif state == CONTACT:
        context.bot.send_message(chat_id=chat_id, text="Ingrese el Nombre y teléfono del encargado:")
    elif state == TASK_SCHEDULE:
        context.bot.send_message(chat_id=chat_id, text="Indique el Horario de INICIO y FIN de tareas:")
    elif state == AVISOS_MENU:
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id, text="Entregaste avisos en otras direcciones?", reply_markup=reply_markup)
    elif state == AVISOS_TEXT:
        context.bot.send_message(chat_id=chat_id, text="Indique qué direcciones (separadas por una coma):")
    else:
        context.bot.send_message(chat_id=chat_id, text="Error: Estado desconocido.")

# =============================================================================
# FUNCIONES PARA VALIDAR CAMPOS NUMÉRICOS (get_code y get_order)
# =============================================================================
def get_code(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if not text.isdigit():
        update.message.reply_text("El código debe ser numérico. Por favor, inténtalo de nuevo:")
        return CODE
    context.user_data["code"] = text
    update.message.reply_text("Por favor, ingrese el número de orden (7 dígitos):")
    context.user_data["current_state"] = ORDER
    return ORDER

def get_order(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if not text.isdigit() or len(text) != 7:
        update.message.reply_text("El número de orden debe ser numérico y contener 7 dígitos. Por favor, inténtalo de nuevo:")
        return ORDER
    context.user_data["order"] = text
    update.message.reply_text("Ingrese la dirección:")
    context.user_data["current_state"] = ADDRESS
    return ADDRESS

# =============================================================================
# FUNCIONES DEL FLUJO DE CONVERSACIÓN
# =============================================================================
def start_conversation(update: Update, context: CallbackContext) -> int:
    logger.debug("Inicio de conversación.")
    context.user_data.clear()
    update.message.reply_text("¡Hola! Inserte su código (solo números):")
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
    update.message.reply_text("¿Qué servicio se realizó?", reply_markup=reply_markup)
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
        query.edit_message_text("Servicio seleccionado: Fumigación\n¿Qué unidades contienen insectos?")
        context.user_data["current_state"] = FUMIGATION
        return FUMIGATION
    else:
        query.edit_message_text("Servicio seleccionado: Limpieza y reparación de tanques")
        keyboard = [
            [InlineKeyboardButton("CISTERNA", callback_data='cisterna')],
            [InlineKeyboardButton("RESERVA", callback_data='reserva')],
            [InlineKeyboardButton("INTERMEDIARIO", callback_data='intermediario')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=query.message.chat_id,
                                 text="Seleccione el tipo de tanque:", reply_markup=reply_markup)
        context.user_data["current_state"] = TANK_TYPE
        return TANK_TYPE

# =============================================================================
# FUNCIONES PARA FUMIGACIÓN (se mantienen sin cambios)
# =============================================================================
def fumigation_data(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['fumigated_units'] = text
    update.message.reply_text("Marque las observaciones para la próxima visita:")
    context.user_data["current_state"] = FUM_OBS
    return FUM_OBS

def get_fum_obs(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['fum_obs'] = text
    update.message.reply_text("Adjunte fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO:")
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
    update.message.reply_text("Entregaste avisos para el próximo mes en la dirección en la que hiciste el trabajo?", reply_markup=reply_markup)
    context.user_data["current_state"] = FUM_AVISOS_MENU
    return FUM_AVISOS_MENU

def handle_fum_avisos_menu(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        query.edit_message_text("¿En qué direcciones? (Separe las direcciones con una coma)")
        context.user_data["current_state"] = FUM_AVISOS_TEXT
        return FUM_AVISOS_TEXT
    else:
        query.edit_message_text("Gracias!")
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
    alternatives = [x for x in ["cisterna", "reserva", "intermediario"] if x != selected]
    context.user_data["alternative_1"] = alternatives[0]
    context.user_data["alternative_2"] = alternatives[1]
    query.edit_message_text(f"Tipo de tanque seleccionado: {selected.capitalize()}")
    context.bot.send_message(chat_id=query.message.chat_id, 
                             text=f"Indique la medida del tanque de {selected.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO")
    context.user_data["current_state"] = MEASURE_MAIN
    return MEASURE_MAIN

def get_measure_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['measure_main'] = text
    update.message.reply_text("Indique TAPAS INSPECCIÓN:")
    context.user_data["current_state"] = TAPAS_INSPECCION_MAIN
    return TAPAS_INSPECCION_MAIN

def get_tapas_inspeccion_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_main'] = text
    update.message.reply_text("Indique TAPAS ACCESO:")
    context.user_data["current_state"] = TAPAS_ACCESO_MAIN
    return TAPAS_ACCESO_MAIN

def get_tapas_acceso_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_main'] = text
    selected = context.user_data.get("selected_category", "").capitalize()
    update.message.reply_text(f"Indique las observaciones y reparación de {selected}:")
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
    update.message.reply_text(f"¿Quiere comentar algo sobre {alt1.capitalize()}?", reply_markup=reply_markup)
    context.user_data["current_state"] = ASK_SECOND
    return ASK_SECOND

def handle_ask_second(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        alt1 = context.user_data.get("alternative_1")
        query.edit_message_text(f"Indique la medida del tanque para {alt1.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO")
        context.user_data["current_state"] = MEASURE_ALT1
        return MEASURE_ALT1
    elif query.data.lower() == "no":
        alt2 = context.user_data.get("alternative_2")
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(f"¿Quiere comentar algo sobre {alt2.capitalize()}?", reply_markup=reply_markup)
        context.user_data["current_state"] = ASK_THIRD
        return ASK_THIRD
    else:
        context.bot.send_message(chat_id=query.message.chat_id,
                                 text="Respuesta no reconocida, se asume 'No'.")
        update.effective_chat.send_message("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:")
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

def get_measure_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['measure_alt1'] = text
    update.message.reply_text("Indique TAPAS INSPECCIÓN para esta opción:")
    context.user_data["current_state"] = TAPAS_INSPECCION_ALT1
    return TAPAS_INSPECCION_ALT1

def get_tapas_inspeccion_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_alt1'] = text
    update.message.reply_text("Indique TAPAS ACCESO para esta opción:")
    context.user_data["current_state"] = TAPAS_ACCESO_ALT1
    return TAPAS_ACCESO_ALT1

def get_tapas_acceso_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_alt1'] = text
    alt1 = context.user_data.get("alternative_1")
    update.message.reply_text(f"Indique las observaciones y reparación de {alt1.capitalize()}:")
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
        update.message.reply_text(f"¿Quiere comentar algo sobre {alt2.capitalize()}?", reply_markup=reply_markup)
        context.user_data["current_state"] = ASK_THIRD
        return ASK_THIRD
    else:
        update.message.reply_text("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:")
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

def handle_ask_third(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        alt2 = context.user_data.get("alternative_2")
        query.edit_message_text(f"Indique la medida del tanque para {alt2.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO")
        context.user_data["current_state"] = MEASURE_ALT2
        return MEASURE_ALT2
    elif query.data.lower() == "no":
        update.effective_chat.send_message("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:")
        context.user_data["current_state"] = PHOTOS
        return PHOTOS
    else:
        context.bot.send_message(chat_id=query.message.chat_id,
                                 text="Respuesta no reconocida, se asume 'No'.")
        update.effective_chat.send_message("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:")
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

def get_measure_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['measure_alt2'] = text
    update.message.reply_text("Indique TAPAS INSPECCIÓN para esta opción:")
    context.user_data["current_state"] = TAPAS_INSPECCION_ALT2
    return TAPAS_INSPECCION_ALT2

def get_tapas_inspeccion_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_alt2'] = text
    update.message.reply_text("Indique TAPAS ACCESO para esta opción:")
    context.user_data["current_state"] = TAPAS_ACCESO_ALT2
    return TAPAS_ACCESO_ALT2

def get_tapas_acceso_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_alt2'] = text
    alt2 = context.user_data.get("alternative_2")
    update.message.reply_text(f"Indique las observaciones y reparación de {alt2.capitalize()}:")
    context.user_data["current_state"] = REPAIR_ALT2
    return REPAIR_ALT2

def get_repair_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['repair_alt2'] = text
    update.message.reply_text("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:")
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
    update.message.reply_text("Entregaste avisos en otras direcciones?", reply_markup=reply_markup)
    context.user_data["current_state"] = AVISOS_MENU
    return AVISOS_MENU

# =============================================================================
# FUNCIONES PARA MANEJO DE FOTOS
# =============================================================================
def handle_photos(update: Update, context: CallbackContext) -> int:
    service = context.user_data.get('service')
    if service == "Fumigacion":
        if not update.message.photo:
            update.message.reply_text("Por favor, adjunte una imagen válida.")
            return FUM_PHOTOS
        photos = context.user_data.get("photos", [])
        file_id = update.message.photo[-1].file_id
        photos.append(file_id)
        context.user_data["photos"] = photos
        if len(photos) < 2:
            update.message.reply_text("Por favor cargue la segunda foto.")
            return FUM_PHOTOS
        else:
            update.message.reply_text("Ingrese el Nombre y teléfono del encargado:")
            context.user_data["current_state"] = CONTACT
            return CONTACT
    else:
        # Para Limpieza: el usuario puede enviar fotos y cuando termine, debe escribir "Listo"
        if update.message.text and update.message.text.lower().strip() == "listo":
            if "photos" not in context.user_data or len(context.user_data["photos"]) == 0:
                update.message.reply_text("Debe cargar al menos una foto antes de escribir 'Listo'.")
                return PHOTOS
            else:
                update.message.reply_text("Ingrese el Nombre y teléfono del encargado:")
                context.user_data["current_state"] = CONTACT
                return CONTACT
        elif update.message.photo:
            photos = context.user_data.get("photos", [])
            file_id = update.message.photo[-1].file_id
            photos.append(file_id)
            context.user_data["photos"] = photos
            update.message.reply_text("Foto recibida. Puede enviar más fotos o escriba 'Listo' para continuar.")
            return PHOTOS
        else:
            update.message.reply_text("Por favor, envíe una foto o escriba 'Listo' para continuar.")
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
        context.bot.send_message(chat_id=query.message.chat_id, text="Indique qué direcciones (separadas por una coma):")
        context.user_data["current_state"] = AVISOS_TEXT
        return AVISOS_TEXT
    else:
        context.bot.send_message(chat_id=query.message.chat_id, text="Gracias!")
        send_email(context.user_data, update, context)
        return ConversationHandler.END

def get_aviso_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['avisos_address'] = text
    send_email(context.user_data, update, context)
    update.message.reply_text("Gracias!")
    return ConversationHandler.END

# =============================================================================
# FUNCIONES FALTANTES: get_contact y send_email
# =============================================================================
def get_contact(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data["contact"] = text
    # Diferenciar según el servicio seleccionado:
    if context.user_data.get("service", "").lower() == "fumigacion":
        update.message.reply_text("Gracias por proporcionar el contacto.")
        send_email(context.user_data, update, context)
        return ConversationHandler.END
    else:
        update.message.reply_text("Ingrese el Horario de INICIO y FIN de tareas:")
        context.user_data["current_state"] = TASK_SCHEDULE
        return TASK_SCHEDULE

def send_email(user_data, update: Update, context: CallbackContext):
    subject = "Reporte de Servicio"
    body = "Detalles del reporte:\n"
    for key, value in user_data.items():
        body += f"{key}: {value}\n"

    msg = MIMEMultipart()
    msg["From"] = EMAIL_ADDRESS
    # Configura el destinatario según lo requieras:
    msg["To"] = "destinatario@example.com"
    msg["Subject"] = subject
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        logger.info("Correo enviado exitosamente.")
        if update.message:
            update.message.reply_text("Correo enviado exitosamente.")
        else:
            context.bot.send_message(chat_id=update.effective_chat.id, text="Correo enviado exitosamente.")
    except Exception as e:
        logger.error("Error al enviar email: %s", e)
        if update.message:
            update.message.reply_text("Error al enviar correo.")
        else:
            context.bot.send_message(chat_id=update.effective_chat.id, text="Error al enviar correo.")

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
            # Fumigación
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
            # Limpieza y Reparación – principal y alternativas
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
