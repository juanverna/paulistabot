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
# Se definen los estados en orden de flujo.
# (Se añadieron estados nuevos para la funcionalidad de “Atrás”)
# =============================================================================
(CODE, ORDER, ADDRESS, SERVICE, FUMIGATION, 
 REPAIR_CATEGORY, REPAIR_DETAIL, TAPA_MEDIDAS, 
 FOTO_TANQUE, FOTO_FICHA, FOTO_ORDEN, NOTICES, 
 CONTACT, AVISOS_MENU, AVISOS_TEXT) = range(15)

# =============================================================================
# DICTIONARIO PARA NAVEGACIÓN “ATRÁS”
# Cada estado (excepto CODE) tiene un estado anterior asignado.
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
Encargado y teléfono: {data.get('contact', 'N/A')}
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
    Si el usuario envía el mensaje "Atrás" (o presiona el botón correspondiente),
    se retorna el estado anterior según el diccionario BACK_MAP.
    """
    # Se detecta si es un callback query o un mensaje de texto
    if update.callback_query:
        update.callback_query.answer()
    previous_state = BACK_MAP.get(context.user_data.get("current_state"))
    if previous_state is None:
        # No se puede retroceder (por ejemplo, en el primer paso)
        if update.callback_query:
            update.callback_query.edit_message_text("No puedes retroceder más.")
        else:
            update.message.reply_text("No puedes retroceder más.")
        return context.user_data.get("current_state", CODE)
    else:
        # Informamos al usuario y devolvemos el estado anterior
        text = "Retrocediendo al paso anterior..."
        if update.callback_query:
            update.callback_query.edit_message_text(text)
        else:
            update.message.reply_text(text)
        return previous_state

def add_back_button(keyboard: list) -> list:
    """
    Función auxiliar: recibe una lista de botones (o de filas de botones)
    y añade una fila extra con el botón "Atrás".
    """
    # Se agrega una fila con el botón "Atrás"
    keyboard.append([InlineKeyboardButton("Atrás", callback_data="back")])
    return keyboard

# =============================================================================
# FUNCIONES DEL FLUJO DE CONVERSACIÓN
# =============================================================================
def start(update: Update, context: CallbackContext) -> int:
    update.message.reply_text("¡Hola! Inserte su código:")
    context.user_data["current_state"] = CODE
    return CODE

def get_code(update: Update, context: CallbackContext) -> int:
    context.user_data['code'] = update.message.text
    update.message.reply_text("Escriba el número de la orden de trabajo:\n(O escriba 'Atrás' para volver)")
    context.user_data["current_state"] = ORDER
    return ORDER

def get_order(update: Update, context: CallbackContext) -> int:
    if update.message.text.lower() == "atrás":
        return back_handler(update, context)
    context.user_data['order'] = update.message.text
    update.message.reply_text("Escriba la dirección:\n(O escriba 'Atrás' para volver)")
    context.user_data["current_state"] = ADDRESS
    return ADDRESS

def get_address(update: Update, context: CallbackContext) -> int:
    if update.message.text.lower() == "atrás":
        return back_handler(update, context)
    context.user_data['address'] = update.message.text
    # Se crea el teclado para seleccionar el servicio y se añade el botón "Atrás" manualmente si se desea.
    keyboard = [
        [InlineKeyboardButton("FUMIGACIONES", callback_data='fumigaciones')],
        [InlineKeyboardButton("LIMPIEZA Y REPARACION DE TANQUES", callback_data='limpieza')]
    ]
    # En este caso se usa un menú inline, por lo que se añade un botón "Atrás" a la misma.
    keyboard = add_back_button(keyboard)
    reply_markup = InlineKeyboardMarkup(keyboard)
    update.message.reply_text("¿Qué servicio se realizó?", reply_markup=reply_markup)
    context.user_data["current_state"] = SERVICE
    return SERVICE

def service_selection(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    # Si se presionó el botón "Atrás" (callback_data "back")
    if query.data == "back":
        return back_handler(update, context)
    service_type = query.data
    context.user_data['service'] = service_type
    if service_type == "fumigaciones":
        query.edit_message_text("Servicio seleccionado: Fumigaciones\n¿Qué unidades contienen bichos?\n(Puede escribir 'Atrás' para volver)")
        context.user_data["current_state"] = FUMIGATION
        return FUMIGATION
    else:
        query.edit_message_text("Servicio seleccionado: Limpieza y Reparación de Tanques")
        keyboard = [
            [InlineKeyboardButton("CISTERNA", callback_data='cisterna')],
            [InlineKeyboardButton("RESERVA", callback_data='reserva')],
            [InlineKeyboardButton("INTERMEDIARIO", callback_data='intermediario')]
        ]
        keyboard = add_back_button(keyboard)
        reply_markup = InlineKeyboardMarkup(keyboard)
        query.message.reply_text("Seleccione la categoría de reparación:", reply_markup=reply_markup)
        context.user_data["current_state"] = REPAIR_CATEGORY
        return REPAIR_CATEGORY

def fumigation_data(update: Update, context: CallbackContext) -> int:
    if update.message.text.lower() == "atrás":
        return back_handler(update, context)
    context.user_data['fumigated_units'] = update.message.text
    update.message.reply_text("Marque las observaciones para la próxima visita:\n(O escriba 'Atrás' para volver)")
    context.user_data["current_state"] = NOTICES
    return NOTICES

def handle_repair_category(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data == "back":
        return back_handler(update, context)
    category = query.data  # 'cisterna', 'reserva' o 'intermediario'
    context.user_data['repair_category'] = category.capitalize()
    if category == 'cisterna':
        keyboard = [
            [InlineKeyboardButton("TITCEA", callback_data="TITCEA"),
             InlineKeyboardButton("TITCC", callback_data="TITCC")],
            [InlineKeyboardButton("TATCEA", callback_data="TATCEA"),
             InlineKeyboardButton("TATCC", callback_data="TATCC")],
            [InlineKeyboardButton("MATCEA", callback_data="MATCEA"),
             InlineKeyboardButton("MATCC", callback_data="MATCC")],
            [InlineKeyboardButton("TMTCEA", callback_data="TMTCEA"),
             InlineKeyboardButton("TMTCC", callback_data="TMTCC")]
        ]
    elif category == 'reserva':
        keyboard = [
            [InlineKeyboardButton("TITREA", callback_data="TITREA"),
             InlineKeyboardButton("TITRC", callback_data="TITRC")],
            [InlineKeyboardButton("TATREA", callback_data="TATREA"),
             InlineKeyboardButton("TATRC", callback_data="TATRC")],
            [InlineKeyboardButton("MATREA", callback_data="MATREA"),
             InlineKeyboardButton("MATRC", callback_data="MATRC")],
            [InlineKeyboardButton("TMTREA", callback_data="TMTREA"),
             InlineKeyboardButton("TMTRC", callback_data="TMTRC")]
        ]
    elif category == 'intermediario':
        keyboard = [
            [InlineKeyboardButton("TITHEA", callback_data="TITHEA"),
             InlineKeyboardButton("TITHC", callback_data="TITHC")],
            [InlineKeyboardButton("TATHEA", callback_data="TATHEA"),
             InlineKeyboardButton("TATHC", callback_data="TATHC")],
            [InlineKeyboardButton("MATHEA", callback_data="MATHEA"),
             InlineKeyboardButton("MATHC", callback_data="MATHC")],
            [InlineKeyboardButton("TMTHEA", callback_data="TMTHEA"),
             InlineKeyboardButton("TMTHC", callback_data="TMTHC")]
        ]
    else:
        query.edit_message_text("Opción no válida.")
        return ConversationHandler.END

    keyboard = add_back_button(keyboard)
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(f"Categoría seleccionada: {category.capitalize()}\nAhora seleccione el detalle de reparación:", reply_markup=reply_markup)
    context.user_data["current_state"] = REPAIR_DETAIL
    return REPAIR_DETAIL

def handle_repair_detail(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    query.answer()
    if query.data == "back":
        return back_handler(update, context)
    repair_detail = query.data
    context.user_data['repair_detail'] = repair_detail
    query.edit_message_text(f"Detalle seleccionado: {repair_detail}")
    query.message.reply_text("Indique tipo de tapa y medidas:\n(O escriba 'Atrás' para volver)")
    context.user_data["current_state"] = TAPA_MEDIDAS
    return TAPA_MEDIDAS

def get_tapa_medidas(update: Update, context: CallbackContext) -> int:
    if update.message.text.lower() == "atrás":
        return back_handler(update, context)
    context.user_data['tapa_medidas'] = update.message.text
    update.message.reply_text("Por favor, envíe una foto del tanque:\n(O escriba 'Atrás' para volver)")
    context.user_data["current_state"] = FOTO_TANQUE
    return FOTO_TANQUE
