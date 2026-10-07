"""
campos_tanque.py
----------------
Carga manual con formato fijo (ver bot/services/campos.py): medida validada, tapas y sellado
con botones, y el contacto en dos pasos (nombre y teléfono).

Botones (el sufijo y el campo van en el botón: uno de un paso que ya terminó no se toma):
  "tp:<sufijo>:<insp|acceso>:t:<tipo>"     tipo de tapa de acceso (catálogo en services/campos.py)
  "tp:<sufijo>:<campo>:m:<medida>"         medida de esa tapa
  "tp:<sufijo>:<campo>:v:<EA|C>"           entrada de agua o ciego de esa tapa
  "tp:<sufijo>:<campo>:<volver|borrar|listo|no>"
  "se:<sufijo>:<masilla|burlete|silicona|listo|no|otro>"
  "md:<sufijo>:<plastico|cilindrico|acero>" material de un tanque en litros
  "ct:<sin|sintel>"                        sin encargado / sin teléfono
"""

import html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.error import BadRequest
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import *
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import push_state, back_handler, check_special_commands
from bot.services import campos

PASOS = {
    "main": {"tanque": "selected_category", "medida": (MEASURE_MAIN, "measure_main"),
             "insp": (TAPAS_INSPECCION_MAIN, "tapas_inspeccion_main"),
             "acceso": (TAPAS_ACCESO_MAIN, "tapas_acceso_main"),
             "sellado": (SEALING_MAIN, "sealing_main"), "reparaciones": REPAIR_MAIN},
    "alt1": {"tanque": "alternative_1", "medida": (MEASURE_ALT1, "measure_alt1"),
             "insp": (TAPAS_INSPECCION_ALT1, "tapas_inspeccion_alt1"),
             "acceso": (TAPAS_ACCESO_ALT1, "tapas_acceso_alt1"),
             "sellado": (SEALING_ALT1, "sealing_alt1"), "reparaciones": REPAIR_ALT1},
    "alt2": {"tanque": "alternative_2", "medida": (MEASURE_ALT2, "measure_alt2"),
             "insp": (TAPAS_INSPECCION_ALT2, "tapas_inspeccion_alt2"),
             "acceso": (TAPAS_ACCESO_ALT2, "tapas_acceso_alt2"),
             "sellado": (SEALING_ALT2, "sealing_alt2"), "reparaciones": REPAIR_ALT2},
}
NOMBRE_CAMPO = {"insp": "INSPECCIÓN", "acceso": "ACCESO"}


def _tanque(context: CallbackContext, sufijo: str) -> str:
    return context.user_data.get(PASOS[sufijo]["tanque"], "")


def _enviar(update: Update, context: CallbackContext, texto: str, markup=None) -> None:
    """Sirve tanto para mensajes como para botones (en un botón no hay update.message)."""
    context.bot.send_message(chat_id=update.effective_chat.id, text=apply_bold_keywords(texto),
                             reply_markup=markup, parse_mode=ParseMode.HTML)


def _editar(query, texto: str, markup=None) -> None:
    try:
        query.edit_message_text(apply_bold_keywords(texto), reply_markup=markup, parse_mode=ParseMode.HTML)
    except BadRequest as e:  # mismo texto y botones (ej: "Borrar última" sin tapas): no hay nada que cambiar
        if "not modified" not in str(e).lower():
            raise


def _ir(context: CallbackContext, estado: int) -> int:
    context.user_data["current_state"] = estado
    return estado


def _texto_comun(update: Update, context: CallbackContext):
    """'terminar' y 'atrás' escritos. Devuelve el estado siguiente, o None si hay que seguir."""
    text = update.message.text
    if check_special_commands(text, update, context):
        return ConversationHandler.END
    if text.lower().replace("á", "a").strip() == "atras":
        return back_handler(update, context)
    return None


def _boton_vencido(query) -> None:
    query.answer("Ese paso ya terminó.")


def _volver(update: Update, context: CallbackContext) -> int:
    update.callback_query.answer()
    update.callback_query.edit_message_reply_markup(reply_markup=None)
    return back_handler(update, context)


# =============================================================================
# Medida
# =============================================================================
def preguntar_medida(update: Update, context: CallbackContext, sufijo: str) -> int:
    _enviar(update, context, f"📏 Medida del tanque de {_tanque(context, sufijo).capitalize()}: "
                             "alto, ancho y profundo (ej: 1.80 2 1.50 o 180 200 150).")
    return _ir(context, PASOS[sufijo]["medida"][0])


def recibir_medida(sufijo: str):
    estado, clave = PASOS[sufijo]["medida"]

    def handler(update: Update, context: CallbackContext) -> int:
        siguiente = _texto_comun(update, context)
        if siguiente is not None:
            return siguiente
        valor, problema = campos.normalizar_medida(update.message.text)
        if problema:
            update.message.reply_text(f"⚠️ {problema}\n\n{campos.AYUDA_MEDIDA}")
            return estado
        if valor.startswith("LITROS:"):
            litros = valor.split(":", 1)[1]
            context.user_data["litros_pendiente"] = litros
            botones = [[InlineKeyboardButton(nombre.capitalize(), callback_data=f"md:{sufijo}:{clave_m}")
                        for clave_m, nombre in campos.MATERIALES.items()]]
            update.message.reply_text(f"Tanque de {litros} litros. ¿De qué material es?",
                                      reply_markup=InlineKeyboardMarkup(botones))
            return estado
        return _guardar_medida(update, context, sufijo, valor)

    handler.__name__ = f"recibir_medida_{sufijo}"
    return handler


def boton_material(sufijo: str):
    estado = PASOS[sufijo]["medida"][0]

    def handler(update: Update, context: CallbackContext) -> int:
        query = update.callback_query
        _, de, material = (query.data.split(":") + ["", ""])[:3]
        litros = context.user_data.get("litros_pendiente")
        if de != sufijo or material not in campos.MATERIALES or not litros:
            _boton_vencido(query)
            return estado
        query.answer()
        valor = f"{litros} lts ({campos.MATERIALES[material]})"
        query.edit_message_text(f"✅ Medida: {valor}")
        context.user_data.pop("litros_pendiente", None)
        return _guardar_medida(update, context, sufijo, valor)

    handler.__name__ = f"boton_material_{sufijo}"
    return handler


def _guardar_medida(update: Update, context: CallbackContext, sufijo: str, valor: str) -> int:
    estado, clave = PASOS[sufijo]["medida"]
    context.user_data[clave] = valor
    push_state(context, estado)
    if update.message:
        update.message.reply_text(f"✅ Medida: {valor}")
    return preguntar_tapas(update, context, sufijo, "insp")


# =============================================================================
# Tapas de inspección y de acceso
# =============================================================================
def _en_curso(context: CallbackContext, sufijo: str, campo: str) -> dict:
    actual = context.user_data.get("tapas_en_curso")
    if not actual or actual.get("sufijo") != sufijo or actual.get("campo") != campo:
        actual = {"sufijo": sufijo, "campo": campo, "lista": [], "tipo": None, "medida": None}
        context.user_data["tapas_en_curso"] = actual
    return actual


def _tipo_unico(campo: str):
    """Inspección tiene un solo tipo: se va directo a las medidas."""
    tipos = campos.CATALOGO_TAPAS[campo]
    return next(iter(tipos)) if len(tipos) == 1 else None


def _pantalla_tapas(context: CallbackContext, sufijo: str, campo: str):
    """(texto, botones) según lo que se está eligiendo: tipo, medida o entrada de agua/ciego."""
    curso = _en_curso(context, sufijo, campo)
    base = f"tp:{sufijo}:{campo}:"
    lista = curso["lista"]
    cargadas = f"\n\nCargadas: <b>{html.escape(', '.join(lista) if lista else 'ninguna todavía')}</b>"
    titulo = f"🔍 Tapas de <b>{NOMBRE_CAMPO[campo]}</b> de {_tanque(context, sufijo).capitalize()}\n"
    volver = [InlineKeyboardButton("← Volver", callback_data=f"{base}volver")]
    tipo = curso["tipo"] or _tipo_unico(campo)

    if curso["medida"]:
        texto = (f"Tapa de {NOMBRE_CAMPO[campo].lower()} "
                 f"{html.escape(campos.tapa(campo, curso['tipo'], curso['medida']))}: "
                 "¿es de entrada de agua o ciego?")
        return titulo + texto + cargadas, InlineKeyboardMarkup([
            [InlineKeyboardButton("💧 Entrada de agua", callback_data=f"{base}v:EA"),
             InlineKeyboardButton("Ciego", callback_data=f"{base}v:C")], volver])

    if tipo:
        boton, _, medidas = campos.CATALOGO_TAPAS[campo][tipo]
        botones = [InlineKeyboardButton(m, callback_data=f"{base}m:{m}") for m in medidas]
        filas = [botones[i:i + 3] for i in range(0, len(botones), 3)]
        if curso["tipo"] is None:  # inspección: es la pantalla inicial
            texto = ("Tocá la medida de cada tapa, una por una (después te pregunto si es de entrada "
                     "de agua o ciego). Al terminar, tocá Listo.")
            return titulo + texto + cargadas, InlineKeyboardMarkup(filas + _controles_tapas(base))
        return (titulo + f"{html.escape(boton)}: ¿qué medida?" + cargadas,
                InlineKeyboardMarkup(filas + [volver]))

    texto = ("Tocá el tipo de cada tapa, una por una (después la medida y si es de entrada de agua "
             "o ciego). Al terminar, tocá Listo.")
    filas = [[InlineKeyboardButton(boton, callback_data=f"{base}t:{clave}")]
             for clave, (boton, _, _) in campos.CATALOGO_TAPAS[campo].items()]
    return titulo + texto + cargadas, InlineKeyboardMarkup(filas + _controles_tapas(base))


def _controles_tapas(base: str) -> list:
    return [[InlineKeyboardButton("↩️ Borrar última", callback_data=f"{base}borrar"),
             InlineKeyboardButton("✅ Listo", callback_data=f"{base}listo")],
            [InlineKeyboardButton("🚫 No tiene", callback_data=f"{base}no")],
            [InlineKeyboardButton("ATRAS", callback_data="back")]]


def preguntar_tapas(update: Update, context: CallbackContext, sufijo: str, campo: str) -> int:
    context.user_data.pop("tapas_en_curso", None)
    _enviar(update, context, *_pantalla_tapas(context, sufijo, campo))
    return _ir(context, PASOS[sufijo][campo][0])


def boton_tapas(sufijo: str, campo: str):
    estado, clave = PASOS[sufijo][campo]

    def handler(update: Update, context: CallbackContext) -> int:
        query = update.callback_query
        if query.data == "back":
            context.user_data.pop("tapas_en_curso", None)
            return _volver(update, context)
        partes = query.data.split(":")
        if len(partes) < 4 or partes[1] != sufijo or partes[2] != campo:
            _boton_vencido(query)
            return estado
        accion, valor = partes[3], (partes[4] if len(partes) > 4 else None)
        curso = _en_curso(context, sufijo, campo)
        if accion == "listo" and not curso["lista"]:
            query.answer("No cargaste ninguna tapa. Si no tiene, tocá «No tiene».", show_alert=True)
            return estado
        query.answer()
        catalogo = campos.CATALOGO_TAPAS[campo]
        tipo = curso["tipo"] or _tipo_unico(campo)

        if accion == "t" and valor in catalogo:
            curso["tipo"] = valor
            medidas = catalogo[valor][2]
            if len(medidas) == 1:  # una sola medida (punta recortada 54): no hay que elegirla
                curso["medida"] = medidas[0]
        elif accion == "m" and tipo and valor in catalogo[tipo][2]:
            curso["tipo"], curso["medida"] = tipo, valor
        elif accion == "v" and valor in campos.VARIANTES and curso["medida"]:
            curso["lista"].append(campos.codigo_tapa(campo, _tanque(context, sufijo), valor,
                                                     curso["tipo"], curso["medida"]))
            curso["tipo"] = curso["medida"] = None
        elif accion == "volver":
            curso["tipo"] = curso["medida"] = None
        elif accion == "borrar" and curso["lista"]:
            curso["lista"].pop()
        elif accion in ("listo", "no"):
            valor_final = ", ".join(curso["lista"]) if accion == "listo" else campos.NO_TIENE
            context.user_data[clave] = valor_final
            context.user_data.pop("tapas_en_curso", None)
            push_state(context, estado)
            _editar(query, f"✅ Tapas de {NOMBRE_CAMPO[campo].lower()} de "
                           f"{_tanque(context, sufijo).capitalize()}: {html.escape(valor_final)}")
            if campo == "insp":
                return preguntar_tapas(update, context, sufijo, "acceso")
            return preguntar_sellado(update, context, sufijo)
        _editar(query, *_pantalla_tapas(context, sufijo, campo))
        return estado

    handler.__name__ = f"boton_tapas_{sufijo}_{campo}"
    return handler


def texto_tapas(sufijo: str, campo: str):
    estado = PASOS[sufijo][campo][0]

    def handler(update: Update, context: CallbackContext) -> int:
        siguiente = _texto_comun(update, context)
        if siguiente is not None:
            context.user_data.pop("tapas_en_curso", None)
            return siguiente
        # Las tapas no se escriben: se vuelve a mostrar la botonera (sin perder lo cargado)
        texto, botones = _pantalla_tapas(context, sufijo, campo)
        _enviar(update, context, "👇 Las tapas se cargan con los botones.\n\n" + texto, botones)
        return estado

    handler.__name__ = f"texto_tapas_{sufijo}_{campo}"
    return handler


# =============================================================================
# Sellado
# =============================================================================
def _sellado_en_curso(context: CallbackContext, sufijo: str) -> dict:
    actual = context.user_data.get("sellado_en_curso")
    if not actual or actual.get("sufijo") != sufijo:
        actual = {"sufijo": sufijo, "elegidos": [], "escribiendo": False}
        context.user_data["sellado_en_curso"] = actual
    return actual


def _texto_sellado(context: CallbackContext, sufijo: str) -> str:
    return (f"🧱 ¿Cómo sellaste el tanque de {_tanque(context, sufijo).capitalize()}?\n"
            "Podés marcar más de uno y después tocar Listo.")


def _teclado_sellado(context: CallbackContext, sufijo: str) -> InlineKeyboardMarkup:
    elegidos = _sellado_en_curso(context, sufijo)["elegidos"]
    base = f"se:{sufijo}:"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(("✔️ " if clave in elegidos else "") + nombre, callback_data=base + clave)
         for clave, nombre in campos.SELLADOS.items()],
        [InlineKeyboardButton("✏️ Otro", callback_data=base + "otro"),
         InlineKeyboardButton("✅ Listo", callback_data=base + "listo")],
        [InlineKeyboardButton("🚫 No se selló / no tiene", callback_data=base + "no")],
        [InlineKeyboardButton("ATRAS", callback_data="back")],
    ])


def preguntar_sellado(update: Update, context: CallbackContext, sufijo: str) -> int:
    context.user_data.pop("sellado_en_curso", None)
    _enviar(update, context, _texto_sellado(context, sufijo), _teclado_sellado(context, sufijo))
    return _ir(context, PASOS[sufijo]["sellado"][0])


def _guardar_sellado(update: Update, context: CallbackContext, sufijo: str, valor: str) -> int:
    estado, clave = PASOS[sufijo]["sellado"]
    context.user_data[clave] = valor
    context.user_data.pop("sellado_en_curso", None)
    push_state(context, estado)
    _enviar(update, context, f"Indique reparaciones a realizar para {_tanque(context, sufijo).capitalize()}:")
    return _ir(context, PASOS[sufijo]["reparaciones"])


def boton_sellado(sufijo: str):
    estado = PASOS[sufijo]["sellado"][0]

    def handler(update: Update, context: CallbackContext) -> int:
        query = update.callback_query
        if query.data == "back":
            context.user_data.pop("sellado_en_curso", None)
            return _volver(update, context)
        partes = query.data.split(":")
        if len(partes) != 3 or partes[1] != sufijo:
            _boton_vencido(query)
            return estado
        accion = partes[2]
        curso = _sellado_en_curso(context, sufijo)
        if accion == "listo" and not curso["elegidos"]:
            query.answer("Marcá cómo sellaste, o tocá «No se selló / no tiene».", show_alert=True)
            return estado
        query.answer()
        if accion in campos.SELLADOS:
            elegidos = curso["elegidos"]
            elegidos.remove(accion) if accion in elegidos else elegidos.append(accion)
            query.edit_message_reply_markup(reply_markup=_teclado_sellado(context, sufijo))
            return estado
        if accion == "otro":
            curso["escribiendo"] = True
            _editar(query, "✏️ Escribí con qué sellaste:")
            return estado
        if accion in ("listo", "no"):
            valor = campos.texto_sellado(curso["elegidos"]) if accion == "listo" else campos.NO_TIENE
            _editar(query, f"✅ Sellado: {html.escape(valor)}")
            return _guardar_sellado(update, context, sufijo, valor)
        return estado

    handler.__name__ = f"boton_sellado_{sufijo}"
    return handler


def texto_sellado(sufijo: str):
    estado = PASOS[sufijo]["sellado"][0]

    def handler(update: Update, context: CallbackContext) -> int:
        siguiente = _texto_comun(update, context)
        if siguiente is not None:
            context.user_data.pop("sellado_en_curso", None)
            return siguiente
        curso = _sellado_en_curso(context, sufijo)
        texto = update.message.text.strip()
        if curso["escribiendo"] and texto:
            valor = campos.texto_sellado(curso["elegidos"], texto[:80])
            update.message.reply_text(f"✅ Sellado: {valor}")
            return _guardar_sellado(update, context, sufijo, valor)
        _enviar(update, context, "👇 Usá los botones para indicar el sellado.\n\n" +
                _texto_sellado(context, sufijo), _teclado_sellado(context, sufijo))
        return estado

    handler.__name__ = f"texto_sellado_{sufijo}"
    return handler


# =============================================================================
# Contacto: nombre y después teléfono
# =============================================================================
def preguntar_contacto(update: Update, context: CallbackContext) -> int:
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("No había encargado", callback_data="ct:sin")]])
    _enviar(update, context, "👤 ¿Cómo se llama el encargado? (solo el nombre)", markup)
    return _ir(context, CONTACT)


def preguntar_telefono(update: Update, context: CallbackContext) -> int:
    markup = InlineKeyboardMarkup([[InlineKeyboardButton("No dio teléfono", callback_data="ct:sintel")]])
    _enviar(update, context, "📞 Teléfono del encargado, con código de área (ej: 1135456067):", markup)
    return _ir(context, CONTACT_PHONE)


def _guardar_contacto(update: Update, context: CallbackContext, nombre: str, telefono: str) -> int:
    from bot.handlers.shared import pedir_fotos_generales
    context.user_data["contact_nombre"] = nombre
    context.user_data["contact_telefono"] = telefono
    if not nombre:
        context.user_data["contact"] = "Sin encargado"
    else:
        context.user_data["contact"] = f"{nombre} {telefono or '(sin teléfono)'}"
    return pedir_fotos_generales(update, context)


def recibir_nombre(update: Update, context: CallbackContext) -> int:
    siguiente = _texto_comun(update, context)
    if siguiente is not None:
        return siguiente
    nombre, telefono = campos.separar_nombre_telefono(update.message.text)
    if not campos.nombre_valido(nombre):
        update.message.reply_text("⚠️ Escribí el nombre del encargado (ej: Daniel). "
                                  "Si no había, tocá «No había encargado».")
        return CONTACT
    context.user_data["contact_nombre"] = nombre
    push_state(context, CONTACT)
    if telefono:  # escribió nombre y teléfono juntos, como antes ("atrás" vuelve al nombre)
        return _guardar_contacto(update, context, nombre, telefono)
    return preguntar_telefono(update, context)


def recibir_telefono(update: Update, context: CallbackContext) -> int:
    siguiente = _texto_comun(update, context)
    if siguiente is not None:
        return siguiente
    telefono = campos.normalizar_telefono(update.message.text)
    if not telefono:
        update.message.reply_text("⚠️ El teléfono tiene que tener 10 dígitos con el código de área "
                                  "(ej: 1135456067 o 2214567890). Si no lo dio, tocá «No dio teléfono».")
        return CONTACT_PHONE
    push_state(context, CONTACT_PHONE)
    return _guardar_contacto(update, context, context.user_data.get("contact_nombre", ""), telefono)


def boton_contacto(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    actual = context.user_data.get("current_state")
    if (query.data, actual) not in (("ct:sin", CONTACT), ("ct:sintel", CONTACT_PHONE)):
        _boton_vencido(query)
        return actual
    query.answer()
    query.edit_message_reply_markup(reply_markup=None)
    push_state(context, actual)
    if query.data == "ct:sin":
        context.user_data.pop("contact_nombre", None)
        return _guardar_contacto(update, context, "", None)
    return _guardar_contacto(update, context, context.user_data.get("contact_nombre", ""), None)
