"""
campos_tanque.py
----------------
Carga manual de los tanques del reporte, de a uno (bot/services/tanques_reporte.py), con formato
fijo donde importa (bot/services/campos.py):

  cuántos cuerpos tiene el edificio -> tipo de tanque -> (si hay más de un cuerpo) de qué cuerpo
  -> medida (validada) -> tapas de inspección y de acceso (solo medidas válidas) -> sellado
  -> reparaciones (menú del catálogo del dueño) -> fotos de las reparaciones -> sugerencias
  -> ¿hay otro tanque? (sí: otra vez desde el tipo; no: contacto, en dos pasos)

El tanque que se está cargando es user_data["tanque_actual"].

Botones (el tanque va en el botón: uno de un tanque o paso que ya terminó no se toma):
  "cu:<1|2|3>"                   cuántos cuerpos tiene el edificio
  "tq:<CISTERNA|RESERVA|INTERMEDIARIO>"   tipo del tanque nuevo
  "cp:<frente|fondo|izquierda|derecha>"   cuerpo del tanque nuevo
  "ot:<si|no>"                   ¿hay otro tanque?
  "md:<tanque>:<plastico|cilindrico|acero>" material de un tanque en litros
  "rp:<tanque>:g:<grupo>"        reparación (tapa de inspección, de acceso, marco, revoque...)
  "rp:<tanque>:t:<tipo>"         tipo de tapa de acceso
  "rp:<tanque>:m:<medida>"       medida
  "rp:<tanque>:v:<EA|C>"         entrada de agua o ciego
  "rp:<tanque>:cara:<cara>", "rp:<tanque>:cuba:<EA|C>", "rp:<tanque>:ext:<completo|parche>"
                                 revoque: cara, cuba y si es completo o un parche (medidas escritas)
  "rp:<tanque>:<volver|borrar|listo|no>"
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
from bot.services import tanques_reporte as tq


def _actual(context: CallbackContext) -> str:
    return context.user_data.get("tanque_actual", "")


def _nombre(context: CallbackContext, tanque_id: str = None) -> str:
    return tq.nombre(context.user_data, tanque_id or _actual(context))


def _clave(context: CallbackContext, campo: str, tanque_id: str = None) -> str:
    return tq.clave(campo, tanque_id or _actual(context))


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


def _boton(update: Update, prefijo: str, validos, estado_esperado: int, context: CallbackContext):
    """El valor de un botón "<prefijo>:<valor>" del paso actual, o None (y avisa) si no corresponde."""
    query = update.callback_query
    partes = query.data.split(":", 1)
    if (len(partes) != 2 or partes[0] != prefijo or partes[1] not in validos
            or context.user_data.get("current_state") != estado_esperado):
        _boton_vencido(query)
        return None
    query.answer()
    return partes[1]


# =============================================================================
# Cuerpos, tipo y cuerpo de cada tanque, "¿hay otro tanque?"
# =============================================================================
def preguntar_cuerpos(update: Update, context: CallbackContext) -> int:
    botones = [[InlineKeyboardButton("1 cuerpo", callback_data="cu:1"),
                InlineKeyboardButton("2 cuerpos", callback_data="cu:2"),
                InlineKeyboardButton("3 o más", callback_data="cu:3")]]
    _enviar(update, context, "🏢 ¿Cuántos cuerpos tiene el edificio?\n"
                             "(2 cuerpos = dos edificios en la misma dirección, por ejemplo separados "
                             "por un pozo de aire y luz)", teclado_atras(botones))
    return _ir(context, CUERPOS)


def boton_cuerpos(update: Update, context: CallbackContext) -> int:
    valor = _boton(update, "cu", ("1", "2", "3"), CUERPOS, context)
    if valor is None:
        return context.user_data.get("current_state")
    texto = {"1": "1 cuerpo", "2": "2 cuerpos", "3": "3 o más cuerpos"}[valor]
    _editar(update.callback_query, f"🏢 Edificio de {texto}")
    context.user_data["cuerpos"] = int(valor)
    push_state(context, CUERPOS)
    return preguntar_tipo_tanque(update, context)


def preguntar_tipo_tanque(update: Update, context: CallbackContext) -> int:
    hay = len(tq.lista(context.user_data))
    pregunta = "Seleccione el tipo de tanque:" if not hay else "¿De qué tipo es el otro tanque?"
    botones = [[InlineKeyboardButton(t, callback_data=f"tq:{t}") for t in tq.TIPOS]]
    _enviar(update, context, pregunta, teclado_atras(botones))
    return _ir(context, TANK_TYPE)


def boton_tipo_tanque(update: Update, context: CallbackContext) -> int:
    tipo = _boton(update, "tq", tq.TIPOS, TANK_TYPE, context)
    if tipo is None:
        return context.user_data.get("current_state")
    _editar(update.callback_query, f"Tipo de tanque: {tipo.capitalize()}")
    context.user_data["modo_ingreso"] = "MANUAL"
    push_state(context, TANK_TYPE)
    if context.user_data.get("cuerpos", 1) > 1:
        context.user_data["tanque_nuevo_tipo"] = tipo
        return preguntar_cuerpo_tanque(update, context)
    return _empezar_tanque(update, context, tipo, None)


def preguntar_cuerpo_tanque(update: Update, context: CallbackContext) -> int:
    tipo = context.user_data.get("tanque_nuevo_tipo", "")
    botones = [[InlineKeyboardButton(n.capitalize(), callback_data=f"cp:{c}") for c, n in tq.CUERPOS.items()]]
    _enviar(update, context, f"🏢 ¿De qué cuerpo es este tanque de {tipo.capitalize()}?", teclado_atras(botones))
    return _ir(context, TANK_CUERPO)


def boton_cuerpo_tanque(update: Update, context: CallbackContext) -> int:
    cuerpo = _boton(update, "cp", tuple(tq.CUERPOS), TANK_CUERPO, context)
    if cuerpo is None:
        return context.user_data.get("current_state")
    _editar(update.callback_query, f"🏢 Cuerpo: {tq.CUERPOS[cuerpo]}")
    push_state(context, TANK_CUERPO)
    # El tipo queda guardado: si vuelve con "atrás" a esta pregunta, se vuelve a mostrar
    return _empezar_tanque(update, context, context.user_data.get("tanque_nuevo_tipo", ""), cuerpo)


def _empezar_tanque(update: Update, context: CallbackContext, tipo: str, cuerpo) -> int:
    context.user_data["tanque_actual"] = tq.nuevo(context.user_data, tipo, cuerpo)
    return preguntar_medida(update, context)


def preguntar_otro_tanque(update: Update, context: CallbackContext) -> int:
    nombres = ", ".join(tq.nombre(context.user_data, t["id"]) for t in tq.lista(context.user_data))
    botones = [[InlineKeyboardButton("➕ Sí, cargar otro", callback_data="ot:si"),
                InlineKeyboardButton("No, eso es todo", callback_data="ot:no")]]
    _enviar(update, context, f"Tanques cargados: <b>{html.escape(nombres)}</b>\n\n"
                             "¿Hay otro tanque para cargar? (otra cisterna, reserva o intermediario, "
                             "también de otro cuerpo)", teclado_atras(botones))
    return _ir(context, OTRO_TANQUE)


def boton_otro_tanque(update: Update, context: CallbackContext) -> int:
    valor = _boton(update, "ot", ("si", "no"), OTRO_TANQUE, context)
    if valor is None:
        return context.user_data.get("current_state")
    _editar(update.callback_query, "➕ Otro tanque" if valor == "si" else "✅ No hay más tanques")
    push_state(context, OTRO_TANQUE)
    if valor == "si":
        return preguntar_tipo_tanque(update, context)
    return preguntar_contacto(update, context)


def preguntar_paso(update: Update, context: CallbackContext, estado: int) -> int:
    """Vuelve a hacer la pregunta de un paso del tanque actual (al ir "atrás" o al modificar)."""
    campo = CAMPO_DEL_PASO[estado]
    if campo == "measure":
        return preguntar_medida(update, context)
    if campo == "repairs":
        return preguntar_reparaciones(update, context)
    if campo == "suggestions":
        return preguntar_sugerencias(update, context)
    return preguntar_texto(update, context, campo)


# =============================================================================
# Medida
# =============================================================================
def preguntar_medida(update: Update, context: CallbackContext) -> int:
    _enviar(update, context, f"📏 Medida del tanque de {_nombre(context)}: "
                             "alto, ancho y profundo (ej: 1.80 2 1.50 o 180 200 150).", teclado_atras())
    return _ir(context, MEASURE)


def recibir_medida(update: Update, context: CallbackContext) -> int:
    siguiente = _texto_comun(update, context)
    if siguiente is not None:
        return siguiente
    valor, problema = campos.normalizar_medida(update.message.text)
    if problema:
        update.message.reply_text(f"⚠️ {problema}\n\n{campos.AYUDA_MEDIDA}")
        return MEASURE
    if valor.startswith("LITROS:"):
        litros = valor.split(":", 1)[1]
        context.user_data["litros_pendiente"] = litros
        botones = [[InlineKeyboardButton(nombre.capitalize(), callback_data=f"md:{_actual(context)}:{clave_m}")
                    for clave_m, nombre in campos.MATERIALES.items()]]
        update.message.reply_text(f"Tanque de {litros} litros. ¿De qué material es?",
                                  reply_markup=teclado_atras(botones))
        return MEASURE
    return _guardar_medida(update, context, valor)


def boton_material(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    _, de, material = (query.data.split(":") + ["", ""])[:3]
    litros = context.user_data.get("litros_pendiente")
    if de != _actual(context) or material not in campos.MATERIALES or not litros:
        _boton_vencido(query)
        return MEASURE
    query.answer()
    valor = f"{litros} lts ({campos.MATERIALES[material]})"
    query.edit_message_text(f"✅ Medida: {valor}")
    context.user_data.pop("litros_pendiente", None)
    return _guardar_medida(update, context, valor)


def _guardar_medida(update: Update, context: CallbackContext, valor: str) -> int:
    context.user_data[_clave(context, "measure")] = valor
    push_state(context, MEASURE)
    if update.message:
        update.message.reply_text(f"✅ Medida: {valor}")
    fin = terminar_edicion(update, context)
    if fin is not None:
        return fin
    return preguntar_texto(update, context, "tapas_inspeccion")


# =============================================================================
# Tapas de inspección y de acceso (texto, solo las medidas de la ayuda) y sellado (texto libre)
# =============================================================================
ESTADO_TEXTO = {"tapas_inspeccion": TAPAS_INSPECCION, "tapas_acceso": TAPAS_ACCESO, "sealing": SEALING}
_MEDIDAS_TAPA = {"tapas_inspeccion": "insp", "tapas_acceso": "acceso"}  # campo -> clave en campos.py


def _pregunta_texto(context: CallbackContext, campo: str) -> str:
    if campo == "tapas_inspeccion":
        return "Indique TAPAS INSPECCIÓN (30 40 50 60 80):"
    if campo == "tapas_acceso":
        return "Indique TAPAS ACCESO (4789/50125/49.5 56 56.5 58 54 51.5 62 65):"
    return f"Indique cómo selló el tanque de {_nombre(context)} (EJ: masilla, burlete):"


def preguntar_texto(update: Update, context: CallbackContext, campo: str) -> int:
    _enviar(update, context, _pregunta_texto(context, campo), teclado_atras())
    return _ir(context, ESTADO_TEXTO[campo])


def recibir_texto(campo: str):
    estado = ESTADO_TEXTO[campo]
    siguiente_campo = {"tapas_inspeccion": "tapas_acceso", "tapas_acceso": "sealing"}.get(campo)

    def handler(update: Update, context: CallbackContext) -> int:
        siguiente = _texto_comun(update, context)
        if siguiente is not None:
            return siguiente
        valor = update.message.text
        if campo in _MEDIDAS_TAPA:  # tapas: solo las medidas de la ayuda
            valor, problema = campos.normalizar_tapas(_MEDIDAS_TAPA[campo], valor)
            if problema:
                update.message.reply_text(f"⚠️ {problema}")
                return estado
        context.user_data[_clave(context, campo)] = valor
        push_state(context, estado)
        fin = terminar_edicion(update, context)
        if fin is not None:
            return fin
        if siguiente_campo:
            return preguntar_texto(update, context, siguiente_campo)
        return preguntar_reparaciones(update, context)

    handler.__name__ = f"recibir_{campo}"
    return handler


# =============================================================================
# Sugerencias (texto libre); después, "¿hay otro tanque?"
# =============================================================================
def preguntar_sugerencias(update: Update, context: CallbackContext) -> int:
    _enviar(update, context, f"Indique sugerencias p/ la próx limpieza para {_nombre(context)}:", teclado_atras())
    return _ir(context, SUGGESTIONS)


def recibir_sugerencias(update: Update, context: CallbackContext) -> int:
    siguiente = _texto_comun(update, context)
    if siguiente is not None:
        return siguiente
    context.user_data[_clave(context, "suggestions")] = update.message.text
    push_state(context, SUGGESTIONS)
    fin = terminar_edicion(update, context)
    if fin is not None:
        return fin
    return preguntar_otro_tanque(update, context)


# =============================================================================
# Reparaciones: menú con el catálogo del dueño (bot/services/campos.py)
# =============================================================================
def _rep_en_curso(context: CallbackContext) -> dict:
    tanque_id = _actual(context)
    actual = context.user_data.get("reparaciones_en_curso")
    if not actual or actual.get("tanque") != tanque_id:
        actual = {"tanque": tanque_id, "lista": [], "grupo": None, "tipo": None, "medida": None,
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


def _rep_pantalla(context: CallbackContext):
    """
    (texto, botones) de la pantalla actual del menú. Cada pantalla hace una sola pregunta, en
    negrita, con una línea arriba que dice dónde está. Lo cargado se muestra solo en la pantalla
    principal (en palabras, no en código), para no mezclarlo con la pregunta.
    """
    curso = _rep_en_curso(context)
    base = f"rp:{_actual(context)}:"
    tanque = _nombre(context)
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


def preguntar_reparaciones(update: Update, context: CallbackContext) -> int:
    context.user_data.pop("reparaciones_en_curso", None)
    # Si vuelve con "atrás" desde las fotos (o modifica), arranca con lo que ya había cargado
    anterior = context.user_data.get(_clave(context, "repairs")) or ""
    if anterior and anterior != campos.SIN_REPARACIONES:
        _rep_en_curso(context)["lista"] = anterior.split(", ")
    _enviar(update, context, *_rep_pantalla(context))
    return _ir(context, REPAIR)


def _rep_terminar(update: Update, context: CallbackContext, lista: list) -> int:
    from bot.handlers.fotos_reparaciones import pedir_fotos
    tanque_id = _actual(context)
    context.user_data[_clave(context, "repairs")] = ", ".join(lista) if lista else campos.SIN_REPARACIONES
    context.user_data.pop("reparaciones_en_curso", None)
    push_state(context, REPAIR)
    detalle = ("\n" + "\n".join(f"• {html.escape(campos.legible(i))}" for i in lista)) if lista else " ninguna"
    _editar(update.callback_query, f"✅ Reparaciones de {_nombre(context)}:{detalle}")
    if lista:
        return pedir_fotos(update, context, tanque_id, "manual")
    # Sin reparaciones: no hay fotos que pedir, ni ítems de una carga anterior
    context.user_data.get("fotos_reparaciones", {}).pop(tanque_id, None)
    context.user_data.get("items_reparacion", {}).pop(tanque_id, None)
    fin = terminar_edicion(update, context)
    if fin is not None:
        return fin
    return preguntar_sugerencias(update, context)


def boton_reparaciones(update: Update, context: CallbackContext) -> int:
    estado = REPAIR
    query = update.callback_query
    if query.data == "back":
        context.user_data.pop("reparaciones_en_curso", None)
        return _volver(update, context)
    partes = query.data.split(":")
    if len(partes) < 3 or partes[0] != "rp" or partes[1] != _actual(context):
        _boton_vencido(query)
        return estado
    accion, valor = partes[2], (partes[3] if len(partes) > 3 else None)
    curso = _rep_en_curso(context)
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
    tanque = tq.tipo(context.user_data, _actual(context))
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
        _rep_agregar(curso, campos.reparacion("rev", tanque, curso["cuba"], cara=curso["cara"]))
    elif accion == "ext" and grupo == "rev" and curso["cuba"] and valor == "parche":
        curso["parche"] = True  # las medidas se escriben (texto_reparaciones)
    elif accion == "volver":
        _rep_reiniciar_eleccion(curso)
    elif accion == "borrar" and curso["lista"]:
        curso["aviso"] = f"↩️ Borrada: {campos.legible(curso['lista'].pop())}"
    elif accion == "listo":
        return _rep_terminar(update, context, curso["lista"])
    elif accion == "no":
        return _rep_terminar(update, context, [])
    _editar(query, *_rep_pantalla(context))
    return estado


def texto_reparaciones(update: Update, context: CallbackContext) -> int:
    estado = REPAIR
    siguiente = _texto_comun(update, context)
    if siguiente is not None:
        context.user_data.pop("reparaciones_en_curso", None)
        return siguiente
    curso = _rep_en_curso(context)
    if curso["parche"]:  # lo único que se escribe: las medidas de un parche de revoque
        parche, problema = campos.normalizar_parche(update.message.text)
        if problema:
            update.message.reply_text(f"⚠️ {problema}")
            return estado
        _rep_agregar(curso, campos.reparacion("rev", tq.tipo(context.user_data, _actual(context)),
                                              curso["cuba"], cara=curso["cara"], parche=parche))
        _enviar(update, context, *_rep_pantalla(context))
        return estado
    # Las reparaciones no se escriben: se vuelve a mostrar el menú (sin perder lo cargado)
    texto, botones = _rep_pantalla(context)
    _enviar(update, context, "👇 Las reparaciones se cargan con los botones.\n\n" + texto, botones)
    return estado


# =============================================================================
# Contacto: nombre y después teléfono
# =============================================================================
def preguntar_contacto(update: Update, context: CallbackContext) -> int:
    markup = teclado_atras()
    _enviar(update, context, "👤 ¿Cómo se llama el encargado? (solo el nombre)", markup)
    return _ir(context, CONTACT)


def preguntar_telefono(update: Update, context: CallbackContext) -> int:
    markup = teclado_atras()
    _enviar(update, context, "📞 Teléfono del encargado, con código de área (ej: 1135456067):", markup)
    return _ir(context, CONTACT_PHONE)


def _guardar_contacto(update: Update, context: CallbackContext, nombre: str, telefono: str) -> int:
    from bot.handlers.shared import pedir_fotos_generales
    context.user_data["contact_nombre"] = nombre
    context.user_data["contact_telefono"] = telefono
    context.user_data["contact"] = f"{nombre} {telefono}"
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
        update.message.reply_text("⚠️ Escribí el nombre del encargado (ej: Daniel). Es obligatorio.")
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
                                  "(ej: 1135456067 o 2214567890). Es obligatorio.")
        return CONTACT_PHONE
    push_state(context, CONTACT_PHONE)
    return _guardar_contacto(update, context, context.user_data.get("contact_nombre", ""), telefono)
