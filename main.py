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
    pattern = r"(?i)\b(CISTERNA|RESERVA|INTERMEDIARIO)\b"
    return re.sub(pattern, lambda m: f"<b>{m.group(0)}</b>", text)

# =============================================================================
# CONFIGURACIÓN DEL LOGGING
# =============================================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG
)
logger = logging.getLogger(__name__)

# =============================================================================
# VARIABLES DE CONFIGURACIÓN
# =============================================================================
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "TU_TOKEN_AQUI")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "botpaulista25@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "fxvq jgue rkia gmtg")

# =============================================================================
# DEFINICIÓN DE ESTADOS
# =============================================================================
(
    CODE,               # 0
    SERVICE,            # 1
    ORDER,              # 2
    ADDRESS,            # 3
    FUMIGATION,         # 4
    FUM_OBS,            # 5
    FUM_PHOTOS,         # 6
    CONTACT,            # 7
    TANK_TYPE,          # 8
    MEASURE_MAIN,       # 9
    TAPAS_INSPECCION_MAIN,  # 10
    TAPAS_ACCESO_MAIN,      # 11
    REPAIR_MAIN,        # 12 -> Reparaciones para la sección principal
    SUGGESTIONS_MAIN,   # 13 -> Sugerencias para la sección principal
    ASK_SECOND,         # 14 -> ¿Quiere comentar algo sobre la alternativa 1?
    MEASURE_ALT1,       # 15
    TAPAS_INSPECCION_ALT1,  # 16
    TAPAS_ACCESO_ALT1,      # 17
    REPAIR_ALT1,        # 18 -> Reparaciones para la alternativa 1
    SUGGESTIONS_ALT1,   # 19 -> Sugerencias para la alternativa 1
    ASK_THIRD,          # 20 -> ¿Quiere comentar algo sobre la alternativa 2?
    MEASURE_ALT2,       # 21
    TAPAS_INSPECCION_ALT2,  # 22
    TAPAS_ACCESO_ALT2,      # 23
    REPAIR_ALT2,        # 24 -> Reparaciones para la alternativa 2
    SUGGESTIONS_ALT2,   # 25 -> Sugerencias para la alternativa 2
    PHOTOS,             # 26
    AVISOS_CODE,        # 27
    AVISOS_ADDRESS,     # 28
    AVISOS_PHOTOS       # 29
) = range(30)

# =============================================================================
# DICTIONARIO DE RETROCESO ("ATRÁS")
# =============================================================================
BACK_MAP = {
    ORDER: SERVICE,
    FUMIGATION: ADDRESS,
    FUM_OBS: FUMIGATION,
    FUM_PHOTOS: FUM_OBS,
    CONTACT: FUM_PHOTOS,
    TANK_TYPE: ADDRESS,
    MEASURE_MAIN: TANK_TYPE,
    TAPAS_INSPECCION_MAIN: MEASURE_MAIN,
    TAPAS_ACCESO_MAIN: TAPAS_INSPECCION_MAIN,
    REPAIR_MAIN: TAPAS_ACCESO_MAIN,
    SUGGESTIONS_MAIN: REPAIR_MAIN,
    ASK_SECOND: SUGGESTIONS_MAIN,
    MEASURE_ALT1: ASK_SECOND,
    TAPAS_INSPECCION_ALT1: MEASURE_ALT1,
    TAPAS_ACCESO_ALT1: TAPAS_INSPECCION_ALT1,
    REPAIR_ALT1: TAPAS_ACCESO_ALT1,
    SUGGESTIONS_ALT1: REPAIR_ALT1,
    ASK_THIRD: SUGGESTIONS_ALT1,
    MEASURE_ALT2: ASK_THIRD,
    TAPAS_INSPECCION_ALT2: MEASURE_ALT2,
    TAPAS_ACCESO_ALT2: TAPAS_INSPECCION_ALT2,
    REPAIR_ALT2: TAPAS_ACCESO_ALT2,
    SUGGESTIONS_ALT2: REPAIR_ALT2,
    PHOTOS: SUGGESTIONS_ALT2,
    AVISOS_CODE: SERVICE,
    AVISOS_ADDRESS: AVISOS_CODE,
    AVISOS_PHOTOS: AVISOS_ADDRESS
}

# =============================================================================
# FUNCIONES DE INICIO Y RETROCESO
# =============================================================================
def start_conversation(update: Update, context: CallbackContext) -> int:
    logger.debug("Inicio de conversación.")
    context.user_data.clear()
    update.message.reply_text(apply_bold_keywords("¡Hola! Inserte su código (solo números):"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = CODE
    return CODE

def back_handler(update: Update, context: CallbackContext) -> int:
    logger.debug("back_handler: Estado actual: %s", context.user_data.get("current_state"))
    if update.callback_query:
        update.callback_query.answer()
    current_state = context.user_data.get("current_state", CODE)
    if current_state == ADDRESS:
        if context.user_data.get("service") in ["Presupuestos", "Avisos"]:
            previous_state = SERVICE
        else:
            previous_state = ORDER
    else:
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
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("¡Hola! Inserte su código (solo números):"),
                                 parse_mode=ParseMode.HTML)
    elif state == SERVICE:
        keyboard = [
            [InlineKeyboardButton("Fumigaciones", callback_data="Fumigaciones")],
            [InlineKeyboardButton("Limpieza y Reparacion de Tanques", callback_data="Limpieza y Reparacion de Tanques")],
            [InlineKeyboardButton("Presupuestos", callback_data="Presupuestos")],
            [InlineKeyboardButton("Avisos", callback_data="Avisos")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("¿Qué servicio se realizó?"),
                                 reply_markup=reply_markup,
                                 parse_mode=ParseMode.HTML)
    elif state == ORDER:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Por favor, ingrese el número de orden (7 dígitos):"),
                                 parse_mode=ParseMode.HTML)
    elif state == ADDRESS:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Ingrese la dirección:"),
                                 parse_mode=ParseMode.HTML)
    elif state == FUMIGATION:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("¿Qué unidades contienen insectos?"),
                                 parse_mode=ParseMode.HTML)
    elif state == FUM_OBS:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Marque las observaciones para la próxima visita:"),
                                 parse_mode=ParseMode.HTML)
    elif state == FUM_PHOTOS:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO:"),
                                 parse_mode=ParseMode.HTML)
    elif state == TANK_TYPE:
        keyboard = [
            [InlineKeyboardButton("CISTERNA", callback_data='CISTERNA')],
            [InlineKeyboardButton("RESERVA", callback_data='RESERVA')],
            [InlineKeyboardButton("INTERMEDIARIO", callback_data='INTERMEDIARIO')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Seleccione el tipo de tanque:"),
                                 reply_markup=reply_markup,
                                 parse_mode=ParseMode.HTML)
    elif state == MEASURE_MAIN:
        selected = context.user_data.get("selected_category", "").capitalize()
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"Indique la medida del tanque de {selected} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
                                 parse_mode=ParseMode.HTML)
    elif state == TAPAS_INSPECCION_MAIN:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Indique TAPAS INSPECCIÓN (30 40 50 60 80):"),
                                 parse_mode=ParseMode.HTML)
    elif state == TAPAS_ACCESO_MAIN:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
                                 parse_mode=ParseMode.HTML)
    elif state == REPAIR_MAIN:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Indique reparaciones a realizar (EJ: tapas, revoques, etc) para la sección principal:"),
                                 parse_mode=ParseMode.HTML)
    elif state == SUGGESTIONS_MAIN:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Indique sugerencias p/ la próx limpieza (EJ: desagote):"),
                                 parse_mode=ParseMode.HTML)
    elif state == ASK_SECOND:
        alt1 = context.user_data.get("alternative_1", "")
        keyboard = [
            [InlineKeyboardButton("Si", callback_data="si"),
             InlineKeyboardButton("No", callback_data="no")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"¿Quiere comentar algo sobre {alt1.capitalize()}?"),
                                 reply_markup=reply_markup,
                                 parse_mode=ParseMode.HTML)
    elif state == MEASURE_ALT1:
        alt1 = context.user_data.get("alternative_1", "").capitalize()
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"Indique la medida del tanque para {alt1} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
                                 parse_mode=ParseMode.HTML)
    elif state == TAPAS_INSPECCION_ALT1:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
                                 parse_mode=ParseMode.HTML)
    elif state == TAPAS_ACCESO_ALT1:
        alt1 = context.user_data.get("alternative_1", "").capitalize()
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {alt1}:"),
                                 parse_mode=ParseMode.HTML)
    elif state == REPAIR_ALT1:
        alt1 = context.user_data.get("alternative_1", "").capitalize()
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"Indique reparaciones a realizar para {alt1} (EJ: tapas, revoques, etc):"),
                                 parse_mode=ParseMode.HTML)
    elif state == SUGGESTIONS_ALT1:
        alt1 = context.user_data.get("alternative_1", "").capitalize()
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {alt1}:"),
                                 parse_mode=ParseMode.HTML)
    elif state == ASK_THIRD:
        alt2 = context.user_data.get("alternative_2", "")
        keyboard = [
            [InlineKeyboardButton("Si", callback_data="si"),
             InlineKeyboardButton("No", callback_data="no")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2.capitalize()}?"),
                                 reply_markup=reply_markup,
                                 parse_mode=ParseMode.HTML)
    elif state == MEASURE_ALT2:
        alt2 = context.user_data.get("alternative_2", "").capitalize()
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"Indique la medida del tanque para {alt2} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
                                 parse_mode=ParseMode.HTML)
    elif state == TAPAS_INSPECCION_ALT2:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
                                 parse_mode=ParseMode.HTML)
    elif state == TAPAS_ACCESO_ALT2:
        alt2 = context.user_data.get("alternative_2", "").capitalize()
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {alt2}:"),
                                 parse_mode=ParseMode.HTML)
    elif state == REPAIR_ALT2:
        alt2 = context.user_data.get("alternative_2", "").capitalize()
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"Indique reparaciones a realizar para {alt2} (EJ: tapas, revoques, etc):"),
                                 parse_mode=ParseMode.HTML)
    elif state == SUGGESTIONS_ALT2:
        alt2 = context.user_data.get("alternative_2", "").capitalize()
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {alt2}:"),
                                 parse_mode=ParseMode.HTML)
    elif state == PHOTOS:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:\nSi ha terminado, escriba 'Listo'."),
                                 parse_mode=ParseMode.HTML)
    elif state == AVISOS_CODE:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Ingrese su código (solo números):"),
                                 parse_mode=ParseMode.HTML)
    elif state == AVISOS_ADDRESS:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Indique dirección/es donde se entregaron avisos:"),
                                 parse_mode=ParseMode.HTML)
    elif state == AVISOS_PHOTOS:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Adjunte las fotos de los avisos junto a la chapa con numeración del edificio:"),
                                 parse_mode=ParseMode.HTML)
    else:
        context.bot.send_message(chat_id=chat_id,
                                 text=apply_bold_keywords("Error: Estado desconocido."),
                                 parse_mode=ParseMode.HTML)

# =============================================================================
# FUNCIONES PARA EL FLUJO INICIAL Y VALIDACIÓN DE CAMPOS
# =============================================================================
def get_code(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if not text.isdigit():
        update.message.reply_text(apply_bold_keywords("El código debe ser numérico. Por favor, inténtalo de nuevo:"),
                                    parse_mode=ParseMode.HTML)
        return CODE
    context.user_data["code"] = text
    keyboard = [
        [InlineKeyboardButton("Fumigaciones", callback_data="Fumigaciones")],
        [InlineKeyboardButton("Limpieza y Reparacion de Tanques", callback_data="Limpieza y Reparacion de Tanques")],
        [InlineKeyboardButton("Presupuestos", callback_data="Presupuestos")],
        [InlineKeyboardButton("Avisos", callback_data="Avisos")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(apply_bold_keywords("¿Qué servicio se realizó?"),
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SERVICE
    return SERVICE

def service_selection(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    service_type = query.data
    context.user_data['service'] = service_type
    if service_type == "Fumigaciones":
        query.edit_message_text(apply_bold_keywords("Servicio seleccionado: Fumigaciones"),
                                parse_mode=ParseMode.HTML)
        context.bot.send_message(chat_id=query.message.chat.id,
                                 text=apply_bold_keywords("Por favor, ingrese el número de orden (7 dígitos):"),
                                 parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = ORDER
        return ORDER
    elif service_type == "Limpieza y Reparacion de Tanques":
        query.edit_message_text(apply_bold_keywords("Servicio seleccionado: Limpieza y Reparacion de Tanques"),
                                parse_mode=ParseMode.HTML)
        context.bot.send_message(chat_id=query.message.chat.id,
                                 text=apply_bold_keywords("Por favor indique su número de orden (7 dígitos):"),
                                 parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = ORDER
        return ORDER
    elif service_type == "Presupuestos":
        query.edit_message_text(apply_bold_keywords("Servicio seleccionado: Presupuestos"),
                                parse_mode=ParseMode.HTML)
        context.bot.send_message(chat_id=query.message.chat.id,
                                 text=apply_bold_keywords("Ingrese la dirección:"),
                                 parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = ADDRESS
        return ADDRESS
    elif service_type == "Avisos":
        query.edit_message_text(apply_bold_keywords("Servicio seleccionado: Avisos"),
                                parse_mode=ParseMode.HTML)
        context.bot.send_message(chat_id=query.message.chat.id,
                                 text=apply_bold_keywords("Ingrese su código (solo números):"),
                                 parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = AVISOS_CODE
        return AVISOS_CODE

def get_order(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if not text.isdigit() or len(text) != 7:
        update.message.reply_text(apply_bold_keywords("El número de orden debe ser numérico y contener 7 dígitos. Por favor, inténtalo de nuevo:"),
                                    parse_mode=ParseMode.HTML)
        return ORDER
    context.user_data["order"] = text
    update.message.reply_text(apply_bold_keywords("Ingrese la dirección:"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = ADDRESS
    return ADDRESS

def get_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['address'] = text
    service = context.user_data.get("service")
    if service == "Fumigaciones":
        update.message.reply_text(apply_bold_keywords("¿Qué unidades contienen insectos?"),
                                    parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = FUMIGATION
        return FUMIGATION
    elif service in ["Limpieza y Reparacion de Tanques", "Presupuestos"]:
        keyboard = [
            [InlineKeyboardButton("CISTERNA", callback_data='CISTERNA')],
            [InlineKeyboardButton("RESERVA", callback_data='RESERVA')],
            [InlineKeyboardButton("INTERMEDIARIO", callback_data='INTERMEDIARIO')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        update.message.reply_text(apply_bold_keywords("Seleccione el tipo de tanque:"),
                                    reply_markup=reply_markup,
                                    parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = TANK_TYPE
        return TANK_TYPE

# =============================================================================
# FUNCIONES PARA EL FLUJO DE AVISOS
# =============================================================================
def get_avisos_code(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if not text.isdigit():
        update.message.reply_text(apply_bold_keywords("El código debe ser numérico. Por favor, inténtalo de nuevo:"),
                                    parse_mode=ParseMode.HTML)
        return AVISOS_CODE
    context.user_data["avisos_code"] = text
    update.message.reply_text(apply_bold_keywords("Indique dirección/es donde se entregaron avisos:"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = AVISOS_ADDRESS
    return AVISOS_ADDRESS

def get_avisos_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data["avisos_address"] = text
    update.message.reply_text(apply_bold_keywords("Adjunte las fotos de los avisos junto a la chapa con numeración del edificio:"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = AVISOS_PHOTOS
    return AVISOS_PHOTOS

def handle_avisos_photos(update: Update, context: CallbackContext) -> int:
    if update.message.text and update.message.text.lower().strip() == "listo":
        if "photos" not in context.user_data or len(context.user_data["photos"]) == 0:
            update.message.reply_text(apply_bold_keywords("Debe cargar al menos una foto antes de escribir 'Listo'."),
                                        parse_mode=ParseMode.HTML)
            return AVISOS_PHOTOS
        else:
            send_email(context.user_data, update, context)
            return ConversationHandler.END
    elif update.message.photo:
        photos = context.user_data.get("photos", [])
        file_id = update.message.photo[-1].file_id
        photos.append(file_id)
        context.user_data["photos"] = photos
        update.message.reply_text(apply_bold_keywords("Foto recibida. Puede enviar más fotos o escriba 'Listo' para continuar."),
                                    parse_mode=ParseMode.HTML)
        return AVISOS_PHOTOS
    else:
        update.message.reply_text(apply_bold_keywords("Por favor, envíe una foto o escriba 'Listo' para continuar."),
                                    parse_mode=ParseMode.HTML)
        return AVISOS_PHOTOS

# =============================================================================
# FUNCIONES PARA FUMIGACIONES
# =============================================================================
def fumigation_data(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['fumigated_units'] = text
    update.message.reply_text(apply_bold_keywords("Marque las observaciones para la próxima visita:"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = FUM_OBS
    return FUM_OBS

def get_fum_obs(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['fum_obs'] = text
    update.message.reply_text(apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO:"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = FUM_PHOTOS
    return FUM_PHOTOS

# =============================================================================
# FUNCIONES PARA LIMPIEZA/REPARACIÓN Y PRESUPUESTOS (TANQUES) CON ALTERNATIVAS
# =============================================================================
def handle_tank_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    selected = query.data
    context.user_data["selected_category"] = selected
    alternatives = [x for x in ["CISTERNA", "RESERVA", "INTERMEDIARIO"] if x != selected]
    context.user_data["alternative_1"] = alternatives[0]
    context.user_data["alternative_2"] = alternatives[1]
    query.edit_message_text(apply_bold_keywords(f"Tipo de tanque seleccionado: {selected.capitalize()}"),
                            parse_mode=ParseMode.HTML)
    context.bot.send_message(chat_id=query.message.chat.id,
                             text=apply_bold_keywords(f"Indique la medida del tanque de {selected.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
                             parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = MEASURE_MAIN
    return MEASURE_MAIN

def get_measure_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['measure_main'] = text
    update.message.reply_text(apply_bold_keywords("Indique TAPAS INSPECCIÓN (30 40 50 60 80):"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_INSPECCION_MAIN
    return TAPAS_INSPECCION_MAIN

def get_tapas_inspeccion_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_main'] = text
    update.message.reply_text(apply_bold_keywords("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_ACCESO_MAIN
    return TAPAS_ACCESO_MAIN

def get_tapas_acceso_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_main'] = text
    update.message.reply_text(apply_bold_keywords("Indique reparaciones a realizar (EJ: tapas, revoques, etc) para la sección principal:"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = REPAIR_MAIN
    return REPAIR_MAIN

def get_repair_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['repairs'] = text
    update.message.reply_text(apply_bold_keywords("Indique sugerencias p/ la próx limpieza (EJ: desagote):"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SUGGESTIONS_MAIN
    return SUGGESTIONS_MAIN

def get_suggestions_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['suggestions'] = text
    keyboard = [
        [InlineKeyboardButton("Si", callback_data='si'),
         InlineKeyboardButton("No", callback_data='no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(apply_bold_keywords(f"¿Quiere comentar algo sobre {context.user_data.get('alternative_1', '').capitalize()}?"),
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = ASK_SECOND
    return ASK_SECOND

def handle_ask_second(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        alt1 = context.user_data.get("alternative_1")
        query.edit_message_text(apply_bold_keywords(f"Indique la medida del tanque para {alt1.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
                                  parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = MEASURE_ALT1
        return MEASURE_ALT1
    elif query.data.lower() == "no":
        alt2 = context.user_data.get("alternative_2")
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.edit_message_text(apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2.capitalize()}?"),
                                  reply_markup=reply_markup,
                                  parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = ASK_THIRD
        return ASK_THIRD
    else:
        context.bot.send_message(chat_id=query.message.chat.id,
                                 text=apply_bold_keywords("Respuesta no reconocida, se asume 'No'."),
                                 parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

def get_measure_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['measure_alt1'] = text
    update.message.reply_text(apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_INSPECCION_ALT1
    return TAPAS_INSPECCION_ALT1

def get_tapas_inspeccion_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_alt1'] = text
    update.message.reply_text(apply_bold_keywords("Indique TAPAS ACCESO para esta opción (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_ACCESO_ALT1
    return TAPAS_ACCESO_ALT1

def get_tapas_acceso_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_alt1'] = text
    alt1 = context.user_data.get("alternative_1")
    update.message.reply_text(apply_bold_keywords(f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {alt1.capitalize()}:"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = REPAIR_ALT1
    return REPAIR_ALT1

def get_repair_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['repair_alt1'] = text
    update.message.reply_text(apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {context.user_data.get('alternative_1', '').capitalize()}:"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SUGGESTIONS_ALT1
    return SUGGESTIONS_ALT1

def get_suggestions_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['suggestions_alt1'] = text
    keyboard = [
        [InlineKeyboardButton("Si", callback_data='si'),
         InlineKeyboardButton("No", callback_data='no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(apply_bold_keywords(f"¿Quiere comentar algo sobre {context.user_data.get('alternative_2', '').capitalize()}?"),
                                reply_markup=reply_markup,
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = ASK_THIRD
    return ASK_THIRD

# --- Función handle_ask_third agregada ---
def handle_ask_third(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        alt2 = context.user_data.get("alternative_2")
        query.edit_message_text(apply_bold_keywords(f"Indique la medida del tanque para {alt2.capitalize()} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"),
                                  parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = MEASURE_ALT2
        return MEASURE_ALT2
    elif query.data.lower() == "no":
        query.edit_message_text(apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:"),
                                  parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = PHOTOS
        return PHOTOS
    else:
        context.bot.send_message(chat_id=query.message.chat.id,
                                 text=apply_bold_keywords("Respuesta no reconocida, se asume 'No'."),
                                 parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = PHOTOS
        return PHOTOS
# --- Fin de handle_ask_third ---

def get_measure_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['measure_alt2'] = text
    update.message.reply_text(apply_bold_keywords("Indique TAPAS INSPECCIÓN para esta opción (30 40 50 60 80):"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_INSPECCION_ALT2
    return TAPAS_INSPECCION_ALT2

def get_tapas_inspeccion_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_inspeccion_alt2'] = text
    update.message.reply_text(apply_bold_keywords("Indique TAPAS ACCESO para esta opción (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = TAPAS_ACCESO_ALT2
    return TAPAS_ACCESO_ALT2

def get_tapas_acceso_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['tapas_acceso_alt2'] = text
    alt2 = context.user_data.get("alternative_2")
    update.message.reply_text(apply_bold_keywords(f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {alt2.capitalize()}:"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = REPAIR_ALT2
    return REPAIR_ALT2

def get_repair_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['repair_alt2'] = text
    update.message.reply_text(apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {context.user_data.get('alternative_2', '').capitalize()}:"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SUGGESTIONS_ALT2
    return SUGGESTIONS_ALT2

def get_suggestions_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['suggestions_alt2'] = text
    update.message.reply_text(apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:\nSi ha terminado, escriba 'Listo'."),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = PHOTOS
    return PHOTOS

# =============================================================================
# FUNCIONES PARA MANEJO DE FOTOS (TANQUES y FUMIGACIONES)
# =============================================================================
def handle_photos(update: Update, context: CallbackContext) -> int:
    service = context.user_data.get('service')
    if service == "Fumigaciones":
        if not update.message.photo:
            update.message.reply_text(apply_bold_keywords("Por favor, adjunte una imagen válida."),
                                        parse_mode=ParseMode.HTML)
            return FUM_PHOTOS
        photos = context.user_data.get("photos", [])
        file_id = update.message.photo[-1].file_id
        photos.append(file_id)
        context.user_data["photos"] = photos
        if len(photos) < 2:
            update.message.reply_text(apply_bold_keywords("Por favor cargue la segunda foto."),
                                        parse_mode=ParseMode.HTML)
            return FUM_PHOTOS
        else:
            update.message.reply_text(apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
                                        parse_mode=ParseMode.HTML)
            context.user_data["current_state"] = CONTACT
            return CONTACT
    else:
        if update.message.text and update.message.text.lower().strip() == "listo":
            if "photos" not in context.user_data or len(context.user_data["photos"]) == 0:
                update.message.reply_text(apply_bold_keywords("Debe cargar al menos una foto antes de escribir 'Listo'."),
                                            parse_mode=ParseMode.HTML)
                return PHOTOS
            else:
                update.message.reply_text(apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
                                            parse_mode=ParseMode.HTML)
                context.user_data["current_state"] = CONTACT
                return CONTACT
        elif update.message.photo:
            photos = context.user_data.get("photos", [])
            file_id = update.message.photo[-1].file_id
            photos.append(file_id)
            context.user_data["photos"] = photos
            update.message.reply_text(apply_bold_keywords("Foto recibida. Puede enviar más fotos o escriba 'Listo' para continuar."),
                                        parse_mode=ParseMode.HTML)
            return PHOTOS
        else:
            update.message.reply_text(apply_bold_keywords("Por favor, envíe una foto o escriba 'Listo' para continuar."),
                                        parse_mode=ParseMode.HTML)
            return PHOTOS

# =============================================================================
# FUNCIONES PARA CONTACTO Y ENVÍO DE EMAIL
# =============================================================================
def get_contact(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data["contact"] = text
    update.message.reply_text(apply_bold_keywords("Gracias por proporcionar el contacto."),
                                parse_mode=ParseMode.HTML)
    send_email(context.user_data, update, context)
    return ConversationHandler.END

def send_email(user_data, update: Update, context: CallbackContext):
    subject = "Reporte de Servicio"
    lines = []
    service = user_data.get("service", "")
    if service == "Avisos":
        subject = "Reporte de Avisos"
        if "avisos_code" in user_data:
            lines.append(f"Código: {user_data['avisos_code']}")
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
            ordered_fields.extend([
                ("selected_category", "Tipo de tanque"),
                ("measure_main", "Medida principal"),
                ("tapas_inspeccion_main", "Tapas inspección"),
                ("tapas_acceso_main", "Tapas acceso"),
                ("repairs", "Reparaciones (Principal)"),
                ("suggestions", "Sugerencias (Principal)"),
                ("measure_alt1", "Medida Alternativa 1"),
                ("tapas_inspeccion_alt1", "Tapas inspección Alternativa 1"),
                ("tapas_acceso_alt1", "Tapas acceso Alternativa 1"),
                ("repair_alt1", "Reparaciones Alternativa 1"),
                ("suggestions_alt1", "Sugerencias Alternativa 1"),
                ("measure_alt2", "Medida Alternativa 2"),
                ("tapas_inspeccion_alt2", "Tapas inspección Alternativa 2"),
                ("tapas_acceso_alt2", "Tapas acceso Alternativa 2"),
                ("repair_alt2", "Reparaciones Alternativa 2"),
                ("suggestions_alt2", "Sugerencias Alternativa 2")
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
    msg["To"] = "destinatario@example.com"
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
            update.message.reply_text(apply_bold_keywords("Correo enviado exitosamente."),
                                        parse_mode=ParseMode.HTML)
        else:
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=apply_bold_keywords("Correo enviado exitosamente."),
                                     parse_mode=ParseMode.HTML)
    except Exception as e:
        logger.error("Error al enviar email: %s", e)
        if update.message:
            update.message.reply_text(apply_bold_keywords("Error al enviar correo."),
                                        parse_mode=ParseMode.HTML)
        else:
            context.bot.send_message(chat_id=update.effective_chat.id,
                                     text=apply_bold_keywords("Error al enviar correo."),
                                     parse_mode=ParseMode.HTML)

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
            SERVICE: [CallbackQueryHandler(service_selection),
                      MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)],
            ORDER: [MessageHandler(Filters.text & ~Filters.command, get_order),
                    MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)],
            ADDRESS: [MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                      MessageHandler(Filters.text & ~Filters.command, get_address)],
            FUMIGATION: [MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                         MessageHandler(Filters.text & ~Filters.command, fumigation_data)],
            FUM_OBS: [MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                      MessageHandler(Filters.text & ~Filters.command, get_fum_obs)],
            FUM_PHOTOS: [MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                         MessageHandler(Filters.photo, handle_photos),
                         MessageHandler(Filters.text & ~Filters.command, handle_photos)],
            TANK_TYPE: [CallbackQueryHandler(handle_tank_type),
                        MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)],
            MEASURE_MAIN: [MessageHandler(Filters.text & ~Filters.command, get_measure_main)],
            TAPAS_INSPECCION_MAIN: [MessageHandler(Filters.text & ~Filters.command, get_tapas_inspeccion_main)],
            TAPAS_ACCESO_MAIN: [MessageHandler(Filters.text & ~Filters.command, get_tapas_acceso_main)],
            REPAIR_MAIN: [MessageHandler(Filters.text & ~Filters.command, get_repair_main)],
            SUGGESTIONS_MAIN: [MessageHandler(Filters.text & ~Filters.command, get_suggestions_main)],
            ASK_SECOND: [CallbackQueryHandler(handle_ask_second),
                         MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)],
            MEASURE_ALT1: [MessageHandler(Filters.text & ~Filters.command, get_measure_alt1)],
            TAPAS_INSPECCION_ALT1: [MessageHandler(Filters.text & ~Filters.command, get_tapas_inspeccion_alt1)],
            TAPAS_ACCESO_ALT1: [MessageHandler(Filters.text & ~Filters.command, get_tapas_acceso_alt1)],
            REPAIR_ALT1: [MessageHandler(Filters.text & ~Filters.command, get_repair_alt1)],
            SUGGESTIONS_ALT1: [MessageHandler(Filters.text & ~Filters.command, get_suggestions_alt1)],
            ASK_THIRD: [CallbackQueryHandler(handle_ask_third),
                        MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)],
            MEASURE_ALT2: [MessageHandler(Filters.text & ~Filters.command, get_measure_alt2)],
            TAPAS_INSPECCION_ALT2: [MessageHandler(Filters.text & ~Filters.command, get_tapas_inspeccion_alt2)],
            TAPAS_ACCESO_ALT2: [MessageHandler(Filters.text & ~Filters.command, get_tapas_acceso_alt2)],
            REPAIR_ALT2: [MessageHandler(Filters.text & ~Filters.command, get_repair_alt2)],
            SUGGESTIONS_ALT2: [MessageHandler(Filters.text & ~Filters.command, get_suggestions_alt2)],
            PHOTOS: [MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                     MessageHandler(Filters.photo, handle_photos),
                     MessageHandler(Filters.text & ~Filters.command, handle_photos)],
            CONTACT: [MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                      MessageHandler(Filters.text & ~Filters.command, get_contact)],
            AVISOS_CODE: [MessageHandler(Filters.text & ~Filters.command, get_avisos_code)],
            AVISOS_ADDRESS: [MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                             MessageHandler(Filters.text & ~Filters.command, get_avisos_address)],
            AVISOS_PHOTOS: [MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                            MessageHandler(Filters.photo, handle_avisos_photos),
                            MessageHandler(Filters.text & ~Filters.command, handle_avisos_photos)]
        },
        fallbacks=[]
    )

    dp.add_handler(conv_handler)
    logger.debug("Iniciando polling...")
    updater.start_polling()
    updater.idle()

if __name__ == "__main__":
    main()
