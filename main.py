from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (Updater, MessageHandler, Filters, CallbackQueryHandler,
                          ConversationHandler, CallbackContext)
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
import os
import io

# =============================================================================
# ESTADOS DEL CONVERSATION HANDLER
# =============================================================================
(CODE, ORDER, ADDRESS, SERVICE, FUMIGATION, 
 REPAIR_CATEGORY, REPAIR_DETAIL, TAPA_MEDIDAS, 
 FOTO_TANQUE, FOTO_FICHA, FOTO_ORDEN, NOTICES, 
 CONTACT, AVISOS_MENU, AVISOS_TEXT) = range(15)

# =============================================================================
# DICTIONARIO PARA NAVEGACIÓN “ATRÁS”
# Cada estado (excepto CODE) tiene asignado su estado anterior.
# =============================================================================
BACK_MAP = {
    ORDER: CODE,
    ADDRESS: ORDER,
    SERVICE: ADDRESS,
    FUMIGATION: SERVICE,
    REPAIR_CATEGORY: SERVICE,
    REPAIR_DETAIL: REPAIR_CATEGORY,
    TAPA_MEDIDAS: REPAIR_DETAIL,
    FOTO_TANQUE: TAPA_MEDIDAS,
    FOTO_FICHA: FOTO_TANQUE,
    FOTO_ORDEN: FOTO_FICHA,
    NOTICES: FOTO_ORDEN,
    CONTACT: NOTICES,
    AVISOS_MENU: CONTACT,
    AVISOS_TEXT: AVISOS_MENU
}

# =============================================================================
# CONFIGURACIÓN DEL CORREO Y DEL BOT
# =============================================================================
RECIPIENT_EMAIL = "paulistaser@gmail.com"
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "paulistaser@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "zexc teqn kytt tftx")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7650702859:AAHZfGk5ff5bfPbV3VzMK-XPKOkerjliM8M")

# =============================================================================
# FUNCIONES DE ENVÍO DE CORREO
# =============================================================================
def send_email(data, update: Update, context: CallbackContext):
    """Envía un correo con la información recopilada, adjuntando imágenes si están disponibles."""
    msg = MIMEMultipart()
    msg['Subject'] = "Reporte de servicio"
    msg['From'] = EMAIL_ADDRESS
    msg['To'] = RECIPIENT_EMAIL

    body = f"""Formulario completado:
Código de empleado: {data.get('code', 'N/A')}
Orden de trabajo: {data.get('order', 'N/A')}
Dirección: {data.get('address', 'N/A')}
Servicio: {data.get('service', 'N/A')}
Categoría de reparación: {data.get('repair_category', 'N/A')}
Detalle de reparación: {data.get('repair_detail', 'N/A')}
Tipo de tapa y medidas: {data.get('tapa_medidas', 'N/A')}
Observaciones: {data.get('notices', 'N/A')}
Nombre y teléfono del encargado: {data.get('contact', 'N/A')}
Avisos entregados en: {data.get('avisos_address', 'N/A')}
"""
    msg.attach(MIMEText(body, 'plain'))

    def attach_image(file_id, filename):
        try:
            file_obj = context.bot.get_file(file_id)
            bio = io.BytesIO()
            file_obj.download(out=bio)
            bio.seek(0)
            image = MIMEImage(bio.read())
            image.add_header('Content-Disposition', 'attachment', filename=filename)
            msg.attach(image)
        except Exception as e:
            print(f"Error al adjuntar imagen {filename}: {e}")

    if 'foto_tanque' in data:
        attach_image(data['foto_tanque'], "foto_tanque.jpg")
    if 'foto_ficha' in data:
        attach_image(data['foto_ficha'], "foto_ficha.jpg")
    if 'foto_orden' in data:
        attach_image(data['foto_orden'], "foto_orden.jpg")

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
            server.sendmail(EMAIL_ADDRESS, RECIPIENT_EMAIL, msg.as_string())
    except Exception as e:
        print(f"Error sending email: {e}")

# =============================================================================
# FUNCIONES DE RETROCESO (“ATRÁS”)
# =============================================================================
def back_handler(update: Update, context: CallbackContext) -> int:
    """
    Retrocede al estado anterior según BACK_MAP y reenvía la pregunta correspondiente.
    Se detecta si el usuario escribió "atras" (en cualquiera de sus variantes).
    """
    if update.callback_query:
        update.callback_query.answer()
    previous_state = BACK_MAP.get(context.user_data.get("current_state"))
    if previous_state is None:
        if update.callback_query:
            update.callback_query.edit_message_text("No puedes retroceder más.")
        else:
            update.message.reply_text("No puedes retroceder más.")
        return context.user_data.get("current_state", CODE)
    else:
        context.user_data["current_state"] = previous_state
        re_ask(previous_state, update, context)
        return previous_state

def re_ask(state: int, update: Update, context: CallbackContext):
    """
    Reenvía la pregunta correspondiente al estado indicado, mostrando botones si corresponde.
    """
    chat_id = update.effective_chat.id
    if state == CODE:
        context.bot.send_message(chat_id=chat_id, text="¡Hola! Inserte su código:")
    elif state == ORDER:
        context.bot.send_message(chat_id=chat_id, text="Escriba el número de la orden de trabajo:")
    elif state == ADDRESS:
        context.bot.send_message(chat_id=chat_id, text="Escriba la dirección:")
    elif state == SERVICE:
        keyboard = [
            [InlineKeyboardButton("FUMIGACIONES", callback_data='fumigaciones')],
            [InlineKeyboardButton("LIMPIEZA Y REPARACION DE TANQUES", callback_data='limpieza')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id, text="¿Qué servicio se realizó?", reply_markup=reply_markup)
    elif state == FUMIGATION:
        context.bot.send_message(chat_id=chat_id, text="¿Qué unidades contienen insectos?")
    elif state == REPAIR_CATEGORY:
        keyboard = [
            [InlineKeyboardButton("CISTERNA", callback_data='cisterna')],
            [InlineKeyboardButton("RESERVA", callback_data='reserva')],
            [InlineKeyboardButton("INTERMEDIARIO", callback_data='intermediario')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(chat_id=chat_id, text="Seleccione la categoría de reparación:", reply_markup=reply_markup)
    elif state == REPAIR_DETAIL:
        context.bot.send_message(chat_id=chat_id, text="Seleccione el detalle de reparación (vuelva a elegir):")
    elif state == TAPA_MEDIDAS:
        context.bot.send_message(chat_id=chat_id, text="Indique tipo de tapa y medidas:")
    elif state == FOTO_TANQUE:
        context.bot.send_message(chat_id=chat_id, text="Adjunte foto de tanque:")
    elif state == FOTO_FICHA:
        context.bot.send_message(chat_id=chat_id, text="Adjunte foto de ficha:")
    elif state == FOTO_ORDEN:
        context.bot.send_message(chat_id=chat_id, text="Adjunte foto de orden de trabajo:")
    elif state == NOTICES:
        context.bot.send_message(chat_id=chat_id, text="Marque las observaciones para la próxima visita:")
    elif state == CONTACT:
        context.bot.send_message(chat_id=chat_id, text="Ingrese el Nombre y teléfono del encargado:")
    elif state == AVISOS_MENU:
        keyboard = [
            [InlineKeyboardButton("Si", callback_data='si'),
             InlineKeyboardButton("No", callback_data='no')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
