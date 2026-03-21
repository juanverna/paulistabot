import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import *
from bot.utils.helpers import apply_bold_keywords

logger = logging.getLogger(__name__)


# =============================================================================
# Stack de estados (navegación hacia atrás)
# =============================================================================
def push_state(context: CallbackContext, state: int) -> None:
    context.user_data.setdefault("state_stack", []).append(state)

def pop_state(context: CallbackContext):
    stack = context.user_data.get("state_stack", [])
    return stack.pop() if stack else None


# =============================================================================
# Comandos especiales
# =============================================================================
def check_special_commands(text: str, update: Update, context: CallbackContext) -> bool:
    if "terminar" in text.lower().replace("á", "a"):
        context.user_data.clear()
        update.message.reply_text("Formulario cancelado. Escribí 'Hola' para empezar de nuevo.")
        return True
    return False


# =============================================================================
# Inicio y retroceso
# =============================================================================
def start_conversation(update: Update, context: CallbackContext) -> int:
    context.user_data.clear()
    context.user_data["state_stack"] = []
    update.message.reply_text(
        apply_bold_keywords("¡Hola! Inserte su código (solo números):"),
        parse_mode=ParseMode.HTML,
    )
    context.user_data["current_state"] = CODE
    return CODE


def back_handler(update: Update, context: CallbackContext) -> int:
    current = context.user_data.get("current_state")
    if current in STATE_KEYS and STATE_KEYS[current]:
        context.user_data.pop(STATE_KEYS[current], None)
    prev = pop_state(context) or CODE
    context.user_data["current_state"] = prev
    re_ask(prev, update, context)
    return prev


# =============================================================================
# Re-preguntar según estado
# =============================================================================
def re_ask(state: int, update: Update, context: CallbackContext) -> None:
    chat_id = update.effective_chat.id

    def send(text, markup=None):
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(text),
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )

    def si_no_keyboard():
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("Si", callback_data="si"),
             InlineKeyboardButton("No", callback_data="no")],
            [InlineKeyboardButton("ATRAS", callback_data="back")],
        ])

    def back_keyboard(buttons):
        return InlineKeyboardMarkup(buttons + [[InlineKeyboardButton("ATRAS", callback_data="back")]])

    selected = context.user_data.get("selected_category", "").capitalize()
    alt1     = context.user_data.get("alternative_1", "").capitalize()
    alt2     = context.user_data.get("alternative_2", "").capitalize()
    service  = context.user_data.get("service")

    if state == CODE:
        send("¡Hola! Inserte su código (solo números):")
    elif state == SERVICE:
        kb = back_keyboard([
            [InlineKeyboardButton("Fumigaciones",                    callback_data="Fumigaciones"),
             InlineKeyboardButton("Limpieza y Reparacion de Tanques", callback_data="Limpieza y Reparacion de Tanques")],
            [InlineKeyboardButton("Presupuestos", callback_data="Presupuestos"),
             InlineKeyboardButton("Avisos",        callback_data="Avisos")],
        ])
        send("¿Qué servicio se realizó?", kb)
    elif state == ORDER:
        send("Por favor, ingrese el número de orden (7 dígitos):")
    elif state == ADDRESS:
        send("Ingrese la dirección:")
    elif state == START_TIME:
        send("¿A qué hora empezaste el trabajo? (HH:MM)")
    elif state == END_TIME:
        send("¿A qué hora terminaste el trabajo? (HH:MM)")
    elif state == FUMIGATION:
        send("¿Qué unidades contienen insectos?")
    elif state == FUM_OBS:
        send("Marque las observaciones para la próxima visita:")
    elif state == TANK_TYPE:
        kb = back_keyboard([
            [InlineKeyboardButton("CISTERNA",      callback_data="CISTERNA"),
             InlineKeyboardButton("RESERVA",       callback_data="RESERVA"),
             InlineKeyboardButton("INTERMEDIARIO", callback_data="INTERMEDIARIO")],
        ])
        send("Seleccione el tipo de tanque:", kb)
    elif state == MEASURE_MAIN:
        send(f"Indique la medida del tanque de {selected} (ALTO, ANCHO, PROFUNDO):")
    elif state == TAPAS_INSPECCION_MAIN:
        send("Indique TAPAS INSPECCIÓN (30 40 50 60 80):")
    elif state == TAPAS_ACCESO_MAIN:
        send("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):")
    elif state == SEALING_MAIN:
        send(f"Indique cómo selló el tanque de {selected} (EJ: masilla, burlete):")
    elif state == REPAIR_MAIN:
        send(f"Indique reparaciones a realizar para {selected}:")
    elif state == SUGGESTIONS_MAIN:
        send(f"Indique sugerencias p/ la próx limpieza para {selected}:")
    elif state == ASK_SECOND:
        send(f"¿Quiere comentar algo sobre {alt1}?", si_no_keyboard())
    elif state == MEASURE_ALT1:
        send(f"Indique la medida del tanque para {alt1} (ALTO, ANCHO, PROFUNDO):")
    elif state == TAPAS_INSPECCION_ALT1:
        send("Indique TAPAS INSPECCIÓN (30 40 50 60 80):")
    elif state == TAPAS_ACCESO_ALT1:
        send("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):")
    elif state == SEALING_ALT1:
        send(f"Indique cómo selló el tanque de {alt1}:")
    elif state == REPAIR_ALT1:
        send(f"Indique reparaciones a realizar para {alt1}:")
    elif state == SUGGESTIONS_ALT1:
        send(f"Indique sugerencias p/ la próx limpieza para {alt1}:")
    elif state == ASK_THIRD:
        send(f"¿Quiere comentar algo sobre {alt2}?", si_no_keyboard())
    elif state == MEASURE_ALT2:
        send(f"Indique la medida del tanque para {alt2} (ALTO, ANCHO, PROFUNDO):")
    elif state == TAPAS_INSPECCION_ALT2:
        send("Indique TAPAS INSPECCIÓN (30 40 50 60 80):")
    elif state == TAPAS_ACCESO_ALT2:
        send("Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):")
    elif state == SEALING_ALT2:
        send(f"Indique cómo selló el tanque de {alt2}:")
    elif state == REPAIR_ALT2:
        send(f"Indique reparaciones a realizar para {alt2}:")
    elif state == SUGGESTIONS_ALT2:
        send(f"Indique sugerencias p/ la próx limpieza para {alt2}:")
    elif state == CONTACT:
        send("Ingrese el nombre y teléfono del encargado:")
    elif state == AVISOS_ADDRESS:
        send("Indique dirección/es donde se entregaron avisos:")
    elif state == PHOTOS:
        if service == "Fumigaciones":
            send("Adjunte fotos de ORDEN DE TRABAJO, LISTADO y PORTERO ELECTRICO:")
        elif service == "Avisos":
            send("Adjunte las fotos de los avisos junto a la chapa del edificio.\nSi terminó, escriba 'Listo'.")
        else:
            send("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES.\nSi terminó, escriba 'Listo'.")
