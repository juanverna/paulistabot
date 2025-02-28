import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Updater, MessageHandler, Filters, CallbackQueryHandler,
                          ConversationHandler, CallbackContext)
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from io import BytesIO
import os

# =============================================================================
# CONFIGURACIÓN DEL LOGGING
# =============================================================================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.DEBUG  # Cambia a INFO para menos detalle
)
logger = logging.getLogger(__name__)

# =============================================================================
# DEFINICIÓN DE ESTADOS
# =============================================================================
# Estados comunes:
# 0: CODE (Código de empleado)
# 1: ORDER (Número de orden)
# 2: ADDRESS (Dirección)
# 3: SERVICE (¿Qué servicio se realizó?)
#
# Para fumigaciones:
# 4: FUMIGATION (¿Qué unidades contienen insectos?)
# 15: FUM_OBS (Observaciones para la próxima visita)
# 16: FUM_PHOTOS (Adjuntar fotos para fumigación)
# 17: FUM_AVISOS (Respuesta a "Entregaste avisos para el próximo mes en la dirección en la que hiciste el trabajo?")
# 18: FUM_AVISOS_MENU (Menú: "Entregaste avisos en otras direcciones?")
# 19: FUM_AVISOS_TEXT (En qué direcciones, si respondió afirmativo)
#
# Para limpieza y reparación:
# 5: TANK_TYPE (Seleccione el tipo de tanque)
# 6: REPAIR_FIRST (Observaciones para la opción seleccionada)
# 7: ASK_SECOND (¿Quiere comentar algo sobre la primera alternativa?)
# 8: REPAIR_SECOND (Observaciones para la primera alternativa)
# 9: ASK_THIRD (¿Quiere comentar algo sobre la segunda alternativa?)
# 10: REPAIR_THIRD (Observaciones para la segunda alternativa)
# 11: PHOTOS (Adjuntar fotos para limpieza/reparación)
# 12: CONTACT (Nombre y teléfono del encargado)
# 13: AVISOS_MENU (Menú: "Entregaste avisos en otras direcciones?")
# 14: AVISOS_TEXT (Direcciones adicionales)
(CODE, ORDER, ADDRESS, SERVICE, FUMIGATION, TANK_TYPE, 
 REPAIR_FIRST, ASK_SECOND, REPAIR_SECOND, ASK_THIRD, REPAIR_THIRD,
 PHOTOS, CONTACT, AVISOS_MENU, AVISOS_TEXT, 
 FUM_OBS, FUM_PHOTOS, FUM_AVISOS, FUM_AVISOS_MENU, FUM_AVISOS_TEXT) = range(20)

# =============================================================================
# DICTIONARIO DE RETROCESO (“ATRÁS”)
# =============================================================================
BACK_MAP = {
    ORDER: CODE,
    ADDRESS: ORDER,
    SERVICE: ADDRESS,
    FUMIGATION: SERVICE,
    TANK_TYPE: SERVICE,
    REPAIR_FIRST: TANK_TYPE,
    ASK_SECOND: REPAIR_FIRST,
    REPAIR_SECOND: ASK_SECOND,
    ASK_THIRD: REPAIR_SECOND,
    REPAIR_THIRD: ASK_THIRD,
    PHOTOS: REPAIR_THIRD,  # Para limpieza, PHOTOS retrocede a REPAIR_THIRD
    CONTACT: PHOTOS,
    AVISOS_MENU: CONTACT,
    AVISOS_TEXT: AVISOS_MENU,
    # Para fumigación:
    FUM_OBS: FUMIGATION,
    FUM_PHOTOS: FUM_OBS,
    FUM_AVISOS: FUM_PHOTOS,
    FUM_AVISOS_MENU: FUM_AVISOS,
    FUM_AVISOS_TEXT: FUM_AVISOS_MENU
}

# =============================================================================
# CONFIGURACIÓN DEL CORREO Y DEL BOT
# =============================================================================
RECIPIENT_EMAIL = "botpaulista25@gmail.com"
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "botpaulista25@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "fxvq jgue rkia gmtg")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7650702859:AAHZfGk5ff5bfPbV3VzMK-XPKOkerjliM8M")

# =============================================================================
# FUNCIONES DE ENVÍO DE CORREO
# =============================================================================
def send_email(data, update: Update, context: CallbackContext):
    """Envía un correo con la información recopilada, incluyendo imágenes adjuntas."""
    msg = MIMEMultipart()
    msg['Subject'] = "Reporte de servicio"
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = RECIPIENT_EMAIL

    # Se arma el encabezado común
    body = f"""Formulario completado:
Código de empleado: {data.get('code', 'N/A')}
Orden de trabajo: {data.get('order', 'N/A')}
Dirección: {data.get('address', 'N/A')}
Servicio: {data.get('service', 'N/A')}
"""
    service = data.get('service', 'N/A')
    # Se arma el cuerpo según el rubro elegido
    if service == "Fumigacion":
        body += f"Unidades con insectos: {data.get('fumigated_units', 'N/A')}\n"
        body += f"Observaciones para la próxima visita: {data.get('fum_obs', 'N/A')}\n"
        body += f"Nombre y teléfono del encargado: {data.get('contact', 'N/A')}\n"
        body += f"Avisos: {data.get('avisos_address', 'N/A')}\n"
    elif service == "limpieza":
        selected = data.get("selected_category", "N/A").capitalize()
        body += f"Tipo de tanque seleccionado: {selected}\n"
        body += f"Observaciones y reparación de {selected}: {data.get('repair_'+data.get('selected_category',''), 'N/A')}\n"
        if data.get('repair_'+data.get('alternative_1','')):
            alt1 = data.get("alternative_1", "").capitalize()
            body += f"Observaciones y reparación de {alt1}: {data.get('repair_'+data.get('alternative_1',''), 'N/A')}\n"
        if data.get('repair_'+data.get('alternative_2','')):
            alt2 = data.get("alternative_2", "").capitalize()
            body += f"Observaciones y reparación de {alt2}: {data.get('repair_'+data.get('alternative_2',''), 'N/A')}\n"
        body += f"Nombre y teléfono del encargado: {data.get('contact', 'N/A')}\n"
        body += f"Avisos: {data.get('avisos_address', 'N/A')}\n"
    else:
        # En caso de que no se reconozca el servicio, se envían solo los campos comunes
        body += f"Nombre y teléfono del encargado: {data.get('contact', 'N/A')}\n"

    msg.attach(MIMEText(body, 'plain'))

    # Descargar y adjuntar las imágenes enviadas por el usuario
    photos = data.get("photos")
    if photos:
        for idx, file_id in enumerate(photos, start=1):
            try:
                telegram_file = context.bot.get_file(file_id)
                bio = BytesIO()
                telegram_file.download(out=bio)
                bio.seek(0)
                image = MIMEImage(bio.read())
                image.add_header('Content-Disposition', 'attachment', filename=f'photo_{idx}.jpg')
                msg.attach(image)
            except Exception as e:
                logger.error("Error descargando o adjuntando la imagen %s: %s", file_id, e)
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
        logger.debug("Correo enviado exitosamente.")
    except Exception as e:
        logger.error("Error sending email: %s", e)

# =============================================================================
# FUNCIONES DE RETROCESO (“ATRÁS”)
# =============================================================================
def back_handler(update: Update, context: CallbackContext) -> int:
    """Retrocede al estado anterior y reenvía la pregunta correspondiente."""
    logger.debug("back_handler: Estado actual: %s", context.user_data.get("current_state"))
    if update.callback_query:
        update.callback_query.answer()
    current_state = context.user_data.get("current_state", CODE)
    if current_state == FUM_PHOTOS:
        previous_state = context.user_data.get("prev_state_photos", FUM_PHOTOS)
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
    """Reenvía la pregunta correspondiente al estado indicado."""
    chat_id = update.effective_chat.id
    logger.debug("re_ask: Estado %s", state)
    if state == CODE:
        context.bot.send_message(chat_id=chat_id, text="¡Hola! Inserte su código:")
    elif state == ORDER:
        context.bot.send_message(chat_id=chat_id, text="Escriba el número de la orden de trabajo:")
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
    # Para fumigación: pedir fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO
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
    elif state == REPAIR_FIRST:
        sel = context.user_data.get("selected_category", "la opción").capitalize()
        context.bot.send_message(chat_id=chat_id, text=f"Indique las observaciones y reparación de {sel}:")
    elif state == ASK_SECOND:
        alt1 = context.user_data.get("alternative_1", "la primera alternativa").capitalize()
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id, text=f"¿Quiere comentar algo sobre {alt1}?", reply_markup=reply_markup)
    elif state == REPAIR_SECOND:
        alt1 = context.user_data.get("alternative_1", "la primera alternativa").capitalize()
        context.bot.send_message(chat_id=chat_id, text=f"Indique las observaciones y reparación de {alt1}:")
    elif state == ASK_THIRD:
        alt2 = context.user_data.get("alternative_2", "la segunda alternativa").capitalize()
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id, text=f"¿Quiere comentar algo sobre {alt2}?", reply_markup=reply_markup)
    elif state == REPAIR_THIRD:
        alt2 = context.user_data.get("alternative_2", "la segunda alternativa").capitalize()
        context.bot.send_message(chat_id=chat_id, text=f"Indique las observaciones y reparación de {alt2}:")
    # Para limpieza y reparación: pedir fotos de ORDEN DE TRABAJO, FICHA y TANQUES
    elif state == PHOTOS:
        context.bot.send_message(chat_id=chat_id, text="Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES (cada foto en un mensaje separado):")
    elif state == CONTACT:
        context.bot.send_message(chat_id=chat_id, text="Ingrese el Nombre y teléfono del encargado:")
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
# FUNCIONES DEL FLUJO DE CONVERSACIÓN
# =============================================================================
def start_conversation(update: Update, context: CallbackContext) -> int:
    logger.debug("Inicio de conversación.")
    # Se limpian los datos de conversaciones previas para evitar que se acumulen imágenes u otros datos.
    context.user_data.clear()
    update.message.reply_text("¡Hola! Inserte su código:")
    context.user_data["current_state"] = CODE
    return CODE

def get_code(update: Update, context: CallbackContext) -> int:
    text = update.message.text.strip()
    logger.debug("get_code: %s", text)
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['code'] = text
    update.message.reply_text("Escriba el número de la orden de trabajo:")
    context.user_data["current_state"] = ORDER
    return ORDER

def get_order(update: Update, context: CallbackContext) -> int:
    text = update.message.text.strip()
    logger.debug("get_order: %s", text)
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    # Se requiere que el número de orden tenga EXACTAMENTE 7 dígitos
    if not text.isdigit() or len(text) != 7:
        update.message.reply_text("Por favor, ingrese un número de orden numérico de EXACTAMENTE 7 dígitos:")
        return ORDER
    context.user_data['order'] = text
    update.message.reply_text("Escriba la dirección:")
    context.user_data["current_state"] = ADDRESS
    return ADDRESS

def get_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    logger.debug("get_address: %s", text)
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
    logger.debug("service_selection invoked.")
    if update.message and update.message.text:
        if update.message.text.lower().replace("á", "a") == "atras":
            return back_handler(update, context)
    query = update.callback_query
    query.answer()
    if query.data == "back":
        return back_handler(update, context)
    service_type = query.data
    logger.debug("Servicio seleccionado: %s", service_type)
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
        context.bot.send_message(chat_id=update.effective_chat.id, text="Seleccione el tipo de tanque:", reply_markup=reply_markup)
        context.user_data["current_state"] = TANK_TYPE
        return TANK_TYPE

# Funciones para la rama de fumigación
def fumigation_data(update: Update, context: CallbackContext) -> int:
    """Recoge las unidades con insectos para fumigación."""
    text = update.message.text
    logger.debug("fumigation_data: %s", text)
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['fumigated_units'] = text
    update.message.reply_text("Marque las observaciones para la próxima visita:")
    context.user_data["current_state"] = FUM_OBS
    return FUM_OBS

def get_fum_obs(update: Update, context: CallbackContext) -> int:
    """Recoge las observaciones para la próxima visita en fumigación."""
    text = update.message.text
    logger.debug("get_fum_obs: %s", text)
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['fum_obs'] = text
    update.message.reply_text("Adjunte fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO:")
    context.user_data["current_state"] = FUM_PHOTOS
    return FUM_PHOTOS

def get_fum_avisos(update: Update, context: CallbackContext) -> int:
    """Recoge la respuesta a 'Entregaste avisos para el próximo mes en la dirección en la que hiciste el trabajo?' vía texto."""
    text = update.message.text
    logger.debug("get_fum_avisos: %s", text)
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

def handle_fum_avisos_callback(update: Update, context: CallbackContext) -> int:
    """Procesa la respuesta a 'Entregaste avisos para el próximo mes en la dirección en la que hiciste el trabajo?' vía botones inline."""
    query = update.callback_query
    query.answer()
    logger.debug("handle_fum_avisos_callback: %s", query.data)
    context.user_data['fum_avisos'] = query.data
    # Se podría continuar con otro flujo, pero en este caso no se utiliza.
    return ConversationHandler.END

# Funciones para la rama de limpieza y reparación (se mantienen sin cambios salvo las modificaciones indicadas)
def handle_tank_type(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    logger.debug("handle_tank_type: %s", query.data)
    if query.data == "back":
        return back_handler(update, context)
    selected = query.data  # 'cisterna', 'reserva' o 'intermediario'
    context.user_data["selected_category"] = selected
    alternatives = [x for x in ["cisterna", "reserva", "intermediario"] if x != selected]
    context.user_data["alternative_1"] = alternatives[0]
    context.user_data["alternative_2"] = alternatives[1]
    query.edit_message_text(f"Tipo de tanque seleccionado: {selected.capitalize()}")
    context.bot.send_message(chat_id=update.effective_chat.id,
         text=f"Indique las observaciones y reparación de {selected.capitalize()}:")
    context.user_data["current_state"] = REPAIR_FIRST
    return REPAIR_FIRST

def get_repair_first(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    logger.debug("get_repair_first: %s", text)
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
    logger.debug("handle_ask_second: %s", query.data)
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        alt1 = context.user_data.get("alternative_1")
        query.edit_message_text(f"Indique las observaciones y reparación de {alt1.capitalize()}:")
        context.user_data["current_state"] = REPAIR_SECOND
        return REPAIR_SECOND
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
        context.bot.send_message(chat_id=update.effective_chat.id,
            text="Respuesta no reconocida, se asume 'No'.")
        update.effective_chat.send_message("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:")
        context.user_data["prev_state_photos"] = REPAIR_SECOND
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

def get_repair_second(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    logger.debug("get_repair_second: %s", text)
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    alt1 = context.user_data.get("alternative_1")
    context.user_data[f'repair_{alt1}'] = text
    alt2 = context.user_data.get("alternative_2")
    keyboard = [
        [InlineKeyboardButton("Si", callback_data='si'),
         InlineKeyboardButton("No", callback_data='no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text(f"¿Quiere comentar algo sobre {alt2.capitalize()}?", reply_markup=reply_markup)
    context.user_data["current_state"] = ASK_THIRD
    return ASK_THIRD

def handle_ask_third(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    logger.debug("handle_ask_third: %s", query.data)
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        alt2 = context.user_data.get("alternative_2")
        query.edit_message_text(f"Indique las observaciones y reparación de {alt2.capitalize()}:")
        context.user_data["current_state"] = REPAIR_THIRD
        return REPAIR_THIRD
    elif query.data.lower() == "no":
        update.effective_chat.send_message("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:")
        context.user_data["prev_state_photos"] = REPAIR_THIRD
        context.user_data["current_state"] = PHOTOS
        return PHOTOS
    else:
        context.bot.send_message(chat_id=update.effective_chat.id,
            text="Respuesta no reconocida, se asume 'No'.")
        update.effective_chat.send_message("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:")
        context.user_data["prev_state_photos"] = REPAIR_THIRD
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

def get_repair_third(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    logger.debug("get_repair_third: %s", text)
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    alt2 = context.user_data.get("alternative_2")
    context.user_data[f'repair_{alt2}'] = text
    update.message.reply_text("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:")
    context.user_data["prev_state_photos"] = REPAIR_THIRD
    context.user_data["current_state"] = PHOTOS
    return PHOTOS

# =============================================================================
# Función para el manejo de fotos (usadas tanto en limpieza como en fumigación)
# =============================================================================
def handle_photos(update: Update, context: CallbackContext) -> int:
    """
    Maneja la recepción de fotos.

    Para fumigaciones: se requieren 2 fotos (ORDEN DE TRABAJO y PORTERO ELECTRICO).  
    Para tanques: se requieren 3 fotos (ORDEN DE TRABAJO, FICHA y TANQUES),
    cada una enviada en un mensaje separado.

    Si el mensaje recibido no contiene imagen o se adjunta un archivo inválido,
    se muestra un mensaje de error.
    """
    # Determinar la cantidad requerida según el servicio
    service = context.user_data.get('service')
    if service == "Fumigacion":
        required_count = 2
        target_state = FUM_PHOTOS  # Estado actual en fumigación
    else:
        required_count = 3
        target_state = PHOTOS       # Estado actual en limpieza/reparación

    # Validar que el archivo adjuntado sea una imagen
    if not update.message.photo:
        if update.message.document:
            mime_type = update.message.document.mime_type
            if not mime_type.startswith("image/"):
                update.message.reply_text("Por favor, adjunte un archivo de imagen válido. No se permite avanzar sin una imagen.")
                context.user_data["current_state"] = target_state
                return target_state
        else:
            update.message.reply_text("Por favor, adjunte un archivo de imagen válido. No se permite avanzar sin una imagen.")
            context.user_data["current_state"] = target_state
            return target_state

    # Para limpieza y reparación: asegurar que cada imagen se envíe en un mensaje separado.
    if service != "Fumigacion" and update.message.media_group_id:
        if context.user_data.get("last_media_group_id") == update.message.media_group_id:
            update.message.reply_text("Por favor, envíe cada imagen en un mensaje separado.")
            context.user_data["current_state"] = target_state
            return target_state
        else:
            context.user_data["last_media_group_id"] = update.message.media_group_id

    # Procesar la imagen
    photos = context.user_data.get("photos", [])
    file_id = update.message.photo[-1].file_id
    photos.append(file_id)
    context.user_data["photos"] = photos
    logger.debug("Fotos acumuladas: %s", len(photos))

    if len(photos) < required_count:
        if required_count == 2:
            update.message.reply_text("Por favor cargue la segunda foto.")
        else:
            if len(photos) == 1:
                update.message.reply_text("Por favor cargue la segunda foto.")
            elif len(photos) == 2:
                update.message.reply_text("Por favor cargue la tercera foto.")
        context.user_data["current_state"] = target_state
        return target_state
    else:
        # Modificación solicitada: Para fumigaciones, luego de recibir las fotos se pasa a pedir
        # "Ingrese el Nombre y teléfono del encargado:" en lugar de preguntar avisos.
        if service == "Fumigacion":
            update.message.reply_text("Ingrese el Nombre y teléfono del encargado:")
            context.user_data["current_state"] = CONTACT
            return CONTACT
        else:
            update.message.reply_text("Ingrese el Nombre y teléfono del encargado:")
            context.user_data["current_state"] = CONTACT
            return CONTACT

# Funciones para fumigación avisos en otras direcciones
def handle_fum_avisos_menu(update: Update, context: CallbackContext) -> int:
    """Maneja la respuesta al menú de avisos adicionales en fumigación."""
    query = update.callback_query
    query.answer()
    logger.debug("handle_fum_avisos_menu: %s", query.data)
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        query.edit_message_text("¿En qué direcciones? (Separe las direcciones con una coma)")
        context.user_data["current_state"] = FUM_AVISOS_TEXT
        return FUM_AVISOS_TEXT
    else:
        query.edit_message_text("Gracias!")
        return ConversationHandler.END

# Función para limpieza y reparación (continuación)
def get_contact(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    logger.debug("get_contact: %s", text)
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['contact'] = text
    keyboard = [
        [InlineKeyboardButton("Si", callback_data='si'),
         InlineKeyboardButton("No", callback_data='no')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("Entregaste avisos en otras direcciones?", reply_markup=reply_markup)
    context.user_data["current_state"] = AVISOS_MENU
    return AVISOS_MENU

def handle_avisos_menu(update: Update, context: CallbackContext) -> int:
    logger.debug("handle_avisos_menu invoked.")
    if update.message and update.message.text:
        if update.message.text.lower().replace("á", "a") == "atras":
            return back_handler(update, context)
    query = update.callback_query
    query.answer()
    logger.debug("handle_avisos_menu callback data: %s", query.data)
    if query.data.lower() == "back":
        return back_handler(update, context)
    if query.data.lower() == "si":
        context.bot.send_message(chat_id=update.effective_chat.id, text="Indique qué direcciones (separadas por una coma):")
        context.user_data["current_state"] = AVISOS_TEXT
        return AVISOS_TEXT
    else:
        context.bot.send_message(chat_id=update.effective_chat.id, text="Gracias!")
        send_email(context.user_data, update, context)
        return ConversationHandler.END

def get_aviso_address(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    logger.debug("get_aviso_address: %s", text)
    if text.lower().replace("á", "a") == "atras":
        return back_handler(update, context)
    context.user_data['avisos_address'] = text
    send_email(context.user_data, update, context)
    update.message.reply_text("Gracias!")
    return ConversationHandler.END

# =============================================================================
# CONFIGURACIÓN DEL CONVERSATION HANDLER Y DEL BOT
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
            # Rama de Fumigación
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
            # Rama de Limpieza y Reparación
            TANK_TYPE: [
                CallbackQueryHandler(handle_tank_type),
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)
            ],
            REPAIR_FIRST: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_repair_first)
            ],
            ASK_SECOND: [
                CallbackQueryHandler(handle_ask_second),
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler)
            ],
            REPAIR_SECOND: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_repair_second)
            ],
            ASK_THIRD: [
                CallbackQueryHandler(handle_ask_third),
                MessageHandler(Filters.text & ~Filters.command, lambda u, c: back_handler(u, c))  # fallback
            ],
            REPAIR_THIRD: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_repair_third)
            ],
            PHOTOS: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.photo, handle_photos),
                MessageHandler(Filters.text & ~Filters.command, handle_photos)
            ],
            CONTACT: [
                MessageHandler(Filters.regex("(?i)^(atr[aá]s)$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_contact)
            ],
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
