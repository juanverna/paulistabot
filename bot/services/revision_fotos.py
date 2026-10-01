"""
revision_fotos.py
-----------------
Revisa en segundo plano cada foto de reparación con vision_service y, al cerrar el paso,
decide si cada ítem declarado (tapa de acceso, tapa de inspección, marco, revoque...)
tiene sus fotos.

python-telegram-bot 13 atiende los mensajes de a uno: si el handler esperara a la IA,
todos los operarios quedarían frenados, y con run_async las fotos de un álbum que llegan
mientras se analiza la anterior se pierden. Por eso el handler registra la foto, contesta
enseguida y la manda a revisar acá; el resultado se le avisa al operario respondiendo a
esa foto (con botón para corregir a qué ítem corresponde). Recién al escribir "Listo" se
esperan las revisiones pendientes (con tope) y se evalúan los ítems.

Cada foto es un dict en user_data["fotos_reparaciones"][sufijo]:
  {"pid", "file_id", "message_id", "estado", "analisis", "calidad", "candidatos",
   "grupo", "grupo_ia", "corregida", "huella"}
Estados: pendiente, validada, sin_validar, calidad, no_respalda, no_corresponde, a_confirmar.
Las "no_corresponde" se sacan de la lista y pasan a user_data["fotos_descartadas"].
"""

import os
import logging
import threading
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor, wait

from telegram import ParseMode, InlineKeyboardButton, InlineKeyboardMarkup

from bot.services import vision_service
from bot.services.items_reparacion import etiqueta, ETIQUETAS, VARIANTES
from bot.utils.helpers import apply_bold_keywords

logger = logging.getLogger(__name__)

PENDIENTE      = "pendiente"
VALIDADA       = "validada"
SIN_VALIDAR    = "sin_validar"
CALIDAD        = "calidad"
NO_RESPALDA    = "no_respalda"
NO_CORRESPONDE = "no_corresponde"
A_CONFIRMAR    = "a_confirmar"

# Estados con los que una foto cuenta para su ítem (sin_validar: la IA falló, no se traba al operario)
ACEPTADAS = (VALIDADA, SIN_VALIDAR)

TEXTO_CALIDAD = {"borrosa": "borrosa", "oscura": "oscura", "muy_lejos": "muy de lejos"}

# Fotos casi idénticas (reenviada, ráfaga): distancia de huella hasta este valor
UMBRAL_HUELLA = int(os.getenv("PHASH_THRESHOLD", "8"))

# Elemento que ve la IA → ítems que puede respaldar, en orden de preferencia
CANDIDATOS = {
    "tapa_acceso":     ["tapa_acceso", "tapa_marco", "tapa"],
    "tapa_inspeccion": ["tapa_inspeccion", "tapa"],
    "marco":           ["marco", "tapa_marco"],
    "pared_revoque":   ["revoque"],
    "flotante":        ["flotante"],
    "automatico":      ["automatico"],
    "piso":            [],
    "otro":            [],
}
GRUPOS_TAPA = ("tapa_acceso", "tapa_inspeccion", "tapa_marco", "tapa")

# Lo que la IA vio, para explicarle al operario por qué una foto no corresponde
PARECE = {
    "tapa_acceso":     "una tapa de acceso",
    "tapa_inspeccion": "una tapa de inspección",
    "marco":           "un marco",
    "pared_revoque":   "una pared o revoque",
    "piso":            "el piso del tanque",
    "flotante":        "un flotante",
    "automatico":      "un automático",
}

NOMBRE = {
    "tapa_inspeccion": "la tapa de inspección",
    "tapa_acceso":     "la tapa de acceso",
    "tapa_marco":      "la tapa y marco de acceso",
    "marco":           "el marco",
    "tapa":            "la tapa",
    "revoque":         "el revoque",
    "flotante":        "el flotante",
    "automatico":      "el automático",
    "otras":           "las reparaciones",
}

_executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vision")
_lock     = threading.Lock()
_pendientes = {}  # chat_id → lista de futures


# =============================================================================
# Clasificación de una foto
# =============================================================================
def candidatos(analisis: dict, items: dict) -> list:
    """Ítems declarados que puede respaldar la foto según lo que vio la IA."""
    elemento = analisis["elemento_detectado"]
    cands = [g for g in CANDIDATOS.get(elemento, []) if g in items]
    if "otras" in items and analisis["coincide_con_lo_declarado"]:
        cands.append("otras")
    return cands


def clasificar(analisis, items: dict) -> dict:
    """Estado de la foto a partir del análisis (None = sin validar) y los ítems declarados."""
    if not analisis:
        return {"estado": SIN_VALIDAR, "calidad": None, "candidatos": None}
    cands = candidatos(analisis, items)
    if analisis["calidad_foto"] != "buena":
        return {"estado": CALIDAD, "calidad": analisis["calidad_foto"], "candidatos": cands}
    # La IA no sabe si es de acceso o de inspección: no se adivina, decide el operario (salvo que
    # se haya declarado "tapa" a secas, donde cualquiera sirve). Su respuesta queda como etiqueta.
    es_tapa = analisis["elemento_detectado"] in ("tapa_acceso", "tapa_inspeccion")
    tapas_con_tipo = [g for g in items if g in ("tapa_acceso", "tapa_inspeccion", "tapa_marco")]
    if es_tapa and not analisis["tipo_tapa_seguro"] and tapas_con_tipo:
        return {"estado": A_CONFIRMAR, "calidad": None,
                "candidatos": [g for g in items if g in GRUPOS_TAPA]}
    if not cands:
        return {"estado": NO_CORRESPONDE, "calidad": None, "candidatos": []}
    # El flotante y el automático suelen fallar sin daño visible (no cortan el agua, no prenden la
    # bomba): para ellos alcanza con que la foto los muestre
    sin_dano_visible = all(g in ("flotante", "automatico") for g in cands)
    if not analisis["respalda_la_reparacion"] and not sin_dano_visible:
        return {"estado": NO_RESPALDA, "calidad": None, "candidatos": cands}
    return {"estado": VALIDADA, "calidad": None, "candidatos": cands}


# =============================================================================
# Mensajes y botones
# =============================================================================
def datos_boton(sufijo: str, pid: int, accion: str) -> str:
    return f"rf:{sufijo}:{pid}:{accion}"


def teclado_grupos(sufijo: str, pid: int, items: dict, con_otra: bool = True) -> InlineKeyboardMarkup:
    filas = [[InlineKeyboardButton(etiqueta(g), callback_data=datos_boton(sufijo, pid, f"g:{g}"))]
             for g in items]
    if con_otra:
        filas.append([InlineKeyboardButton("Otra cosa", callback_data=datos_boton(sufijo, pid, "g:otra"))])
    return InlineKeyboardMarkup(filas)


def mensaje_resultado(foto: dict, sufijo: str, tanque: str, items: dict, trabado: bool):
    """(texto, teclado) para avisarle al operario el resultado de una foto. (None, None) = nada."""
    estado, pid = foto["estado"], foto["pid"]
    grupo  = (foto.get("candidatos") or [None])[0]
    nombre = NOMBRE.get(grupo, "")
    cambiar = InlineKeyboardMarkup([[InlineKeyboardButton(
        "Cambiar", callback_data=datos_boton(sufijo, pid, "c"))]])
    seguir = "\nEscribí <b>Listo</b> para seguir." if trabado else ""

    if estado == CALIDAD:
        de = f" de {nombre}" if nombre else ""
        return (f"⚠️ Esta foto{de} salió {TEXTO_CALIDAD.get(foto['calidad'], foto['calidad'])}. "
                "Si tenés otra del mismo lugar, mandala."), None
    if estado == NO_CORRESPONDE:
        visto = PARECE.get((foto.get("analisis") or {}).get("elemento_detectado"))
        motivo = (f"parece {visto} y eso no está en las reparaciones que pusiste para {tanque}" if visto
                  else f"no coincide con las reparaciones que pusiste para {tanque}")
        return (f"⚠️ Esta foto {motivo}. "
                "La saco de acá: mandala después con las fotos generales."), \
            InlineKeyboardMarkup([[InlineKeyboardButton(
                "Sí es de las reparaciones", callback_data=datos_boton(sufijo, pid, "c"))]])
    if estado == NO_RESPALDA:
        return (f"⚠️ Esta foto no muestra bien el daño de {nombre or 'las reparaciones'}. "
                "Si tenés otra, mandala."), None
    if estado == A_CONFIRMAR:
        tapas = {g: i for g, i in items.items() if g in GRUPOS_TAPA}  # en el orden que las escribió
        return ("❓ No estoy seguro de qué tapa es esta foto. ¿Es alguna de estas?",
                teclado_grupos(sufijo, pid, tapas))
    if estado == VALIDADA:
        sin_tapa = " (falta la tapa propiamente dicha)" if (foto.get("analisis") or {}).get("tapa_faltante") else ""
        return f"📷 {etiqueta(grupo)}{sin_tapa} ✅{seguir}", cambiar
    if trabado:  # sin validar (la IA no respondió) mientras el paso está trabado
        return f"📷 Foto recibida.{seguir}", None
    return None, None


# =============================================================================
# Revisión en segundo plano
# =============================================================================
def _descargar(bot, file_id: str) -> bytes:
    bio = BytesIO()
    bot.get_file(file_id).download(out=bio)
    return bio.getvalue()


def _revisar(bot, chat_id, user_data, sufijo, foto, tanque, reparacion, items):
    try:
        data = _descargar(bot, foto["file_id"])
        foto["huella"] = vision_service.huella(data)
        texto_items = ", ".join(etiqueta(g, i["cantidad"]) for g, i in items.items())
        analisis = vision_service.analizar_foto(data, tanque, reparacion, texto_items)
    except Exception as e:
        logger.warning("Revisión de foto falló (%s): queda sin validar", e)
        analisis = None
    resultado = clasificar(analisis, items)
    # Para poder revisar después qué respondió la IA (sin datos del cliente)
    a = analisis or {}
    logger.info("Visión: foto %s de %s → %s | elemento=%s seguro=%s respalda=%s calidad=%s | %s",
                foto.get("pid"), tanque, resultado["estado"], a.get("elemento_detectado"),
                a.get("tipo_tapa_seguro"), a.get("respalda_la_reparacion"), a.get("calidad_foto"),
                a.get("comentario", ""))

    with _lock:
        if foto.get("cerrada"):
            return  # el paso ya siguió sin esperar este resultado
        foto.update(resultado, analisis=analisis)
        foto["grupo_ia"] = (resultado["candidatos"] or [None])[0]
        if resultado["estado"] == NO_CORRESPONDE:
            _descartar(user_data, sufijo, foto)
        ctx = user_data.get("rep_fotos") or {}
        trabado = bool(ctx.get("trabado")) and ctx.get("sufijo") == sufijo
        texto, teclado = mensaje_resultado(foto, sufijo, tanque, items, trabado)

    if texto:
        try:
            bot.send_message(chat_id=chat_id, text=apply_bold_keywords(texto), parse_mode=ParseMode.HTML,
                             reply_markup=teclado, reply_to_message_id=foto.get("message_id"),
                             allow_sending_without_reply=True)
        except Exception as e:
            logger.error("No se pudo avisar el resultado de la foto: %s", e)


def _descartar(user_data, sufijo, foto):
    """Saca la foto de su apartado (se llama con _lock tomado)."""
    fotos = user_data.get("fotos_reparaciones", {}).get(sufijo, [])
    if foto in fotos:
        fotos.remove(foto)
    user_data.setdefault("fotos_descartadas", []).append(dict(foto, sufijo=sufijo))


def enviar_a_revisar(bot, chat_id, user_data, sufijo, foto, tanque, reparacion, items) -> None:
    foto["estado"] = PENDIENTE
    futuro = _executor.submit(_revisar, bot, chat_id, user_data, sufijo, foto, tanque, reparacion, items)
    with _lock:
        lista = [f for f in _pendientes.get(chat_id, []) if not f.done()]
        lista.append(futuro)
        _pendientes[chat_id] = lista


def hay_pendientes(chat_id) -> bool:
    with _lock:
        return any(not f.done() for f in _pendientes.get(chat_id, []))


def esperar(chat_id, fotos: list, timeout: float) -> None:
    """Espera las revisiones pendientes del chat; las que no terminan a tiempo quedan sin validar."""
    with _lock:
        futuros = list(_pendientes.get(chat_id, []))
    wait(futuros, timeout=timeout)
    with _lock:
        for foto in fotos:
            if foto.get("estado") == PENDIENTE:
                foto.update({"estado": SIN_VALIDAR, "cerrada": True, "candidatos": None})
        _pendientes[chat_id] = [f for f in _pendientes.get(chat_id, []) if not f.done()]


def instantanea(fotos: list) -> list:
    """Copia de las fotos tomada con el lock (el hilo de revisión las modifica)."""
    with _lock:
        return [dict(f) for f in fotos]


def resumen(fotos: list) -> dict:
    """Cantidad de fotos por estado."""
    with _lock:
        cuenta = {}
        for foto in fotos:
            estado = foto.get("estado", SIN_VALIDAR) if isinstance(foto, dict) else SIN_VALIDAR
            cuenta[estado] = cuenta.get(estado, 0) + 1
        return cuenta


# =============================================================================
# Corrección del operario (botones)
# =============================================================================
def aplicar_correccion(user_data: dict, sufijo: str, pid: int, grupo: str):
    """
    El operario dice a qué ítem corresponde la foto (grupo) u "otra" (no es de las reparaciones).
    Devuelve la foto corregida, o None si no se encontró.
    """
    with _lock:
        fotos = user_data.get("fotos_reparaciones", {}).setdefault(sufijo, [])
        descartadas = user_data.get("fotos_descartadas", [])
        foto = next((f for f in fotos if f.get("pid") == pid), None)
        if foto is None:
            previa = next((f for f in descartadas if f.get("pid") == pid and f.get("sufijo") == sufijo), None)
            if previa is None:
                return None
            if grupo == "otra":
                return previa
            # Estaba descartada y el operario dice que sí es de las reparaciones: vuelve
            descartadas.remove(previa)
            foto = {k: v for k, v in previa.items() if k != "sufijo"}
            fotos.append(foto)
        foto["corregida"] = True
        if grupo == "otra":
            foto.update({"estado": NO_CORRESPONDE, "candidatos": []})
            _descartar(user_data, sufijo, foto)
            return foto
        foto["candidatos"] = [grupo]
        if foto.get("estado") == A_CONFIRMAR:
            # El operario dijo qué tapa es; lo que la IA vio del daño sigue valiendo
            respalda = (foto.get("analisis") or {}).get("respalda_la_reparacion", True)
            foto["estado"] = VALIDADA if respalda else NO_RESPALDA
        elif foto.get("estado") in (NO_CORRESPONDE, PENDIENTE):
            foto["estado"] = VALIDADA  # el operario contradice a la IA: queda marcada como corregida
        return foto


# =============================================================================
# Evaluación de los ítems al escribir "Listo"
# =============================================================================
def _asignar(fotos: list, items: dict) -> dict:
    """Reparte las fotos aceptadas entre los ítems (primero las que tienen un solo candidato)."""
    asignadas = {g: [] for g in items}
    aceptadas = [f for f in fotos if f.get("estado") in ACEPTADAS]
    aceptadas.sort(key=lambda f: len(f.get("candidatos") or items))
    for foto in aceptadas:
        cands = [g for g in (foto.get("candidatos") or list(items)) if g in items]
        if not cands:
            continue
        # al ítem al que más fotos le faltan
        grupo = max(cands, key=lambda g: items[g]["cantidad"] - len(asignadas[g]))
        foto["grupo"] = grupo
        asignadas[grupo].append(foto)
    return asignadas


def _distintas(bot, fotos: list, grupo: str, item: dict, tanque: str, cache: dict) -> tuple:
    """(objetos distintos, si se pudo verificar) entre las fotos de un ítem que pide varias."""
    # 1) Fotos casi idénticas cuentan una sola vez
    representantes = []
    for foto in fotos:
        h = foto.get("huella")
        if h is not None and any(r.get("huella") is not None and
                                 vision_service.distancia(h, r["huella"]) <= UMBRAL_HUELLA
                                 for r in representantes):
            continue
        representantes.append(foto)
    if len(representantes) < 2:
        return len(representantes), True
    # 2) La IA dice cuántos objetos físicos distintos hay
    clave = (grupo, tuple(sorted(f["pid"] for f in representantes)))
    if clave not in cache:
        try:
            datos = [_descargar(bot, f["file_id"]) for f in representantes]
            objetos = vision_service.agrupar_objetos(datos, ETIQUETAS[grupo], tanque, item["cantidad"])
        except Exception as e:
            logger.warning("No se pudo agrupar las fotos de %s: %s", grupo, e)
            objetos = None
        cache[clave] = objetos
    objetos = cache[clave]
    if objetos is None:
        return len(representantes), False  # la IA no respondió: no se traba al operario
    return len(set(objetos)), True


def evaluar(bot, user_data: dict, sufijo: str, tanque: str, items: dict, cache: dict) -> dict:
    """
    Estado de cada ítem: {grupo: {"requeridas", "fotos", "distintas", "verificado", "ok",
    "motivo", "texto"}}. motivo/texto explican por qué falta (para el destrabe).
    """
    from bot.services import destrabe
    fotos = user_data.get("fotos_reparaciones", {}).get(sufijo, [])
    with _lock:
        asignadas = _asignar(fotos, items)
        todas = [dict(f) for f in fotos]
    resultado = {}
    for grupo, item in items.items():
        propias = asignadas[grupo]
        requeridas = item["cantidad"]
        if requeridas > 1 and len(propias) > 1:
            distintas, verificado = _distintas(bot, propias, grupo, item, tanque, cache)
        else:
            distintas, verificado = len(propias), True
        estado = {"requeridas": requeridas, "fotos": len(propias), "distintas": min(distintas, len(propias)),
                  "verificado": verificado, "ok": distintas >= requeridas, "motivo": None, "texto": None}
        nombre = NOMBRE[grupo]
        if not estado["ok"]:
            malas = [f for f in todas if grupo in (f.get("candidatos") or [])]
            calidades = [f["calidad"] for f in malas if f.get("estado") == CALIDAD]
            variantes = [VARIANTES[v] for v in dict.fromkeys(item.get("variantes", [])) if v in VARIANTES]
            if not propias and calidades:
                estado["motivo"] = destrabe.MOTIVO_CALIDAD_BAJA
                estado["texto"] = (f"La foto de {nombre} salió "
                                   f"{TEXTO_CALIDAD.get(calidades[-1], calidades[-1])}")
            elif not propias and any(f.get("estado") == NO_RESPALDA for f in malas):
                estado["motivo"] = destrabe.MOTIVO_NO_RESPALDA
                estado["texto"] = f"La foto no muestra bien el daño de {nombre}"
            elif propias and len(propias) >= requeridas:
                estado["motivo"] = destrabe.MOTIVO_FOTO_FALTANTE
                cuales = f" ({' y '.join(variantes)})" if len(variantes) > 1 else ""
                estado["texto"] = (f"Pusiste {requeridas} de {ETIQUETAS[grupo].lower()}{cuales}, "
                                   f"pero las fotos muestran {distintas}: falta la foto de la otra")
            else:
                estado["motivo"] = destrabe.MOTIVO_FOTO_FALTANTE
                faltan = requeridas - distintas
                estado["texto"] = (f"Falta la foto de {nombre}" if requeridas == 1 else
                                   f"Faltan {faltan} foto(s) de {ETIQUETAS[grupo].lower()} "
                                   f"(pusiste {requeridas} distintas)")
        resultado[grupo] = estado
    return resultado


def texto_checklist(tanque: str, estados: dict) -> str:
    lineas = [f"📋 Reparaciones de {tanque}:"]
    for grupo, e in estados.items():
        if e["ok"]:
            detalle = f"{e['fotos']} foto(s)"
            if e["requeridas"] > 1:
                detalle = f"{e['distintas']} de {e['requeridas']}, {detalle}"
            lineas.append(f"✅ {ETIQUETAS[grupo]} ({detalle})")
        else:
            lineas.append(f"❌ {ETIQUETAS[grupo]}: {e['distintas']} de {e['requeridas']}")
    return "\n".join(lineas)
