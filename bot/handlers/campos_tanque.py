"""
campos_tanque.py
----------------
Carga manual de cada tanque con formato fijo donde importa (ver bot/services/campos.py):
medida validada, tapas y sellado en texto libre (como siempre), reparaciones con un menú del
catálogo del dueño, y el contacto en dos pasos (nombre y teléfono).

Botones (el sufijo va en el botón: uno de un paso que ya terminó no se toma):
  "rp:<sufijo>:g:<grupo>"        reparación (tapa de inspección, de acceso, marco, revoque...)
  "rp:<sufijo>:t:<tipo>"         tipo de tapa de acceso
  "rp:<sufijo>:m:<medida>"       medida
  "rp:<sufijo>:v:<EA|C>"         entrada de agua o ciego
  "rp:<sufijo>:cara:<cara>", "rp:<sufijo>:cuba:<EA|C>", "rp:<sufijo>:ext:<completo|parche>"
                                 revoque: cara, cuba y si es completo o un parche (medidas escritas)
  "rp:<sufijo>:<volver|borrar|listo|no>"
  "md:<sufijo>:<plastico|cilindrico|acero>" material de un tanque en litros
  "ct:<sin|sintel>"              sin encargado / sin teléfono
"""

import html

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.error import BadRequest
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import *
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import (push_state, back_handler, check_special_commands, terminar_edicion,
                                 teclado_atras)
from bot.services import campos

PASOS = {
    "main": {"tanque": "selected_category", "medida": (MEASURE_MAIN, "measure_main"),
             "insp": (TAPAS_INSPECCION_MAIN, "tapas_inspeccion_main"),
             "acceso": (TAPAS_ACCESO_MAIN, "tapas_acceso_main"),
             "sellado": (SEALING_MAIN, "sealing_main"), "reparaciones": (REPAIR_MAIN, "repairs")},
    "alt1": {"tanque": "alternative_1", "medida": (MEASURE_ALT1, "measure_alt1"),
             "insp": (TAPAS_INSPECCION_ALT1, "tapas_inspeccion_alt1"),
             "acceso": (TAPAS_ACCESO_ALT1, "tapas_acceso_alt1"),
             "sellado": (SEALING_ALT1, "sealing_alt1"), "reparaciones": (REPAIR_ALT1, "repair_alt1")},
    "alt2": {"tanque": "alternative_2", "medida": (MEASURE_ALT2, "measure_alt2"),
             "insp": (TAPAS_INSPECCION_ALT2, "tapas_inspeccion_alt2"),
             "acceso": (TAPAS_ACCESO_ALT2, "tapas_acceso_alt2"),
             "sellado": (SEALING_ALT2, "sealing_alt2"), "reparaciones": (REPAIR_ALT2, "repair_alt2")},
}


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
                             "alto, ancho y profundo (ej: 1.80 2 1.50 o 180 200 150).", teclado_atras())
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
                                      reply_markup=teclado_atras(botones))
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
    fin = terminar_edicion(update, context)
    if fin is not None:
        return fin
    return preguntar_texto(update, context, sufijo, "insp")


# =============================================================================
# Tapas de inspección y de acceso (texto, solo las medidas de la ayuda) y sellado (texto libre)
# =============================================================================
def _pregunta_texto(context: CallbackContext, sufijo: str, campo: str) -> str:
    if campo == "insp":
        return "Indique TAPAS INSPECCIÓN (30 40 50 60 80):"
    if campo == "acceso":
        return "Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"
    tanque = _tanque(context, sufijo).capitalize()
    if sufijo == "main":
        return f"Indique cómo selló el tanque de {tanque} (EJ: masilla, burlete):"
    return f"Indique cómo selló el tanque de {tanque}:"


def preguntar_texto(update: Update, context: CallbackContext, sufijo: str, campo: str) -> int:
    _enviar(update, context, _pregunta_texto(context, sufijo, campo), teclado_atras())
    return _ir(context, PASOS[sufijo][campo][0])


def recibir_texto(sufijo: str, campo: str):
    estado, clave = PASOS[sufijo][campo]
    siguiente_campo = {"insp": "acceso", "acceso": "sellado"}.get(campo)

    def handler(update: Update, context: CallbackContext) -> int:
        siguiente = _texto_comun(update, context)
        if siguiente is not None:
            return siguiente
        valor = update.message.text
        if campo in campos.MEDIDAS_TAPAS:  # tapas: solo las medidas de la ayuda
            valor, problema = campos.normalizar_tapas(campo, valor)
            if problema:
                update.message.reply_text(f"⚠️ {problema}")
                return estado
        context.user_data[clave] = valor
        push_state(context, estado)
        fin = terminar_edicion(update, context)
        if fin is not None:
            return fin
        if siguiente_campo:
            return preguntar_texto(update, context, sufijo, siguiente_campo)
        return preguntar_reparaciones(update, context, sufijo)

    handler.__name__ = f"recibir_{campo}_{sufijo}"
    return handler


# =============================================================================
# Reparaciones: menú con el catálogo del dueño (bot/services/campos.py)
# =============================================================================
def _rep_en_curso(context: CallbackContext, sufijo: str) -> dict:
    actual = context.user_data.get("reparaciones_en_curso")
    if not actual or actual.get("sufijo") != sufijo:
        actual = {"sufijo": sufijo, "lista": [], "grupo": None, "tipo": None, "medida": None,
                  "cara": None, "cuba": None, "parche": False}
        context.user_data["reparaciones_en_curso"] = actual
    return actual


def _rep_reiniciar_eleccion(curso: dict) -> None:
    curso.update({"grupo": None, "tipo": None, "medida": None, "cara": None, "cuba": None, "parche": False})


def _rep_tipo(curso: dict):
    """El tipo elegido, o el único que hay (todos los grupos menos la tapa de acceso tienen uno)."""
    if curso["tipo"] or not curso["grupo"]:
        return curso["tipo"]
    tipos = campos.CATALOGO_REPARACIONES[curso["grupo"]][2]
    return next(iter(tipos)) if len(tipos) == 1 else None


def _rep_pantalla(context: CallbackContext, sufijo: str):
    """
    (texto, botones) de la pantalla actual del menú. Cada pantalla hace una sola pregunta, en
    negrita, con una línea arriba que dice dónde está. Lo cargado se muestra solo en la pantalla
    principal (en palabras, no en código), para no mezclarlo con la pregunta.
    """
    curso = _rep_en_curso(context, sufijo)
    base = f"rp:{sufijo}:"
    tanque = _tanque(context, sufijo).capitalize()
    volver = [InlineKeyboardButton("⬅️ Volver al menú", callback_data=f"{base}volver")]
    grupo = curso["grupo"]

    def pantalla(donde: str, pregunta: str, ayuda: str = ""):
        texto = f"🔧 {tanque} › {html.escape(donde)}\n\n<b>{pregunta}</b>"
        return texto + (f"\n{ayuda}" if ayuda else "")

    if grupo is None:
        # "Sin reparaciones" arriba de todo; con algo cargado no va (borraría lo cargado)
        filas = [] if curso["lista"] else [[InlineKeyboardButton("🚫 Sin reparaciones", callback_data=f"{base}no")]]
        filas += [[InlineKeyboardButton(f"{campos.EMOJI_REPARACION[clave]} {boton}", callback_data=f"{base}g:{clave}")]
                  for clave, (boton, _, _) in campos.CATALOGO_REPARACIONES.items()]
        filas += [[InlineKeyboardButton("↩️ Borrar última", callback_data=f"{base}borrar"),
                   InlineKeyboardButton("✅ Listo", callback_data=f"{base}listo")],
                  [InlineKeyboardButton("⬅️ ATRAS", callback_data="back")]]
        partes = [f"🔧 <b>Reparaciones de {tanque}</b>"]
        if curso.get("aviso"):
            partes.append(html.escape(curso["aviso"]))
        if curso["lista"]:
            partes.append("Ya cargaste:\n" + "\n".join(f"• {html.escape(campos.legible(i))}" for i in curso["lista"]))
            partes.append("Tocá otra reparación para agregarla, o <b>✅ Listo</b> si ya están todas.")
        else:
            partes.append("Tocá cada reparación que haya que hacer, de a una. Si son 2 iguales, cargala "
                          "2 veces. Si no hay ninguna, tocá <b>🚫 Sin reparaciones</b> (arriba de todo).")
        return "\n\n".join(partes), InlineKeyboardMarkup(filas)

    nombre_grupo, _, tipos = campos.CATALOGO_REPARACIONES[grupo]
    if grupo == "rev":
        return _rep_pantalla_revoque(curso, base, pantalla, volver)

    tipo = _rep_tipo(curso)
    if curso["medida"]:
        descripcion = f"{nombre_grupo} {tipos[tipo][1]} {curso['medida']}".replace("  ", " ")
        return pantalla(descripcion, "¿Es la de la entrada de agua o la del ciego?"), InlineKeyboardMarkup([
            [InlineKeyboardButton("💧 Entrada de agua", callback_data=f"{base}v:EA"),
             InlineKeyboardButton("⚫ Ciego", callback_data=f"{base}v:C")], volver])
    if tipo:
        nombre_tipo, _, medidas = tipos[tipo]
        botones = [InlineKeyboardButton(m, callback_data=f"{base}m:{m}") for m in medidas]
        filas = [botones[i:i + 3] for i in range(0, len(botones), 3)] + [volver]
        nombre = f"{nombre_grupo} {nombre_tipo.lower()}".strip() if nombre_tipo else nombre_grupo
        return pantalla(nombre, "¿Qué medida tiene?"), InlineKeyboardMarkup(filas)
    filas = [[InlineKeyboardButton(f"▫️ {boton}", callback_data=f"{base}t:{clave}")]
             for clave, (boton, _, _) in tipos.items()] + [volver]
    return pantalla(nombre_grupo, "¿De qué tipo es?"), InlineKeyboardMarkup(filas)


def _rep_pantalla_revoque(curso: dict, base: str, pantalla, volver: list):
    """Revoque, de a una cara: cara -> cuba -> completo o parche -> (parche) medidas escritas."""
    cara = campos.CARAS_REVOQUE.get(curso["cara"])
    if not cara:
        filas = [[InlineKeyboardButton(f"▫️ {nombre.capitalize()}", callback_data=f"{base}cara:{clave}")]
                 for clave, nombre in campos.CARAS_REVOQUE.items()] + [volver]
        return pantalla("Revoque", "¿Qué cara del tanque hay que revocar?"), InlineKeyboardMarkup(filas)
    if not curso["cuba"]:
        return (pantalla(f"Revoque {cara}", "¿En qué cuba?",
                         "Si el tanque tiene una sola cuba, elegí <b>Entrada de agua</b>."),
                InlineKeyboardMarkup([
                    [InlineKeyboardButton("💧 Entrada de agua", callback_data=f"{base}cuba:EA"),
                     InlineKeyboardButton("⚫ Ciego", callback_data=f"{base}cuba:C")], volver]))
    donde = f"Revoque {cara} ({campos.CUBAS[curso['cuba']]})"
    if curso["parche"]:
        return (pantalla(donde, "📏 ¿Cuánto mide el parche?",
                         "\nEscribí el <b>largo</b> y el <b>alto</b> en metros, con una x en el medio.\n"
                         "Por ejemplo: <b>2x2</b> · <b>1,5x1,5</b> · <b>0,5x1</b>\n\n"
                         "👇 Escribilo abajo y mandalo."),
                InlineKeyboardMarkup([volver]))
    return pantalla(donde, f"¿Hay que revocar todo el {cara} o es un parche?"), InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🧱 Todo el {cara}", callback_data=f"{base}ext:completo")],
        [InlineKeyboardButton("🩹 Un parche (después escribís la medida)", callback_data=f"{base}ext:parche")],
        volver])


def _rep_agregar(curso: dict, item: str) -> None:
    curso["lista"].append(item)
    curso["aviso"] = f"✅ Agregado: {campos.legible(item)}"
    _rep_reiniciar_eleccion(curso)


def preguntar_reparaciones(update: Update, context: CallbackContext, sufijo: str) -> int:
    estado, clave = PASOS[sufijo]["reparaciones"]
    context.user_data.pop("reparaciones_en_curso", None)
    # Si vuelve con "atrás" desde las fotos, arranca con lo que ya había cargado
    anterior = context.user_data.get(clave) or ""
    if anterior and anterior != campos.SIN_REPARACIONES:
        _rep_en_curso(context, sufijo)["lista"] = anterior.split(", ")
    _enviar(update, context, *_rep_pantalla(context, sufijo))
    return _ir(context, estado)


def _rep_terminar(update: Update, context: CallbackContext, sufijo: str, lista: list) -> int:
    from bot.handlers.fotos_reparaciones import pedir_fotos, SIGUIENTE_MANUAL
    estado, clave = PASOS[sufijo]["reparaciones"]
    valor = ", ".join(lista) if lista else campos.SIN_REPARACIONES
    context.user_data[clave] = valor
    context.user_data.pop("reparaciones_en_curso", None)
    push_state(context, estado)
    detalle = ("\n" + "\n".join(f"• {html.escape(campos.legible(i))}" for i in lista)) if lista else " ninguna"
    _editar(update.callback_query, f"✅ Reparaciones de {_tanque(context, sufijo).capitalize()}:{detalle}")
    if lista:
        return pedir_fotos(update, context, sufijo, "manual")
    # Sin reparaciones: no hay fotos que pedir, ni ítems de una carga anterior
    context.user_data.get("fotos_reparaciones", {}).pop(sufijo, None)
    context.user_data.get("items_reparacion", {}).pop(sufijo, None)
    fin = terminar_edicion(update, context)
    if fin is not None:
        return fin
    siguiente = SIGUIENTE_MANUAL[sufijo][0]
    _enviar(update, context, f"Indique sugerencias p/ la próx limpieza para {_tanque(context, sufijo).capitalize()}:",
            teclado_atras())
    return _ir(context, siguiente)


def boton_reparaciones(sufijo: str):
    estado = PASOS[sufijo]["reparaciones"][0]

    def handler(update: Update, context: CallbackContext) -> int:
        query = update.callback_query
        if query.data == "back":
            context.user_data.pop("reparaciones_en_curso", None)
            return _volver(update, context)
        partes = query.data.split(":")
        if len(partes) < 3 or partes[0] != "rp" or partes[1] != sufijo:
            _boton_vencido(query)
            return estado
        accion, valor = partes[2], (partes[3] if len(partes) > 3 else None)
        curso = _rep_en_curso(context, sufijo)
        if accion == "listo" and not curso["lista"]:
            query.answer("No cargaste ninguna reparación. Si no hay, tocá «Sin reparaciones».", show_alert=True)
            return estado
        if accion == "no" and curso["lista"]:  # botón viejo: no se borra lo cargado
            query.answer("Ya cargaste reparaciones. Si no va ninguna, borralas con «Borrar última».",
                         show_alert=True)
            return estado
        query.answer()
        curso["aviso"] = None
        catalogo = campos.CATALOGO_REPARACIONES
        tanque = _tanque(context, sufijo)
        grupo, tipo = curso["grupo"], _rep_tipo(curso)

        if accion == "g" and valor in catalogo:
            if catalogo[valor][1] is None and valor != "rev":  # flotante, automático: se agregan directo
                _rep_agregar(curso, campos.reparacion(valor))
            else:
                _rep_reiniciar_eleccion(curso)
                curso["grupo"] = valor
        elif accion == "t" and grupo and valor in catalogo[grupo][2]:
            curso["tipo"] = valor
            medidas = catalogo[grupo][2][valor][2]
            if len(medidas) == 1:  # una sola medida (punta recortada 54): no hay que elegirla
                curso["medida"] = medidas[0]
        elif accion == "m" and grupo and tipo and valor in catalogo[grupo][2][tipo][2]:
            curso["tipo"], curso["medida"] = tipo, valor
        elif accion == "v" and valor in campos.VARIANTES and curso["medida"]:
            _rep_agregar(curso, campos.reparacion(grupo, tanque, valor, tipo, curso["medida"]))
        elif accion == "cara" and grupo == "rev" and valor in campos.CARAS_REVOQUE:
            curso["cara"] = valor
        elif accion == "cuba" and grupo == "rev" and curso["cara"] and valor in campos.CUBAS:
            curso["cuba"] = valor
        elif accion == "ext" and grupo == "rev" and curso["cuba"] and valor == "completo":
            _rep_agregar(curso, campos.reparacion("rev", variante=curso["cuba"], cara=curso["cara"]))
        elif accion == "ext" and grupo == "rev" and curso["cuba"] and valor == "parche":
            curso["parche"] = True  # las medidas se escriben (texto_reparaciones)
        elif accion == "volver":
            _rep_reiniciar_eleccion(curso)
        elif accion == "borrar" and curso["lista"]:
            curso["aviso"] = f"↩️ Borrada: {campos.legible(curso['lista'].pop())}"
        elif accion == "listo":
            return _rep_terminar(update, context, sufijo, curso["lista"])
        elif accion == "no":
            return _rep_terminar(update, context, sufijo, [])
        _editar(query, *_rep_pantalla(context, sufijo))
        return estado

    handler.__name__ = f"boton_reparaciones_{sufijo}"
    return handler


def texto_reparaciones(sufijo: str):
    estado = PASOS[sufijo]["reparaciones"][0]

    def handler(update: Update, context: CallbackContext) -> int:
        siguiente = _texto_comun(update, context)
        if siguiente is not None:
            context.user_data.pop("reparaciones_en_curso", None)
            return siguiente
        curso = _rep_en_curso(context, sufijo)
        if curso["parche"]:  # lo único que se escribe: las medidas de un parche de revoque
            parche, problema = campos.normalizar_parche(update.message.text)
            if problema:
                update.message.reply_text(f"⚠️ {problema}")
                return estado
            _rep_agregar(curso, campos.reparacion("rev", variante=curso["cuba"], cara=curso["cara"],
                                                  parche=parche))
            _enviar(update, context, *_rep_pantalla(context, sufijo))
            return estado
        # Las reparaciones no se escriben: se vuelve a mostrar el menú (sin perder lo cargado)
        texto, botones = _rep_pantalla(context, sufijo)
        _enviar(update, context, "👇 Las reparaciones se cargan con los botones.\n\n" + texto, botones)
        return estado

    handler.__name__ = f"texto_reparaciones_{sufijo}"
    return handler


# =============================================================================
# Contacto: nombre y después teléfono
# =============================================================================
def preguntar_contacto(update: Update, context: CallbackContext) -> int:
    markup = teclado_atras([[InlineKeyboardButton("No había encargado", callback_data="ct:sin")]])
    _enviar(update, context, "👤 ¿Cómo se llama el encargado? (solo el nombre)", markup)
    return _ir(context, CONTACT)


def preguntar_telefono(update: Update, context: CallbackContext) -> int:
    markup = teclado_atras([[InlineKeyboardButton("No dio teléfono", callback_data="ct:sintel")]])
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
    fin = terminar_edicion(update, context)
    if fin is not None:
        return fin
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
