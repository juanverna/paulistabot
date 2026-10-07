"""
fotos_reparaciones.py
---------------------
Paso de fotos de las reparaciones de cada tanque (Limpieza y Presupuestos).

Después de que el operario escribe las reparaciones de un tanque, el bot saca los ítems
de ese texto (bot/services/items_reparacion.py: tapa de acceso, tapa de inspección,
marco, revoque...) y le pide una foto de cada uno; si hay que cambiar 2 tapas de acceso,
2 fotos de 2 tapas distintas. Puede mandar varias fotos, en el orden que quiera.

Cada foto se revisa con IA en segundo plano (bot/services/revision_fotos.py): el bot le
responde a qué ítem la asignó (con botón para corregirla), si no coincide con lo declarado
(se saca del apartado), o si salió mal o no muestra el daño.

Al escribir "Listo" se evalúa cada ítem. Si todos tienen sus fotos, sigue; si no, muestra
qué falta y el paso queda trabado hasta que mande las fotos que faltan o ingrese el código
diario del encargado (ver bot/services/destrabe.py), que queda registrado por ítem.

Las fotos quedan en user_data["fotos_reparaciones"][sufijo] (sufijo: main/alt1/alt2),
como dicts con file_id, estado, ítem y análisis; los ítems y su estado final en
user_data["items_reparacion"][sufijo].
"""

import re
import logging
import unicodedata
from telegram import Update, ParseMode
from telegram.ext import CallbackContext, ConversationHandler

from bot.states import (REPAIR_PHOTOS, SUGGESTIONS_MAIN, SUGGESTIONS_ALT1, SUGGESTIONS_ALT2)
from bot.utils.helpers import apply_bold_keywords
from bot.handlers.common import (push_state, back_handler, check_special_commands, terminar_edicion,
                                 teclado_atras)
from bot.services import destrabe, revision_fotos, vision_service
from bot.services.items_reparacion import (detectar_items, lista_para_operario, etiqueta,
                                           problemas_de_reparaciones)

logger = logging.getLogger(__name__)

# sufijo → (clave de reparaciones en user_data, clave del nombre del tanque)
TANQUES = {
    "main": ("repairs",     "selected_category"),
    "alt1": ("repair_alt1", "alternative_1"),
    "alt2": ("repair_alt2", "alternative_2"),
}

# Paso siguiente en el flujo manual: sugerencias del mismo tanque
SIGUIENTE_MANUAL = {
    "main": (SUGGESTIONS_MAIN, "selected_category"),
    "alt1": (SUGGESTIONS_ALT1, "alternative_1"),
    "alt2": (SUGGESTIONS_ALT2, "alternative_2"),
}

AYUDA_CODIGO = "🔑 Si no tenés otra foto, pedile al encargado el código de hoy y escribilo acá."

_SIN_REPARACIONES = re.compile(
    r"(no|nada|ninguna|ninguno|-|n/?a|no aplica|sin reparacion(es)?"
    r"|no (tiene|hay|requiere|necesita|lleva)( reparacion(es)?| nada)?"
    r"|ninguna reparacion|no hay que reparar nada)"
)


def _normalizar(texto: str) -> str:
    sin_tildes = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", sin_tildes.lower()).strip(" .!,;")


# Para tolerar errores de tipeo en UNA palabra ("ningana", "nimguna", "nadaa"). En frases no:
# "no hay tapa" se parece a "no hay nada" y significa lo contrario (hay que colocarla).
_PALABRAS_SIN_REPARACIONES = ("ninguna", "ninguno", "nada")


def necesita_fotos(reparaciones) -> bool:
    """True si el texto de reparaciones describe alguna reparación."""
    import difflib
    if not reparaciones or not str(reparaciones).strip():
        return False
    normal = _normalizar(str(reparaciones))
    if _SIN_REPARACIONES.fullmatch(normal):
        return False
    # Una sola palabra parecida a "ninguna" o "nada" (con errores de tipeo)
    if " " not in normal and difflib.get_close_matches(normal, _PALABRAS_SIN_REPARACIONES, n=1, cutoff=0.8):
        return False
    return True


def _nombre_tanque(context: CallbackContext, sufijo: str) -> str:
    return context.user_data.get(TANQUES[sufijo][1], "").capitalize()


def _reparacion(context: CallbackContext, sufijo: str) -> str:
    return context.user_data.get(TANQUES[sufijo][0], "") or ""


def _reparacion_en_palabras(context: CallbackContext, sufijo: str) -> str:
    """Para la IA de fotos: "TCEA F COMP" no le dice nada; "Revoque frente (entrada de agua)..." sí."""
    from bot.services.campos import legible
    return ", ".join(legible(i) for i in _reparacion(context, sufijo).split(", ") if i)


def _fotos(context: CallbackContext, sufijo: str) -> list:
    return context.user_data.setdefault("fotos_reparaciones", {}).setdefault(sufijo, [])


def _items(context: CallbackContext, sufijo: str) -> dict:
    return context.user_data.get("items_reparacion", {}).get(sufijo, {}).get("items", {})


def _send(update: Update, context: CallbackContext, text: str, atras: bool = False):
    return context.bot.send_message(
        chat_id=update.effective_chat.id,
        text=apply_bold_keywords(text),
        reply_markup=teclado_atras() if atras else None,
        parse_mode=ParseMode.HTML,
    )


def texto_pedido(context: CallbackContext, sufijo: str) -> str:
    items = _items(context, sufijo)
    return (f"📷 Mandá una foto de cada reparación de {_nombre_tanque(context, sufijo)}:\n"
            f"{lista_para_operario(items)}\n\n"
            "Podés mandar varias. Cuando termines, escribí <b>Listo</b>.")


def _preparar(context: CallbackContext, sufijo: str, modo: str) -> None:
    items = detectar_items(_reparacion(context, sufijo))
    context.user_data.setdefault("items_reparacion", {})[sufijo] = {"items": items, "estado": None}
    context.user_data["rep_fotos"] = {"sufijo": sufijo, "modo": modo, "trabado": False,
                                      "distincion": {}}


def pedir_fotos(update: Update, context: CallbackContext, sufijo: str, modo: str) -> int:
    """
    Arranca el paso de fotos de reparaciones de un tanque.
    modo: "manual" (sigue con sugerencias; es el único que queda).
    """
    _preparar(context, sufijo, modo)
    context.user_data["current_state"] = REPAIR_PHOTOS
    # Códigos mal escritos, de otro tanque (ej: TITREA en la cisterna) o texto que no es ningún
    # ítem conocido: no se deja pasar, hay que corregirlo
    corregir = problemas_de_reparaciones(_reparacion(context, sufijo),
                                         context.user_data.get(TANQUES[sufijo][1]))
    if corregir:
        context.user_data["rep_fotos"]["corregir_codigos"] = True
        _send(update, context, corregir)
        return REPAIR_PHOTOS
    _send(update, context, texto_pedido(context, sufijo), atras=True)
    return REPAIR_PHOTOS


def _corregir_codigos(update: Update, context: CallbackContext, ctx: dict, text: str) -> int:
    """El operario reescribió las reparaciones que el bot no entendió."""
    sufijo = ctx["sufijo"]
    normal = _normalizar(text)
    if normal == "listo" or normal.startswith("no tengo") or destrabe.parece_codigo(text):
        update.message.reply_text("Primero escribí de nuevo las reparaciones con el código correcto.")
        return REPAIR_PHOTOS
    if not necesita_fotos(text):  # "No", "ninguna"...: no hay reparaciones en este tanque
        context.user_data[TANQUES[sufijo][0]] = text
        # Los ítems eran del texto rechazado: si quedan, el informe pide su foto
        context.user_data.get("items_reparacion", {}).pop(sufijo, None)
        return _continuar(update, context)
    corregir = problemas_de_reparaciones(text, context.user_data.get(TANQUES[sufijo][1]))
    if corregir:
        _send(update, context, corregir)
        return REPAIR_PHOTOS
    context.user_data[TANQUES[sufijo][0]] = text
    if not necesita_fotos(text):
        return _continuar(update, context)
    return pedir_fotos(update, context, sufijo, ctx.get("modo", "manual"))


def reanudar_manual(update: Update, context: CallbackContext, sufijo: str) -> None:
    """Vuelve a este paso con "atrás" desde sugerencias (flujo manual). Las fotos se conservan."""
    _preparar(context, sufijo, "manual")
    n = len(_fotos(context, sufijo))
    extra = f"\nYa tenés {n} foto(s) cargada(s)." if n else ""
    _send(update, context, texto_pedido(context, sufijo) + extra, atras=True)


def _continuar(update: Update, context: CallbackContext) -> int:
    ctx = context.user_data.pop("rep_fotos", {})
    sufijo = ctx.get("sufijo", "main")
    hechos = context.user_data.setdefault("fotos_reparaciones_hechas", [])
    if sufijo not in hechos:
        hechos.append(sufijo)

    push_state(context, REPAIR_PHOTOS)
    fin = terminar_edicion(update, context)
    if fin is not None:
        return fin
    siguiente, clave_nombre = SIGUIENTE_MANUAL[sufijo]
    nombre = context.user_data.get(clave_nombre, "").capitalize()
    _send(update, context, f"Indique sugerencias p/ la próx limpieza para {nombre}:", atras=True)
    context.user_data["current_state"] = siguiente
    return siguiente


def _trabar(update: Update, context: CallbackContext, ctx: dict, faltantes: dict, corregidas: list) -> int:
    """
    Traba el paso hasta que mande las fotos que faltan o el encargado dé el código.
    faltantes = {grupo: estado del ítem} sin sus fotos; corregidas = fotos donde el operario
    contradijo a la IA (piden el código aunque ya estén todas).
    """
    ctx["trabado"] = True
    ctx["faltantes"] = {g: e["motivo"] for g, e in faltantes.items()}
    ctx["correcciones"] = [{"grupo": f["candidatos"][0], "texto": revision_fotos.texto_correccion(f)}
                           for f in corregidas]
    partes = []
    if faltantes:
        partes.append(destrabe.mensaje_trabado(". ".join(e["texto"] for e in faltantes.values())))
    if corregidas:
        detalle = "; ".join(c["texto"] for c in ctx["correcciones"])
        n = len(corregidas)
        partes.append((f"Corregiste {n} foto que la IA reconoció distinto" if n == 1 else
                       f"Corregiste {n} fotos que la IA reconoció distinto") +
                      f" ({detalle}). Como hubo corrección, para seguir hace falta el código del encargado"
                      + ("." if faltantes else ", aunque ya estén todas las fotos."))
    texto = "⚠️ " + "\n\n".join(partes) + "\n\n" + (
        AYUDA_CODIGO if faltantes else "🔑 Pedile al encargado el código de hoy y escribilo acá.")
    # Si ya había un aviso de trabado, queda marcado como viejo: vale el nuevo
    anterior = ctx.pop("msg_trabado", None)
    if anterior:
        try:
            context.bot.edit_message_text(chat_id=update.effective_chat.id, message_id=anterior,
                                          text="ℹ️ Este aviso se actualizó: mirá el de más abajo.")
        except Exception:  # muy viejo o igual: no importa
            pass
    mensaje = _send(update, context, texto)
    ctx["msg_trabado"] = getattr(mensaje, "message_id", None)
    return REPAIR_PHOTOS


def _evaluar_y_decidir(update: Update, context: CallbackContext, ctx: dict) -> int:
    """Evalúa los ítems con las fotos que hay: sigue, o traba (fotos faltantes o corregidas)."""
    sufijo = ctx["sufijo"]
    items = _items(context, sufijo)
    estados = revision_fotos.evaluar(context.bot, context.user_data, sufijo,
                                     _nombre_tanque(context, sufijo), items, ctx.setdefault("distincion", {}))
    context.user_data["items_reparacion"][sufijo]["estado"] = estados
    if len(items) > 1 or any(e["requeridas"] > 1 for e in estados.values()):
        _send(update, context, revision_fotos.texto_checklist(_nombre_tanque(context, sufijo), estados))

    faltantes = {g: e for g, e in estados.items() if not e["ok"]}
    corregidas = revision_fotos.corregidas(revision_fotos.instantanea(_fotos(context, sufijo)))
    if not faltantes and not corregidas:
        if ctx.get("trabado"):  # se destrabó solo (ej: deshizo la corrección)
            ctx["trabado"] = False
            if update.message is None:  # vino de un botón: hay que escribir Listo para seguir
                _send(update, context, "✅ Ya está todo. Escribí <b>Listo</b> para seguir.")
                return REPAIR_PHOTOS
        return _continuar(update, context)
    return _trabar(update, context, ctx, faltantes, corregidas)


def _cerrar_paso(update: Update, context: CallbackContext, ctx: dict) -> int:
    """"Listo": espera las revisiones pendientes y evalúa si cada ítem tiene sus fotos."""
    sufijo  = ctx["sufijo"]
    chat_id = update.effective_chat.id
    if revision_fotos.hay_pendientes(chat_id):
        update.message.reply_text("⏳ Estoy revisando las fotos, un momento...")
    revision_fotos.esperar(chat_id, _fotos(context, sufijo),
                           timeout=vision_service.VISION_TIMEOUT_S + 10)

    fotos = revision_fotos.instantanea(_fotos(context, sufijo))
    if any(f.get("estado") == revision_fotos.A_CONFIRMAR for f in fotos):
        update.message.reply_text("❓ Antes de seguir, decime de cuál tapa es cada foto marcada "
                                  "con ❓ (tocá el botón en esa foto).")
        return REPAIR_PHOTOS
    return _evaluar_y_decidir(update, context, ctx)


def _es_imagen(update: Update) -> bool:
    if update.message.photo:
        return True
    doc = update.message.document
    return bool(doc and (doc.mime_type or "").startswith("image/"))


def _file_id(update: Update) -> str:
    if update.message.photo:
        return update.message.photo[-1].file_id
    return update.message.document.file_id


def handle_repair_photos(update: Update, context: CallbackContext) -> int:
    ctx = context.user_data.get("rep_fotos")
    if not ctx:
        # No debería pasar: sin contexto no sabemos de qué tanque es
        logger.warning("REPAIR_PHOTOS sin contexto")
        return back_handler(update, context)
    sufijo = ctx["sufijo"]

    # ---------- Fotos ----------
    if update.message.photo or update.message.document:
        if ctx.get("corregir_codigos"):
            update.message.reply_text("Primero corregí el código de las reparaciones (escribilas de nuevo).")
            return REPAIR_PHOTOS
        if not _es_imagen(update):
            update.message.reply_text("Eso no es una foto. Mandá una foto de la galería.")
            return REPAIR_PHOTOS
        fotos = _fotos(context, sufijo)
        pid = context.user_data["foto_pid"] = context.user_data.get("foto_pid", 0) + 1
        foto = {"pid": pid, "file_id": _file_id(update), "message_id": update.message.message_id}
        fotos.append(foto)
        # Se revisa con IA en segundo plano; si sigue trabado, se destraba en el próximo "Listo"
        revision_fotos.enviar_a_revisar(
            context.bot, update.effective_chat.id, context.user_data, sufijo, foto,
            _nombre_tanque(context, sufijo), _reparacion_en_palabras(context, sufijo), _items(context, sufijo))
        # Un álbum llega como varios mensajes: respondemos una sola vez por álbum
        grupo = update.message.media_group_id
        if grupo and grupo == ctx.get("ultimo_album"):
            return REPAIR_PHOTOS
        ctx["ultimo_album"] = grupo
        recibido = "✅ Fotos recibidas." if grupo else f"✅ Foto recibida (total: {len(fotos)})."
        update.message.reply_text(
            apply_bold_keywords(f"{recibido} Mandá más o escribí <b>Listo</b>."),
            parse_mode=ParseMode.HTML,
        )
        return REPAIR_PHOTOS

    # ---------- Texto ----------
    text = (update.message.text or "").strip()
    if not text:
        update.message.reply_text("Mandá una foto o escribí Listo.")
        return REPAIR_PHOTOS
    if check_special_commands(text, update, context):
        return ConversationHandler.END

    normal = _normalizar(text)
    if normal == "atras":
        return _atras(update, context, sufijo)

    if ctx.get("corregir_codigos"):
        return _corregir_codigos(update, context, ctx, text)

    if ctx.get("trabado") and destrabe.parece_codigo(text):
        resultado = destrabe.intentar_destrabe(context.user_data, text)
        if resultado == destrabe.OK:
            for grupo, motivo in ctx.get("faltantes", {}).items():
                destrabe.registrar_destrabe(context.user_data, _nombre_tanque(context, sufijo),
                                            etiqueta(grupo), motivo or destrabe.MOTIVO_FOTO_FALTANTE)
            for c in ctx.get("correcciones", []):
                destrabe.registrar_destrabe(context.user_data, _nombre_tanque(context, sufijo),
                                            etiqueta(c["grupo"]), f"{destrabe.MOTIVO_CORRECCION} ({c['texto']})")
            update.message.reply_text("✅ Código correcto. Seguimos.")
            return _continuar(update, context)
        if resultado == destrabe.BLOQUEADO:
            update.message.reply_text(destrabe.mensaje_bloqueado())
            return REPAIR_PHOTOS
        update.message.reply_text("❌ Código incorrecto. Pedile el código de hoy al encargado.")
        return REPAIR_PHOTOS

    if normal == "listo" or normal.startswith("no tengo"):
        return _cerrar_paso(update, context, ctx)

    if ctx.get("trabado"):  # "No", "no tengo otra", etc. con el paso trabado
        update.message.reply_text(apply_bold_keywords(AYUDA_CODIGO), parse_mode=ParseMode.HTML)
        return REPAIR_PHOTOS

    update.message.reply_text(
        apply_bold_keywords("Mandá una foto o escribí <b>Listo</b>."),
        parse_mode=ParseMode.HTML,
    )
    return REPAIR_PHOTOS


# =============================================================================
# Botones de las fotos: [Cambiar], "¿De cuál tapa es?", "Sí es de las reparaciones"
# =============================================================================
def _atras(update: Update, context: CallbackContext, sufijo: str) -> int:
    """Vuelve al menú de reparaciones (con lo cargado); las fotos de este tanque se descartan."""
    context.user_data.get("fotos_reparaciones", {}).pop(sufijo, None)
    context.user_data.get("items_reparacion", {}).pop(sufijo, None)
    context.user_data.pop("rep_fotos", None)
    return back_handler(update, context)


def handle_repair_photos_atras(update: Update, context: CallbackContext) -> int:
    """Botón ATRAS del pedido de fotos: lo mismo que escribir "atrás"."""
    query = update.callback_query
    query.answer()
    try:
        query.edit_message_reply_markup(reply_markup=None)
    except Exception:  # el mensaje ya no tenía botones: no importa
        pass
    sufijo = context.user_data.get("rep_fotos", {}).get("sufijo", "main")
    return _atras(update, context, sufijo)


def handle_repair_photo_button(update: Update, context: CallbackContext) -> int:
    query = update.callback_query
    partes = query.data.split(":")  # rf:<sufijo>:<pid>:c  |  rf:<sufijo>:<pid>:g:<grupo>
    ctx = context.user_data.get("rep_fotos")
    if len(partes) < 4 or not ctx or ctx.get("sufijo") != partes[1]:
        query.answer("Ese paso ya terminó.")
        return context.user_data.get("current_state", REPAIR_PHOTOS)
    sufijo, pid, accion = partes[1], int(partes[2]), partes[3]
    items = _items(context, sufijo)
    query.answer()

    if accion == "c":
        query.edit_message_reply_markup(revision_fotos.teclado_grupos(sufijo, pid, items))
        return REPAIR_PHOTOS

    grupo = partes[4] if len(partes) > 4 else ""
    if accion != "g" or (grupo != "otra" and grupo not in items):
        return REPAIR_PHOTOS
    foto = revision_fotos.aplicar_correccion(context.user_data, sufijo, pid, grupo)
    if foto is None:
        query.edit_message_reply_markup(None)
        return REPAIR_PHOTOS
    ctx.get("distincion", {}).clear()  # cambió qué fotos tiene cada ítem
    if grupo == "otra":
        query.edit_message_text("🗑️ La saqué de las reparaciones: mandala después con las fotos generales.")
    else:
        query.edit_message_text(apply_bold_keywords(f"📷 {etiqueta(grupo)} ✅ (corregida)"),
                                parse_mode=ParseMode.HTML)
    if ctx.get("trabado"):
        # El aviso de trabado era de antes de la corrección: se vuelve a evaluar y se avisa de nuevo
        return _evaluar_y_decidir(update, context, ctx)
    return REPAIR_PHOTOS


def handle_boton_vencido(update: Update, context: CallbackContext):
    """Botón de una foto de un paso que ya terminó (cualquier otro estado)."""
    update.callback_query.answer("Ese paso ya terminó.")
    return None
