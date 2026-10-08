import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import *
from bot.utils.helpers import apply_bold_keywords

logger = logging.getLogger(__name__)


# =============================================================================
# Stack de estados (navegación hacia atrás)
# =============================================================================
# Cada paso se apila junto con el tanque en el que estaba (user_data["tanque_actual"]): "atrás"
# desde la medida de la Reserva 2 vuelve a las sugerencias de la Cisterna, en la Cisterna.
def push_state(context: CallbackContext, state: int) -> None:
    ud = context.user_data
    stack = ud.setdefault("state_stack", [])
    tanques = ud.setdefault("stack_tanques", [])
    tanques.extend([None] * (len(stack) - len(tanques)))
    stack.append(state)
    tanques.append(ud.get("tanque_actual"))


def pop_state(context: CallbackContext):
    ud = context.user_data
    stack = ud.get("state_stack", [])
    if not stack:
        return None
    tanques = ud.get("stack_tanques", [])
    if len(tanques) == len(stack):
        tanque = tanques.pop()
        if tanque:
            ud["tanque_actual"] = tanque
    return stack.pop()


# =============================================================================
# Botón ATRAS: va en todas las preguntas (callback "back")
# =============================================================================
def teclado_atras(filas: list = None) -> InlineKeyboardMarkup:
    """Los botones de la pregunta (si tiene) más una fila con ATRAS."""
    return InlineKeyboardMarkup((filas or []) + [[InlineKeyboardButton("⬅️ ATRAS", callback_data="back")]])


def atras_boton(update: Update, context: CallbackContext) -> int:
    """ATRAS tocado en una pregunta cuyo paso no maneja el botón él mismo (fallback de la conversación)."""
    query = update.callback_query
    query.answer()
    try:
        query.edit_message_reply_markup(reply_markup=None)
    except Exception:  # el mensaje ya no tenía botones o es muy viejo: no importa
        pass
    return back_handler(update, context)


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


# =============================================================================
# "Modificar algo" del resumen final (final_summary.py)
# =============================================================================
_EN_CURSO = ("reparaciones_en_curso", "rep_fotos", "litros_pendiente")


def terminar_edicion(update: Update, context: CallbackContext):
    """
    Si se está modificando un campo desde el resumen final, vuelve al resumen.
    None si no se está modificando nada (el paso sigue con el flujo normal).
    """
    if context.user_data.pop("editando", None) is None:
        return None
    for clave in _EN_CURSO:
        context.user_data.pop(clave, None)
    from bot.handlers.final_summary import show_final_summary
    return show_final_summary(update, context)


def back_handler(update: Update, context: CallbackContext) -> int:
    # "Atrás" en la primera pregunta del campo que se está modificando: vuelve al resumen
    # sin borrar el valor (más adentro, ej. de las fotos al menú de reparaciones, es lo normal)
    editando = context.user_data.get("editando")
    if editando is not None and len(context.user_data.get("state_stack", [])) <= editando:
        return terminar_edicion(update, context)
    current = context.user_data.get("current_state")
    if current in CAMPO_DEL_PASO and context.user_data.get("tanque_actual"):
        from bot.services.tanques_reporte import clave
        context.user_data.pop(clave(CAMPO_DEL_PASO[current], context.user_data["tanque_actual"]), None)
    elif current in STATE_KEYS and STATE_KEYS[current]:
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
        # Toda pregunta lleva ATRAS, menos la primera (el código)
        if markup is None and state != CODE:
            markup = teclado_atras()
        context.bot.send_message(
            chat_id=chat_id,
            text=apply_bold_keywords(text),
            reply_markup=markup,
            parse_mode=ParseMode.HTML,
        )

    def back_keyboard(buttons):
        return InlineKeyboardMarkup(buttons + [[InlineKeyboardButton("ATRAS", callback_data="back")]])

    service  = context.user_data.get("service")
    tanque   = context.user_data.get("tanque_actual")

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
    elif state == SCAN_QR:
        send("📷 Por favor, envíe la foto del código QR de la orden:")
    elif state == ORDER:
        send("Por favor, ingrese el número de orden (7 dígitos):")
    elif state == ADDRESS:
        send("Ingrese la dirección:")
    elif state in (START_TIME, END_TIME):
        from bot.handlers import hora
        campo = "inicio" if state == START_TIME else "fin"
        send(hora.texto_pregunta(campo), hora.teclado_horas(campo))
    elif state == FUMIGATION:
        send("¿Qué unidades contienen insectos?")
    elif state == FUM_OBS:
        send("Marque las observaciones para la próxima visita:")
    elif state in (CUERPOS, TANK_TYPE, TANK_CUERPO, TANK_CUBAS, OTRO_TANQUE):
        # Preguntas de los tanques. Al volver a elegir un tanque, el que se había empezado sin
        # cargarle nada se descarta
        from bot.handlers import campos_tanque
        from bot.services import tanques_reporte
        if state in (TANK_TYPE, TANK_CUERPO, TANK_CUBAS):
            tanques_reporte.descartar_vacios(context.user_data)
        {CUERPOS: campos_tanque.preguntar_cuerpos, TANK_TYPE: campos_tanque.preguntar_tipo_tanque,
         TANK_CUERPO: campos_tanque.preguntar_cuerpo_tanque, TANK_CUBAS: campos_tanque.preguntar_cubas,
         OTRO_TANQUE: campos_tanque.preguntar_otro_tanque}[state](update, context)
    elif state in CAMPO_DEL_PASO:
        # Pasos de cada tanque: la misma pregunta que la primera vez, del tanque actual
        from bot.handlers import campos_tanque
        campos_tanque.preguntar_paso(update, context, state)
    elif state == REPAIR_PHOTOS:
        # Se vuelve acá con "atrás" desde sugerencias
        from bot.handlers.fotos_reparaciones import reanudar_manual
        reanudar_manual(update, context, tanque)
    elif state == CONTACT:
        from bot.handlers import campos_tanque
        campos_tanque.preguntar_contacto(update, context)
    elif state == CONTACT_PHONE:
        from bot.handlers import campos_tanque
        campos_tanque.preguntar_telefono(update, context)
    elif state == AVISOS_ADDRESS:
        send("Indique dirección/es donde se entregaron avisos:")
    elif state == PHOTOS:
        if service == "Fumigaciones":
            send("Adjunte fotos de ORDEN DE TRABAJO, LISTADO y PORTERO ELECTRICO:")
        elif service == "Avisos":
            send("Adjunte las fotos de los avisos junto a la chapa del edificio.\nSi terminó, escriba 'Listo'.")
        else:
            send("Adjunte fotos de ORDEN DE TRABAJO, FICHA y TANQUES.\nSi terminó, escriba 'Listo'.")
