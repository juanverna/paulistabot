"""
informe_html.py
---------------
Arma el informe en HTML (Limpieza y Reparación de Tanques, Presupuestos) para el mail.

Diseño pensado para clientes de mail (Gmail, Outlook, celular): tablas, estilos en línea y
sin CSS externo ni JavaScript. Las fotos van embebidas por Content-ID (cid:) y achicadas,
para que el mail pese poco.

Orden: encabezado con los datos del servicio → resumen de alertas → una sección por tanque
con sus datos y cada reparación con su foto al lado (y el estado: validado, alerta, falta
foto, destrabado por el encargado) → fotos generales en grilla.
"""

import io
import html
import logging
from datetime import datetime

from bot.services.destrabe import HORA_ARGENTINA

logger = logging.getLogger(__name__)

# Cada foto va una sola vez: se muestra chica en el diseño y, como también es adjunto, en Gmail se
# abre grande desde la lista de adjuntos (Gmail no deja linkear una imagen del mail a un adjunto).
LADO_FOTO_PX = 1400

# Paleta
AZUL, AZUL_CLARO, GRIS, GRIS_CLARO, TEXTO = "#0b3d91", "#e8eef9", "#6b7280", "#f3f4f6", "#1f2937"
VERDE, VERDE_FONDO = "#166534", "#dcfce7"
AMBAR, AMBAR_FONDO = "#92400e", "#fef3c7"
ROJO, ROJO_FONDO = "#991b1b", "#fee2e2"
VIOLETA, VIOLETA_FONDO = "#5b21b6", "#ede9fe"


SERVICIOS_CON_INFORME = ("Limpieza y Reparacion de Tanques", "Presupuestos")
NOMBRE_SERVICIO = {"Limpieza y Reparacion de Tanques": "Limpieza y Reparación de Tanques"}


def _e(texto) -> str:
    return html.escape(str(texto or ""))


def achicar(data: bytes):
    """JPEG liviano para embeber. None si no es una imagen."""
    from PIL import Image, ImageOps
    try:
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
    except Exception:
        return None
    img.thumbnail((LADO_FOTO_PX, LADO_FOTO_PX))
    out = io.BytesIO()
    img.save(out, format="JPEG", quality=72, optimize=True)
    return out.getvalue()


# =============================================================================
# Datos
# =============================================================================
def _fotos_de(foto) -> dict:
    """Normaliza una foto (los reportes viejos guardaban solo el file_id)."""
    return foto if isinstance(foto, dict) else {"file_id": foto, "estado": "sin_validar"}


def _grupo(foto: dict):
    return foto.get("grupo") or (foto.get("candidatos") or [None])[0]


def tanques(user_data: dict) -> list:
    """Tanques con datos, en orden: dicts con nombre, datos, reparación, ítems y fotos."""
    from bot.services import tanques_reporte as tq
    resultado = []
    for tanque in tq.lista(user_data):
        sufijo = tanque["id"]
        valor = lambda campo: user_data.get(tq.clave(campo, sufijo))
        datos = [("Medidas", valor("measure")), ("Tapas de inspección", valor("tapas_inspeccion")),
                 ("Tapas de acceso", valor("tapas_acceso")), ("Sellado", valor("sealing")),
                 ("Sugerencias", valor("suggestions"))]
        reparacion = valor("repairs")
        fotos = [_fotos_de(f) for f in user_data.get("fotos_reparaciones", {}).get(sufijo, [])]
        if not any(v for _, v in datos) and not reparacion and not fotos:
            continue
        items = user_data.get("items_reparacion", {}).get(sufijo, {})
        resultado.append({
            "sufijo": sufijo,
            "nombre": tq.nombre(user_data, sufijo),
            "datos": [(k, v) for k, v in datos if v],
            "reparacion": reparacion,
            "items": items.get("items") or {},
            "estado_items": items.get("estado") or {},
            "fotos": fotos,
        })
    return resultado


def alertas(user_data: dict) -> list:
    """[(nivel, texto)] para el resumen de arriba. nivel: rojo, ambar, violeta."""
    from bot.services.items_reparacion import ETIQUETAS
    lista = []
    for d in user_data.get("destrabes", []):
        lista.append(("violeta", f"{d['tanque']} · {d['item']}: destrabado por el encargado "
                                 f"({d['motivo']}) el {d['fecha']} a las {d['hora']}"))
    descartadas = {}
    for f in user_data.get("fotos_descartadas", []):
        descartadas[f.get("sufijo")] = descartadas.get(f.get("sufijo"), 0) + 1
    for t in tanques(user_data):
        nombre, items = t["nombre"], t["items"]
        destrabados = {d["item"] for d in user_data.get("destrabes", []) if d["tanque"] == nombre}
        for grupo, e in t["estado_items"].items():
            etiqueta = ETIQUETAS.get(grupo, grupo)
            if not e.get("ok") and etiqueta not in destrabados:
                lista.append(("rojo", f"{nombre} · {etiqueta}: falta foto ({e.get('distintas', 0)} de "
                                      f"{e.get('requeridas', 1)})"))
            if not e.get("verificado", True):
                lista.append(("ambar", f"{nombre} · {etiqueta}: no se pudo comprobar con IA que las fotos "
                                       "sean de objetos distintos"))
        no_respalda = [f for f in t["fotos"] if f.get("estado") == "no_respalda"]
        for f in no_respalda:
            lista.append(("rojo", f"{nombre} · {ETIQUETAS.get(_grupo(f), 'Reparación')}: la foto no "
                                  "muestra bien el daño (reparación sin respaldo visual)"))
        calidad = sum(1 for f in t["fotos"] if f.get("estado") == "calidad")
        if calidad:
            lista.append(("ambar", f"{nombre}: {calidad} foto(s) oscuras, borrosas o de muy lejos"))
        if descartadas.get(t["sufijo"]):
            lista.append(("ambar", f"{nombre}: {descartadas[t['sufijo']]} foto(s) no coincidían con las "
                                   "reparaciones y se sacaron"))
        corregidas = sum(1 for f in t["fotos"] if f.get("corregida"))
        if corregidas:
            lista.append(("ambar", f"{nombre}: {corregidas} foto(s) asignadas a mano por el operario "
                                   "(la IA vio otra cosa)"))
        sin_validar = sum(1 for f in t["fotos"] if f.get("estado") == "sin_validar")
        if sin_validar:
            lista.append(("ambar", f"{nombre}: {sin_validar} foto(s) sin validar (la IA no respondió)"))
        # Posibles daños no reportados, según lo que la IA vio en las fotos
        if "revoque" not in items and any((f.get("analisis") or {}).get("requiere_revoque") for f in t["fotos"]):
            lista.append(("rojo", f"{nombre}: la IA vio revoque dañado y no está en las reparaciones "
                                  "(posible trabajo sin cotizar)"))
    orden = {"rojo": 0, "violeta": 1, "ambar": 2}
    return sorted(lista, key=lambda a: orden[a[0]])


def _estado_item(grupo: str, e: dict, fotos: list, destrabe) -> tuple:
    """(texto, color, fondo) del indicador de un ítem."""
    if destrabe:
        return "🔓 Destrabado por encargado", VIOLETA, VIOLETA_FONDO
    if e and not e.get("ok"):
        return "✖ Falta foto", ROJO, ROJO_FONDO
    if any(f.get("estado") == "no_respalda" for f in fotos) and not any(
            f.get("estado") == "validada" for f in fotos):
        return "⚠ No muestra el daño", ROJO, ROJO_FONDO
    if any(f.get("corregida") for f in fotos):
        return "✎ Corregido por operario", AMBAR, AMBAR_FONDO
    if fotos and all(f.get("estado") == "sin_validar" for f in fotos):
        return "• Sin validar", AMBAR, AMBAR_FONDO
    if e and not e.get("verificado", True):
        return "• Sin verificar", AMBAR, AMBAR_FONDO
    if fotos:
        return "✔ Validado", VERDE, VERDE_FONDO
    return "✖ Falta foto", ROJO, ROJO_FONDO


# =============================================================================
# HTML
# =============================================================================
def _badge(texto, color, fondo) -> str:
    return (f'<span style="display:inline-block;padding:3px 10px;border-radius:12px;font-size:12px;'
            f'font-weight:bold;color:{color};background:{fondo};">{_e(texto)}</span>')


def _img(foto: tuple, ancho: int, alt: str) -> str:
    """foto = (cid, número de adjunto). Debajo, cómo verla grande."""
    cid, numero = foto
    return (f'<img src="cid:{cid}" width="{ancho}" alt="{_e(alt)}" style="display:block;width:{ancho}px;'
            f'max-width:100%;height:auto;border-radius:6px;border:1px solid #d1d5db;">'
            f'<div style="font-size:11px;color:{GRIS};margin-top:3px;">📎 Foto {numero} · ampliar en adjuntos</div>')


def _fila_dato(clave, valor) -> str:
    return (f'<tr><td style="padding:3px 12px 3px 0;color:{GRIS};font-size:13px;white-space:nowrap;'
            f'vertical-align:top;">{_e(clave)}</td><td style="padding:3px 0;font-size:13px;color:{TEXTO};">'
            f'{_e(valor)}</td></tr>')


def _encabezado(user_data: dict) -> str:
    direccion = user_data.get("address") or user_data.get("direccion_qr") or "Sin dirección"
    horario = " a ".join(h for h in (user_data.get("start_time"), user_data.get("end_time")) if h)
    datos = [("Orden", user_data.get("order") or user_data.get("numero_evento")),
             ("Código cliente", user_data.get("codigo_interno")),
             ("Operario", user_data.get("code")),
             ("Fecha", datetime.now(HORA_ARGENTINA).strftime("%d/%m/%Y")),
             ("Horario", horario),
             ("Contacto", user_data.get("contact")),
             ("Carga", user_data.get("modo_ingreso"))]
    filas = "".join(_fila_dato(k, v) for k, v in datos if v)
    return (f'<tr><td style="background:{AZUL};padding:20px 24px;color:#ffffff;">'
            f'<div style="font-size:12px;letter-spacing:1px;text-transform:uppercase;opacity:.85;">'
            f'Reporte de servicio · {_e(NOMBRE_SERVICIO.get(user_data.get("service"), user_data.get("service", "")))}</div>'
            f'<div style="font-size:22px;font-weight:bold;margin-top:4px;">{_e(direccion)}</div></td></tr>'
            f'<tr><td style="padding:16px 24px;background:{AZUL_CLARO};">'
            f'<table role="presentation" cellpadding="0" cellspacing="0">{filas}</table></td></tr>')


def _resumen_alertas(lista: list) -> str:
    if not lista:
        return (f'<tr><td style="padding:16px 24px;"><div style="padding:12px 14px;border-radius:8px;'
                f'background:{VERDE_FONDO};color:{VERDE};font-size:14px;font-weight:bold;">'
                f'✔ Sin alertas: todas las reparaciones tienen su foto validada.</div></td></tr>')
    colores = {"rojo": (ROJO, ROJO_FONDO), "ambar": (AMBAR, AMBAR_FONDO), "violeta": (VIOLETA, VIOLETA_FONDO)}
    items = "".join(
        f'<tr><td style="padding:6px 10px;border-left:4px solid {colores[n][0]};background:{colores[n][1]};'
        f'color:{colores[n][0]};font-size:13px;">{_e(t)}</td></tr><tr><td style="height:6px;"></td></tr>'
        for n, t in lista)
    return (f'<tr><td style="padding:16px 24px 4px;"><div style="font-size:15px;font-weight:bold;'
            f'color:{TEXTO};margin-bottom:8px;">⚠ Alertas ({len(lista)})</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{items}</table></td></tr>')


def _nota_ia(fotos: list) -> str:
    """Lo que vio la IA en la primera foto con análisis."""
    for f in fotos:
        a = f.get("analisis")
        if a:
            partes = [f"Estado: {a.get('estado')}"] if a.get("estado") else []
            if a.get("tapa_faltante"):
                partes.append("falta la tapa propiamente dicha")
            if a.get("danos_visibles"):
                partes.append(", ".join(a["danos_visibles"]))
            texto = " · ".join(partes)
            comentario = f'<div style="margin-top:2px;">{_e(a.get("comentario"))}</div>' if a.get("comentario") else ""
            return (f'<div style="margin-top:8px;font-size:12px;color:{GRIS};">🤖 IA: {_e(texto)}'
                    f'{comentario}</div>')
    return ""


def _item(grupo, item, e, fotos, destrabe, cids) -> str:
    from bot.services.items_reparacion import ETIQUETAS, VARIANTES
    texto, color, fondo = _estado_item(grupo, e, fotos, destrabe)
    detalle = []
    if item.get("codigos"):
        detalle.append(", ".join(item["codigos"]))
    if item.get("cantidad", 1) > 1:
        variantes = [VARIANTES[v] for v in dict.fromkeys(item.get("variantes", [])) if v in VARIANTES]
        detalle.append(f"{item['cantidad']} unidades" + (f" ({' y '.join(variantes)})" if variantes else ""))
    extra = (f'<div style="font-size:12px;color:{GRIS};margin-top:2px;">{_e(" · ".join(detalle))}</div>'
             if detalle else "")
    nota_destrabe = (f'<div style="font-size:12px;color:{VIOLETA};margin-top:6px;">Motivo: {_e(destrabe["motivo"])}'
                     f' · {_e(destrabe["fecha"])} {_e(destrabe["hora"])}</div>' if destrabe else "")
    izquierda = (f'<div style="font-size:15px;font-weight:bold;color:{TEXTO};">{_e(ETIQUETAS.get(grupo, grupo))}</div>'
                 f'{extra}<div style="margin-top:8px;">{_badge(texto, color, fondo)}</div>'
                 f'{nota_destrabe}{_nota_ia(fotos)}')
    con_foto = [f for f in fotos if f.get("file_id") in cids]
    if con_foto:
        derecha = "".join(
            f'<div style="margin-bottom:6px;">{_img(cids[f["file_id"]], 240, ETIQUETAS.get(grupo, grupo))}</div>'
            for f in con_foto)
    else:
        derecha = (f'<div style="width:240px;max-width:100%;padding:34px 0;text-align:center;border-radius:6px;'
                   f'border:2px dashed {ROJO};color:{ROJO};font-size:13px;background:{ROJO_FONDO};">Sin foto</div>')
    return (f'<tr><td style="padding:12px 0;border-top:1px solid #e5e7eb;">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0"><tr>'
            f'<td style="vertical-align:top;padding-right:10px;">{izquierda}</td>'
            f'<td style="vertical-align:middle;width:28px;font-size:22px;color:{AZUL};text-align:center;">➜</td>'
            f'<td style="vertical-align:top;width:240px;">{derecha}</td></tr></table></td></tr>')


def _seccion_tanque(t: dict, user_data: dict, cids: dict) -> str:
    datos = "".join(_fila_dato(k, v) for k, v in t["datos"])
    destrabes = {d["item"]: d for d in user_data.get("destrabes", []) if d["tanque"] == t["nombre"]}
    from bot.services.items_reparacion import ETIQUETAS
    filas = []
    if t["items"]:
        por_grupo = {g: [] for g in t["items"]}
        sueltas = []
        for f in t["fotos"]:
            (por_grupo[_grupo(f)] if _grupo(f) in por_grupo else sueltas).append(f)
        for grupo, item in t["items"].items():
            filas.append(_item(grupo, item, t["estado_items"].get(grupo), por_grupo[grupo],
                               destrabes.get(ETIQUETAS.get(grupo, grupo)), cids))
        if sueltas:
            filas.append(_item("otras", {"cantidad": 1}, None, sueltas, None, cids))
    elif t["fotos"]:  # reportes sin ítems (antes de la fase 2)
        filas.append(_item("otras", {"cantidad": 1}, None, t["fotos"], None, cids))
    reparacion = (f'<div style="margin:12px 0 4px;font-size:13px;color:{TEXTO};"><b>Reparaciones declaradas:</b> '
                  f'{_e(t["reparacion"])}</div>' if t["reparacion"] else
                  f'<div style="margin:12px 0 4px;font-size:13px;color:{GRIS};">Sin reparaciones declaradas.</div>')
    return (f'<tr><td style="padding:20px 24px 4px;">'
            f'<div style="font-size:17px;font-weight:bold;color:{AZUL};border-bottom:2px solid {AZUL};'
            f'padding-bottom:6px;">🛢 {_e(t["nombre"].upper())}</div>'
            f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin-top:10px;">{datos}</table>'
            f'{reparacion}'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{"".join(filas)}</table>'
            f'</td></tr>')


def _grilla_generales(fotos: list, cids: dict) -> str:
    celdas = [f'<td style="width:33%;padding:6px;vertical-align:top;text-align:center;">'
              f'{_img(cids[fid], 190, "Foto general")}</td>' for fid in fotos if fid in cids]
    if not celdas:
        return ""
    filas = "".join("<tr>" + "".join(celdas[i:i + 3]) + "</tr>" for i in range(0, len(celdas), 3))
    return (f'<tr><td style="padding:20px 24px 8px;"><div style="font-size:17px;font-weight:bold;color:{AZUL};'
            f'border-bottom:2px solid {AZUL};padding-bottom:6px;">📷 Fotos generales</div>'
            f'<div style="font-size:12px;color:{GRIS};margin:6px 0;">Orden de trabajo, ficha y tanques</div>'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0">{filas}</table></td></tr>')


def armar_informe(user_data: dict, descargar) -> tuple:
    """
    Devuelve (html, imagenes). descargar(file_id) → bytes de la foto.
    imagenes: [(cid, jpeg, nombre_archivo)] para embeber en el mail.
    """
    ts = tanques(user_data)
    cids, imagenes = {}, []

    def embeber(file_id, nombre):
        if file_id in cids:
            return
        try:
            jpeg = achicar(descargar(file_id))
        except Exception as e:
            logger.error("No se pudo bajar la foto %s para el informe: %s", nombre, e)
            return
        if jpeg is None:
            return
        numero = len(imagenes) + 1
        cid = f"foto{numero}@paulistabot"
        cids[file_id] = (cid, numero)
        # El número al principio ordena los adjuntos igual que en el diseño
        imagenes.append((cid, jpeg, f"{numero:02d}_{nombre}.jpg"))

    for t in ts:
        for f in t["fotos"]:
            embeber(f["file_id"], f"{t['nombre'].lower()}_{_grupo(f) or 'reparacion'}")
    generales = list(user_data.get("photos", []))
    for fid in generales:
        embeber(fid, "general")

    cuerpo = (_encabezado(user_data) + _resumen_alertas(alertas(user_data))
              + "".join(_seccion_tanque(t, user_data, cids) for t in ts)
              + _grilla_generales(generales, cids)
              + f'<tr><td style="padding:16px 24px;font-size:11px;color:{GRIS};background:{GRIS_CLARO};">'
                f'Generado por Paulista Bot. Las fotos de reparaciones se revisan con IA; lo marcado como alerta '
                f'conviene verificarlo.</td></tr>')
    documento = (
        '<!DOCTYPE html><html lang="es"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1"></head>'
        f'<body style="margin:0;padding:0;background:{GRIS_CLARO};font-family:Arial,Helvetica,sans-serif;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:{GRIS_CLARO};">'
        '<tr><td align="center" style="padding:16px 8px;">'
        '<table role="presentation" width="680" cellpadding="0" cellspacing="0" '
        'style="width:680px;max-width:100%;background:#ffffff;border-radius:10px;overflow:hidden;">'
        f'{cuerpo}</table></td></tr></table></body></html>')
    return documento, imagenes
