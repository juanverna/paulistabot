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
    level=logging.DEBUG  # Cambiar a INFO para menos detalle
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
(CODE,         # 0
 SERVICE,      # 1 -> Menú de servicio
 ORDER,        # 2 -> Número de orden (usado en Fumigaciones y Tanques)
 ADDRESS,      # 3 -> Dirección (para Fumigaciones, Tanques y Presupuestos)
 FUMIGATION,   # 4 -> "¿Qué unidades contienen insectos?" (Fumigaciones)
 FUM_OBS,      # 5 -> "Marque las observaciones para la próxima visita:" (Fumigaciones)
 FUM_PHOTOS,   # 6 -> Carga de fotos (Fumigaciones)
 CONTACT,      # 7 -> Contacto
 TANK_TYPE,    # 8 -> Selección de tipo de tanque (Tanques/Presupuestos)
 MEASURE_MAIN, # 9 -> Medida principal
 TAPAS_INSPECCION_MAIN,  # 10
 TAPAS_ACCESO_MAIN,      # 11
 REPAIR_FIRST,           # 12 -> "Indique reparaciones a realizar (EJ: tapas, revoques, etc):"
 SUGGESTIONS,            # 13 -> "Indique sugerencias p/ la próx limpieza (EJ: desagote despacio, etc):"
 PHOTOS,               # 14 -> Carga de fotos (Tanques/Presupuestos)
 AVISOS_CODE,          # 15 -> (Avisos) Pide código nuevamente
 AVISOS_ADDRESS,       # 16 -> (Avisos) Dirección/es donde se entregaron avisos
 AVISOS_PHOTOS         # 17 -> (Avisos) Fotos de avisos
) = range(18)

# =============================================================================
# DICTIONARIO DE RETROCESO ("ATRÁS")
# =============================================================================
# Para ADDRESS se diferencia según el servicio: si es "Presupuestos" o "Avisos", se vuelve a SERVICE; 
# de lo contrario se vuelve a ORDER.
BACK_MAP = {
    ORDER: SERVICE,
    # ADDRESS se maneja en back_handler según el servicio
    FUMIGATION: ADDRESS,
    FUM_OBS: FUMIGATION,
    FUM_PHOTOS: FUM_OBS,
    CONTACT: FUM_PHOTOS,  # Para fumigaciones; en tanques, CONTACT viene después de PHOTOS.
    TANK_TYPE: ADDRESS,
    MEASURE_MAIN: TANK_TYPE,
    TAPAS_INSPECCION_MAIN: MEASURE_MAIN,
    TAPAS_ACCESO_MAIN: TAPAS_INSPECCION_MAIN,
    REPAIR_FIRST: TAPAS_ACCESO_MAIN,
    SUGGESTIONS: REPAIR_FIRST,
    PHOTOS: SUGGESTIONS,
    # Avisos branch:
    AVISOS_CODE: SERVICE,
    AVISOS_ADDRESS: AVISOS_CODE,
    AVISOS_PHOTOS: AVISOS_ADDRESS
}

# =============================================================================
# FUNCIONES DE RETROCESO (back_handler Y re_ask)
# =============================================================================
def back_handler(update: Update, context: CallbackContext) -> int:
    logger.debug("back_handler: Estado actual: %s", context.user_data.get("current_state"))
    if update.callback_query:
        update.callback_query.answer()
    current_state = context.user_data.get("current_state", CODE)
    if current_state == ADDRESS:
        # Si el servicio es Presupuestos o Avisos, volver a SERVICE; de lo contrario, a ORDER.
        if context.user_data.get("service") in ["Presupuestos", "Avisos"]:
            previous_state = SERVICE
        else:
            previous_state = BACK_MAP.get(ORDER)
            previous_state = ORDER  # Para flujos que usan ORDER
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
    elif state == REPAIR_FIRST:
        context.bot.send_message(chat_id=chat_id, 
                                 text=apply_bold_keywords("Indique reparaciones a realizar (EJ: tapas, revoques, etc):"), 
                                 parse_mode=ParseMode.HTML)
    elif state == SUGGESTIONS:
        context.bot.send_message(chat_id=chat_id, 
                                 text=apply_bold_keywords("Indique sugerencias p/ la próx limpieza (EJ: desagote despacio, etc):"), 
                                 parse_mode=ParseMode.HTML)
    elif state == PHOTOS:
        context.bot.send_message(chat_id=chat_id, 
                                 text=apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:\nSi ha terminado, escriba 'Listo'."), 
                                 parse_mode=ParseMode.HTML)
    elif state == CONTACT:
        context.bot.send_message(chat_id=chat_id, 
                                 text=apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"), 
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
# FUNCIONES PARA VALIDAR CAMPOS NUMÉRICOS Y FLUJO INICIAL
# =============================================================================
def get_code(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if not text.isdigit():
        update.message.reply_text(apply_bold_keywords("El código debe ser numérico. Por favor, inténtalo de nuevo:"), 
                                    parse_mode=ParseMode.HTML)
        return CODE
    context.user_data["code"] = text
    # Mostrar menú de servicios
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
    service_type = query.data  # "Fumigaciones", "Limpieza y Reparacion de Tanques", "Presupuestos", "Avisos"
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
# FUNCIONES PARA LIMPIEZA/REPARACIÓN Y PRESUPUESTOS (TANQUES)
# =============================================================================
def handle_tank_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data.lower() == "back":
        return back_handler(update, context)
    selected = query.data
    context.user_data["selected_category"] = selected
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
    update.message.reply_text(apply_bold_keywords("Indique reparaciones a realizar (EJ: tapas, revoques, etc):"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = REPAIR_FIRST
    return REPAIR_FIRST

def get_repair_first(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['repairs'] = text
    update.message.reply_text(apply_bold_keywords("Indique sugerencias p/ la próx limpieza (EJ: desagote despacio, etc):"),
                                parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SUGGESTIONS
    return SUGGESTIONS

def get_suggestions(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['suggestions'] = text
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
        # Para Tanques y Presupuestos
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
                ("repairs", "Reparaciones a realizar"),
                ("suggestions", "Sugerencias p/ la próx limpieza")
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
            REPAIR_FIRST: [MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                           MessageHandler(Filters.text & ~Filters.command, get_repair_first)],
            SUGGESTIONS: [MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                          MessageHandler(Filters.text & ~Filters.command, get_suggestions)],
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
