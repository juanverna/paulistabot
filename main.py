
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
                          ConversationHandler, CallbackContext, CommandHandler)
import cv2
import numpy as np
from PIL import Image
from dotenv import load_dotenv

# Cargar variables de entorno
load_dotenv()

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
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "7650702859:AAHZfGk5ff5bfPbV3VzMK-XPKOkerjliM8M")
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "botpaulista25@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "fxvq jgue rkia gmtg")

# =============================================================================
# Definición de estados
# =============================================================================
(SCAN_QR, CODE, SERVICE, ORDER, ADDRESS, START_TIME, END_TIME, FUMIGATION, FUM_OBS, FUM_PHOTOS, CONTACT,
 TANK_TYPE, MEASURE_MAIN, TAPAS_INSPECCION_MAIN, TAPAS_ACCESO_MAIN, SEALING_MAIN, REPAIR_MAIN,
 SUGGESTIONS_MAIN, ASK_SECOND, MEASURE_ALT1, TAPAS_INSPECCION_ALT1, TAPAS_ACCESO_ALT1, SEALING_ALT1,
 REPAIR_ALT1, SUGGESTIONS_ALT1, ASK_THIRD, MEASURE_ALT2, TAPAS_INSPECCION_ALT2,
 TAPAS_ACCESO_ALT2, SEALING_ALT2, REPAIR_ALT2, SUGGESTIONS_ALT2, PHOTOS, AVISOS_CODE,
 AVISOS_ADDRESS, AVISOS_PHOTOS) = range(36)

# =============================================================================
# Mapeo de estados a claves en user_data para eliminar respuesta actual al "atras"
# =============================================================================
STATE_KEYS = {
    CODE: "code",
    ORDER: "order",
    ADDRESS: "address",
    START_TIME: "start_time",
    END_TIME: "end_time",
    FUMIGATION: "fumigated_units",
    FUM_OBS: "fum_obs",
    MEASURE_MAIN: "measure_main",
    TAPAS_INSPECCION_MAIN: "tapas_inspeccion_main",
    TAPAS_ACCESO_MAIN: "tapas_acceso_main",
    SEALING_MAIN: "sealing_main",
    SUGGESTIONS_MAIN: "suggestions",
    REPAIR_MAIN: "repairs",
    MEASURE_ALT1: "measure_alt1",
    TAPAS_INSPECCION_ALT1: "tapas_inspeccion_alt1",
    TAPAS_ACCESO_ALT1: "tapas_acceso_alt1",
    SEALING_ALT1: "sealing_alt1",
    SUGGESTIONS_ALT1: "suggestions_alt1",
    REPAIR_ALT1: "repair_alt1",
    MEASURE_ALT2: "measure_alt2",
    TAPAS_INSPECCION_ALT2: "tapas_inspeccion_alt2",
    TAPAS_ACCESO_ALT2: "tapas_acceso_alt2",
    SEALING_ALT2: "sealing_alt2",
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
# Función para escanear QR
# =============================================================================
def scan_qr(update: Update, context: CallbackContext) -> int:
    if not update.message.photo:
        update.message.reply_text(
            apply_bold_keywords("Por favor, envíe una foto del código QR para continuar."),
            parse_mode=ParseMode.HTML
        )
        return SCAN_QR
    
    try:
        # Descargar la foto del QR
        file = update.message.photo[-1].get_file()
        bio = BytesIO()
        file.download(out=bio)
        bio.seek(0)
        
        logger.info("Imagen del QR descargada exitosamente")
        
        # Decodificar la imagen con OpenCV
        img = Image.open(bio)
        img_array = np.array(img)
        
        logger.info(f"Imagen procesada: dimensiones {img_array.shape}")
        
        # Convertir a escala de grises si es necesario
        if len(img_array.shape) == 3:
            gray = cv2.cvtColor(img_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = img_array
        
        # Crear detector QR
        qr_detector = cv2.QRCodeDetector()
        
        # Lista de métodos de procesamiento para intentar
        processing_methods = []
        
        # Método 1: Imagen original
        processing_methods.append(("original", gray))
        
        # Método 2: Con filtro gaussiano
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        processing_methods.append(("blurred", blurred))
        
        # Método 3: Umbralización adaptativa
        thresh = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
        processing_methods.append(("adaptive_thresh", thresh))
        
        # Método 4: Umbralización simple
        _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
        processing_methods.append(("binary_thresh", binary))
        
        # Método 5: Imagen invertida
        inverted = cv2.bitwise_not(gray)
        processing_methods.append(("inverted", inverted))
        
        # Método 6: Redimensionada si es muy grande
        height, width = gray.shape
        if width > 1000 or height > 1000:
            scale = 800 / max(width, height)
            new_width = int(width * scale)
            new_height = int(height * scale)
            resized = cv2.resize(gray, (new_width, new_height))
            processing_methods.append(("resized", resized))
        
        # Intentar con cada método
        data = None
        successful_method = None
        
        for method_name, processed_img in processing_methods:
            try:
                logger.info(f"Intentando método: {method_name}")
                detected_data, vertices, _ = qr_detector.detectAndDecode(processed_img)
                
                if detected_data and detected_data.strip():
                    data = detected_data.strip()
                    successful_method = method_name
                    logger.info(f"QR detectado exitosamente con método '{method_name}': {data}")
                    break
                else:
                    logger.debug(f"Método '{method_name}' no detectó QR válido")
                    
            except Exception as method_error:
                logger.warning(f"Error en método '{method_name}': {method_error}")
                continue
        
        if not data:
            logger.warning("No se pudo decodificar el código QR con ningún método")
            update.message.reply_text(
                apply_bold_keywords("No pude leer el código QR. Por favor, intente de nuevo con una imagen más clara, mejor iluminada, o tome la foto desde una distancia diferente."),
                parse_mode=ParseMode.HTML
            )
            return SCAN_QR
        
        logger.info(f"QR decodificado exitosamente con método '{successful_method}': {data}")
        
        # Extraer y separar el payload
        payload = data.strip()
        logger.info(f"Payload completo del QR: '{payload}'")
        logger.info(f"Longitud del payload: {len(payload)} caracteres")
        
        # Para casos de prueba, si el QR contiene una URL o texto simple, mostrar mensaje específico
        if payload.startswith(('http://', 'https://', 'www.')):
            logger.info("QR detectado contiene una URL")
            update.message.reply_text(
                apply_bold_keywords("El código QR detectado contiene una URL, pero se esperan datos de orden de trabajo separados por '|'. Por favor, use el código QR correcto para órdenes de trabajo."),
                parse_mode=ParseMode.HTML
            )
            return SCAN_QR
        
        # Detectar QR con solo números (probablemente QR de prueba o incorrecto)
        if payload.isdigit() and len(payload) <= 5:
            logger.info(f"QR detectado contiene solo un número simple: {payload}")
            update.message.reply_text(
                apply_bold_keywords(f"El código QR detectado contiene solo el número '{payload}', pero se esperan datos de orden de trabajo separados por '|'.\n\nEste parece ser un QR de prueba o diferente. Por favor, use el código QR específico de la orden de trabajo que contiene los datos completos."),
                parse_mode=ParseMode.HTML
            )
            return SCAN_QR
        
        # Verificar si el payload contiene pipes para el formato esperado
        if "|" not in payload:
            logger.warning(f"El QR no contiene el formato esperado (sin pipes): '{payload}'")
            logger.info("Caracteres en el payload:")
            for i, char in enumerate(payload):
                logger.info(f"  Posición {i}: '{char}' (ASCII: {ord(char)})")
            
            # Mensaje más específico según el tipo de contenido
            if payload.isdigit():
                error_msg = f"El código QR contiene solo el número '{payload}', pero se esperan datos de orden de trabajo en formato: ORDEN|ADMIN|CODIGO|DIRECCION|FECHA"
            elif len(payload) < 10:
                error_msg = f"El código QR contiene texto muy corto: '{payload}'. Se esperan datos completos de orden de trabajo separados por '|'"
            else:
                error_msg = f"El código QR fue leído correctamente, pero no tiene el formato esperado de orden de trabajo.\n\nContenido detectado: {payload[:50]}{'...' if len(payload) > 50 else ''}\n\nSe esperan datos separados por '|'"
            
            update.message.reply_text(
                apply_bold_keywords(f"{error_msg}\n\n🔍 **Formato esperado:**\nORDEN|ADMINISTRADOR|CODIGO_ADMIN|DIRECCION|FECHA\n\n⚠️ Verifique que está usando el QR correcto de la orden de trabajo."),
                parse_mode=ParseMode.HTML
            )
            return SCAN_QR
        
        # Separar las partes del payload
        parts = payload.split("|")
        logger.info(f"Partes separadas por pipes: {len(parts)} partes")
        for i, part in enumerate(parts):
            logger.info(f"  Parte {i+1}: '{part}' (longitud: {len(part)})")
        
        if len(parts) != 5:
            logger.warning(f"El QR no tiene 5 partes separadas por pipes. Tiene {len(parts)} partes")
            update.message.reply_text(
                apply_bold_keywords(f"El formato del código QR no es válido. Se esperan exactamente 5 campos separados por '|', pero se encontraron {len(parts)} campos.\n\nContenido: {payload}\n\nPor favor, verifique que está usando el código QR correcto para órdenes de trabajo."),
                parse_mode=ParseMode.HTML
            )
            return SCAN_QR
        
        orden, admin, cod_admin, direccion, fecha = parts
        
        # Limpiar espacios en blanco de cada campo
        orden = orden.strip()
        admin = admin.strip()
        cod_admin = cod_admin.strip()
        direccion = direccion.strip()
        fecha = fecha.strip()
        
        # Validar que ningún campo esté vacío
        if not orden or not admin or not cod_admin or not direccion or not fecha:
            logger.warning("Uno o más campos del QR están vacíos")
            empty_fields = []
            if not orden: empty_fields.append("Orden")
            if not admin: empty_fields.append("Administrador") 
            if not cod_admin: empty_fields.append("Código Admin")
            if not direccion: empty_fields.append("Dirección")
            if not fecha: empty_fields.append("Fecha")
            
            update.message.reply_text(
                apply_bold_keywords(f"El código QR tiene campos vacíos: {', '.join(empty_fields)}.\n\nPor favor, verifique que está usando un código QR válido con todos los datos completos."),
                parse_mode=ParseMode.HTML
            )
            return SCAN_QR
        
        # Guardar los datos en user_data
        context.user_data.update({
            "orden_trabajo": orden,
            "administrador": admin,
            "codigo_admin": cod_admin,
            "direccion_qr": direccion,
            "fecha_orden": fecha,
        })
        
        logger.info(f"✅ Datos del QR guardados exitosamente:")
        logger.info(f"  📋 Orden: '{orden}' (longitud: {len(orden)})")
        logger.info(f"  👤 Administrador: '{admin}' (longitud: {len(admin)})")
        logger.info(f"  🔢 Código admin: '{cod_admin}' (longitud: {len(cod_admin)})")
        logger.info(f"  📍 Dirección: '{direccion}' (longitud: {len(direccion)})")
        logger.info(f"  📅 Fecha: '{fecha}' (longitud: {len(fecha)}) - Contiene '/': {'/' in fecha}")
        logger.info(f"  🎯 Servicio: {context.user_data.get('service', 'No definido')}")
        
        # Mostrar datos extraídos para confirmación
        confirmation_text = f"""✅ **Código QR procesado correctamente**

📋 **Datos extraídos:**
• **Orden:** {orden}
• **Administrador:** {admin}
• **Código Admin:** {cod_admin}
• **Dirección:** {direccion}
• **Fecha:** {fecha}

✏️ Ahora inserte su código (solo números):"""

        update.message.reply_text(
            apply_bold_keywords(confirmation_text),
            parse_mode=ParseMode.HTML
        )
        context.user_data["current_state"] = CODE
        return CODE
            
    except Exception as e:
        logger.error("Error general al procesar QR: %s", str(e), exc_info=True)
        update.message.reply_text(
            apply_bold_keywords("❌ Error al procesar el código QR. Por favor, intente de nuevo con una imagen más clara."),
            parse_mode=ParseMode.HTML
        )
        return SCAN_QR

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
    """
    Vuelve a mostrar la pregunta o el menú del estado 'state'.
    De esta manera, al hacer 'ATRAS', el usuario ve nuevamente la pregunta anterior.
    """
    chat_id = update.effective_chat.id

    if state == SCAN_QR:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Por favor, envíe una foto del código QR para comenzar:"),
            parse_mode=ParseMode.HTML
        )
    elif state == CODE:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Inserte su código (solo números):"),
            parse_mode=ParseMode.HTML
        )
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
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif state == ORDER:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Por favor, ingrese el número de orden (7 dígitos):"),
            parse_mode=ParseMode.HTML
        )
    elif state == ADDRESS:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Ingrese la dirección:"),
            parse_mode=ParseMode.HTML
        )
    elif state == START_TIME:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("¿A qué hora empezaste el trabajo?"),
            parse_mode=ParseMode.HTML
        )
    elif state == END_TIME:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("¿A qué hora terminaste el trabajo?"),
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
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif state == MEASURE_MAIN:
        selected = context.user_data.get("selected_category", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(
                f"Indique la medida del tanque de {selected} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"
            ),
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
    elif state == SEALING_MAIN:
        selected = context.user_data.get("selected_category", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(f"Indique como selló el tanque de {selected} (EJ: masilla, burlete, etc):"),
            parse_mode=ParseMode.HTML
        )
    elif state == SUGGESTIONS_MAIN:
        selected = context.user_data.get("selected_category", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(
                f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {selected}:"
            ),
            parse_mode=ParseMode.HTML
        )
    elif state == REPAIR_MAIN:
        selected = context.user_data.get("selected_category", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(
                f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {selected}:"
            ),
            parse_mode=ParseMode.HTML
        )
    elif state == ASK_SECOND:
        alt1 = context.user_data.get("alternative_1", "").capitalize()
        keyboard = [
            [
                InlineKeyboardButton("Si", callback_data='si'),
                InlineKeyboardButton("No", callback_data='no')
            ],
            [InlineKeyboardButton("ATRAS", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(f"¿Quiere comentar algo sobre {alt1}?"),
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif state == MEASURE_ALT1:
        alt1 = context.user_data.get("alternative_1", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(
                f"Indique la medida del tanque para {alt1} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"
            ),
            parse_mode=ParseMode.HTML
        )
    elif state == TAPAS_INSPECCION_ALT1:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Indique TAPAS INSPECCIÓN (30 40 50 60 80):"),
            parse_mode=ParseMode.HTML
        )
    elif state == TAPAS_ACCESO_ALT1:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
            parse_mode=ParseMode.HTML
        )
    elif state == SEALING_ALT1:
        alt1 = context.user_data.get("alternative_1", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(f"Indique como selló el tanque de {alt1} (EJ: masilla, burlete, etc):"),
            parse_mode=ParseMode.HTML
        )
    elif state == SUGGESTIONS_ALT1:
        alt1 = context.user_data.get("alternative_1", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {alt1}:"),
            parse_mode=ParseMode.HTML
        )
    elif state == REPAIR_ALT1:
        alt1 = context.user_data.get("alternative_1", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(
                f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {alt1}:"
            ),
            parse_mode=ParseMode.HTML
        )
    elif state == ASK_THIRD:
        alt2 = context.user_data.get("alternative_2", "").capitalize()
        keyboard = [
            [
                InlineKeyboardButton("Si", callback_data='si'),
                InlineKeyboardButton("No", callback_data='no')
            ],
            [InlineKeyboardButton("ATRAS", callback_data='back')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(f"¿Quiere comentar algo sobre {alt2}?"),
            reply_markup=reply_markup,
            parse_mode=ParseMode.HTML
        )
    elif state == MEASURE_ALT2:
        alt2 = context.user_data.get("alternative_2", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(
                f"Indique la medida del tanque para {alt2} en el siguiente formato:\nALTO, ANCHO, PROFUNDO"
            ),
            parse_mode=ParseMode.HTML
        )
    elif state == TAPAS_INSPECCION_ALT2:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Indique TAPAS INSPECCIÓN (30 40 50 60 80):"),
            parse_mode=ParseMode.HTML
        )
    elif state == TAPAS_ACCESO_ALT2:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
            parse_mode=ParseMode.HTML
        )
    elif state == SEALING_ALT2:
        alt2 = context.user_data.get("alternative_2", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(f"Indique como selló el tanque de {alt2} (EJ: masilla, burlete, etc):"),
            parse_mode=ParseMode.HTML
        )
    elif state == SUGGESTIONS_ALT2:
        alt2 = context.user_data.get("alternative_2", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {alt2}:"),
            parse_mode=ParseMode.HTML
        )
    elif state == REPAIR_ALT2:
        alt2 = context.user_data.get("alternative_2", "").capitalize()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(
                f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {alt2}:"
            ),
            parse_mode=ParseMode.HTML
        )
    elif state == CONTACT:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
            parse_mode=ParseMode.HTML
        )
    elif state == PHOTOS:
        service = context.user_data.get("service")
        if service == "Fumigaciones":
            context.bot.send_message(
                chat_id=chat_id,
                text=apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO:"),
                parse_mode=ParseMode.HTML
            )
        elif service == "Avisos":
            context.bot.send_message(
                chat_id=chat_id,
                text=apply_bold_keywords(
                    "Adjunte las fotos de los avisos junto a la chapa con numeración del edificio:\nSi ha terminado, escriba 'Listo'."
                ),
                parse_mode=ParseMode.HTML
            )
        else:
            context.bot.send_message(
                chat_id=chat_id,
                text=apply_bold_keywords(
                    "Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:\nSi ha terminado, escriba 'Listo'."
                ),
                parse_mode=ParseMode.HTML
            )
    elif state == AVISOS_ADDRESS:
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords("Indique dirección/es donde se entregaron avisos:"),
            parse_mode=ParseMode.HTML
        )

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
            text=apply_bold_keywords("Por favor, envíe una foto del código QR para continuar:"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = SCAN_QR
        return SCAN_QR
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
    update.message.reply_text(
        apply_bold_keywords("¿A qué hora empezaste el trabajo?"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = START_TIME
    return START_TIME

def get_start_time(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['start_time'] = text
    push_state(context, START_TIME)
    update.message.reply_text(
        apply_bold_keywords("¿A qué hora terminaste el trabajo?"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = END_TIME
    return END_TIME

def get_end_time(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['end_time'] = text
    push_state(context, END_TIME)
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
        apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = CONTACT
    return CONTACT

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
        apply_bold_keywords(f"Indique como selló el tanque de {selected} (EJ: masilla, burlete, etc):"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SEALING_MAIN
    return SEALING_MAIN

def get_sealing_main(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['sealing_main'] = text
    push_state(context, SEALING_MAIN)
    selected = context.user_data.get("selected_category", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {selected}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = REPAIR_MAIN
    return REPAIR_MAIN

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
    selected = context.user_data.get("selected_category", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {selected}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SUGGESTIONS_MAIN
    return SUGGESTIONS_MAIN

def get_suggestions_main_after_repair(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['suggestions'] = text
    push_state(context, SUGGESTIONS_MAIN)
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
        apply_bold_keywords("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
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
        apply_bold_keywords(f"Indique como selló el tanque de {alt1} (EJ: masilla, burlete, etc):"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SEALING_ALT1
    return SEALING_ALT1

def get_sealing_alt1(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['sealing_alt1'] = text
    push_state(context, SEALING_ALT1)
    alt1 = context.user_data.get("alternative_1", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {alt1}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = REPAIR_ALT1
    return REPAIR_ALT1

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
    alt1 = context.user_data.get("alternative_1", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {alt1}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SUGGESTIONS_ALT1
    return SUGGESTIONS_ALT1

def get_suggestions_alt1_after_repair(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['suggestions_alt1'] = text
    push_state(context, SUGGESTIONS_ALT1)
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
        apply_bold_keywords("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"),
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
        apply_bold_keywords(f"Indique como selló el tanque de {alt2} (EJ: masilla, burlete, etc):"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SEALING_ALT2
    return SEALING_ALT2

def get_sealing_alt2(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['sealing_alt2'] = text
    push_state(context, SEALING_ALT2)
    alt2 = context.user_data.get("alternative_2", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique reparaciones a realizar (EJ: tapas, revoques, etc) para {alt2}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = REPAIR_ALT2
    return REPAIR_ALT2

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
    alt2 = context.user_data.get("alternative_2", "").capitalize()
    update.message.reply_text(
        apply_bold_keywords(f"Indique sugerencias p/ la próx limpieza (EJ: desagote) para {alt2}:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = SUGGESTIONS_ALT2
    return SUGGESTIONS_ALT2

def get_suggestions_alt2_after_repair(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['suggestions_alt2'] = text
    push_state(context, SUGGESTIONS_ALT2)
    update.message.reply_text(
        apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = CONTACT
    return CONTACT

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
        apply_bold_keywords("¿A qué hora empezaste el trabajo?"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = START_TIME
    return START_TIME

def get_avisos_end_time(update: Update, context: CallbackContext) -> int:
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    context.user_data['end_time'] = text
    push_state(context, END_TIME)
    update.message.reply_text(
        apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
        parse_mode=ParseMode.HTML)
    context.user_data["current_state"] = CONTACT
    return CONTACT

def handle_avisos_photos(update: Update, context: CallbackContext) -> int:
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
        return PHOTOS
    else:
        update.message.reply_text(
            apply_bold_keywords("Por favor, envíe una foto o escriba 'Listo' para continuar."),
            parse_mode=ParseMode.HTML)
        return PHOTOS

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
        context.user_data["current_state"] = CONTACT
        return CONTACT

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
            apply_bold_keywords("Ingrese el Nombre y teléfono del encargado:"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = CONTACT
        return CONTACT
    else:
        context.bot.send_message(
            chat_id=query.message.chat.id,
            text=apply_bold_keywords("Respuesta no reconocida, se asume 'No'."),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = CONTACT
        return CONTACT

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
            return PHOTOS
        photos = context.user_data.get("photos", [])
        file_id = update.message.photo[-1].file_id
        photos.append(file_id)
        context.user_data["photos"] = photos
        if len(photos) < 2:
            update.message.reply_text(
                apply_bold_keywords("Por favor cargue la segunda foto."),
                parse_mode=ParseMode.HTML)
            return PHOTOS
        else:
            send_email(context.user_data, update, context)
            return ConversationHandler.END
    elif service == "Avisos":
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
                    send_email(context.user_data, update, context)
                    return ConversationHandler.END
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
                    send_email(context.user_data, update, context)
                    return ConversationHandler.END
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
    service = context.user_data.get("service")
    if service == "Fumigaciones":
        update.message.reply_text(
            apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO y PORTERO ELECTRICO:"),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = PHOTOS
        return PHOTOS
    elif service == "Avisos":
        update.message.reply_text(
            apply_bold_keywords("Adjunte las fotos de los avisos junto a la chapa con numeración del edificio:\nSi ha terminado, escriba 'Listo'."),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = PHOTOS
        return PHOTOS
    else:
        update.message.reply_text(
            apply_bold_keywords("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES:\nSi ha terminado, escriba 'Listo'."),
            parse_mode=ParseMode.HTML)
        context.user_data["current_state"] = PHOTOS
        return PHOTOS

def send_email(user_data, update: Update, context: CallbackContext):
    service = user_data.get("service", "")
    subject = "Reporte de Servicio: " + service
    lines = []
    
    # Incluir datos del QR solo para fumigaciones
    if service == "Fumigaciones":
        if "orden_trabajo" in user_data:
            lines.append(f"Orden de trabajo (QR): {user_data['orden_trabajo']}")
        if "administrador" in user_data:
            lines.append(f"Administrador (QR): {user_data['administrador']}")
        if "codigo_admin" in user_data:
            lines.append(f"Código de admin (QR): {user_data['codigo_admin']}")
        if "direccion_qr" in user_data:
            lines.append(f"Dirección (QR): {user_data['direccion_qr']}")
        if "fecha_orden" in user_data:
            lines.append(f"Fecha de orden (QR): {user_data['fecha_orden']}")
        lines.append("")  # Línea en blanco para separar datos QR de datos formulario
    
    # Se eliminó la fecha automática según requerimiento
    if "code" in user_data:
        lines.append(f"Código: {user_data['code']}")
    if service == "Avisos":
        if "avisos_address" in user_data:
            lines.append(f"Dirección/es: {user_data['avisos_address']}")
        if "start_time" in user_data:
            lines.append(f"Hora de inicio: {user_data['start_time']}")
        if "end_time" in user_data:
            lines.append(f"Hora de finalización: {user_data['end_time']}")
        if "contact" in user_data:
            lines.append(f"Contacto: {user_data['contact']}")
    else:
        ordered_fields = []
        if service in ["Fumigaciones", "Limpieza y Reparacion de Tanques"]:
            ordered_fields.append(("order", "Número de Orden"))
        ordered_fields.extend([
            ("address", "Dirección"),
            ("start_time", "Hora de inicio"),
            ("end_time", "Hora de finalización"),
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
                ("sealing_main", f"Sellado {selected}"),
                ("repairs", f"Reparaciones {selected}"),
                ("suggestions", f"Sugerencias {selected}"),
                ("measure_alt1", "Medida " + alt1),
                ("tapas_inspeccion_alt1", "Tapas inspección " + alt1),
                ("tapas_acceso_alt1", "Tapas acceso " + alt1),
                ("sealing_alt1", f"Sellado {alt1}"),
                ("repair_alt1", f"Reparaciones {alt1}"),
                ("suggestions_alt1", f"Sugerencias {alt1}"),
                ("measure_alt2", "Medida " + alt2),
                ("tapas_inspeccion_alt2", "Tapas inspección " + alt2),
                ("tapas_acceso_alt2", "Tapas acceso " + alt2),
                ("sealing_alt2", f"Sellado {alt2}"),
                ("repair_alt2", f"Reparaciones {alt2}"),
                ("suggestions_alt2", f"Sugerencias {alt2}")
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
                parse_mode=ParseMode.HTML)
        else:
            context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=apply_bold_keywords("Error al enviar correo."),
                parse_mode=ParseMode.HTML)

def main():
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    dp = updater.dispatcher
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start_conversation),
            MessageHandler(Filters.regex("(?i)^hola$"), start_conversation)
        ],
        states={
            SCAN_QR: [
                MessageHandler(Filters.photo, scan_qr)
            ],
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
            START_TIME: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_start_time)
            ],
            END_TIME: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_end_time)
            ],
            FUMIGATION: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, fumigation_data)
            ],
            FUM_OBS: [
                MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler),
                MessageHandler(Filters.text & ~Filters.command, get_fum_obs)
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
            SEALING_MAIN: [
                MessageHandler(Filters.text & ~Filters.command, get_sealing_main)
            ],
            SUGGESTIONS_MAIN: [
                MessageHandler(Filters.text & ~Filters.command, get_suggestions_main_after_repair)
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
            SEALING_ALT1: [
                MessageHandler(Filters.text & ~Filters.command, get_sealing_alt1)
            ],
            SUGGESTIONS_ALT1: [
                MessageHandler(Filters.text & ~Filters.command, get_suggestions_alt1_after_repair)
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
            SEALING_ALT2: [
                MessageHandler(Filters.text & ~Filters.command, get_sealing_alt2)
            ],
            SUGGESTIONS_ALT2: [
                MessageHandler(Filters.text & ~Filters.command, get_suggestions_alt2_after_repair)
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
