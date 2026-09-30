"""
dataset_fotos.py
----------------
Guarda en una hoja de Google Sheets una fila por cada foto de reparación, para medir y
mejorar la IA más adelante (ver README, "Datos para entrenar").

Lo más valioso es la columna grupo_final cuando corregida_por_operario = sí: es lo que la
foto muestra según el operario, contra lo que dijo la IA (grupo_ia). Las fotos no se suben
a ningún lado: se guarda el file_id de Telegram, con el que el bot puede volver a bajarlas.
No se guardan dirección ni contacto; solo el número de orden, para ubicar el servicio.

Se activa con DATASET_SHEET_ID y GOOGLE_SERVICE_ACCOUNT_JSON (la hoja tiene que estar
compartida como Editor con el mail de la cuenta de servicio). Si falta algo o falla, no
pasa nada: el reporte se envía igual.
"""

import os
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

HOJA = os.getenv("DATASET_SHEET_NAME", "Fotos")
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

COLUMNAS = [
    "fecha", "orden", "codigo_operario", "servicio", "tanque", "reparaciones_texto",
    "items_declarados", "file_id", "estado", "descartada", "grupo_ia", "grupo_final",
    "corregida_por_operario", "elemento_detectado", "tipo_tapa_seguro", "estado_elemento",
    "calidad_foto", "respalda_la_reparacion", "requiere_revoque", "danos_visibles",
    "comentario_ia", "modelo",
]

_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="dataset")
_lock = threading.Lock()
_encabezado_ok = False


def configurado() -> bool:
    return bool(os.getenv("DATASET_SHEET_ID") and os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))


def _si_no(valor) -> str:
    if valor is None:
        return ""
    return "sí" if valor else "no"


def filas(user_data: dict) -> list:
    """Una fila (lista de COLUMNAS) por cada foto de reparación, incluidas las descartadas."""
    from bot.services import vision_service
    from bot.services.destrabe import HORA_ARGENTINA
    from bot.handlers.fotos_reparaciones import TANQUES
    from datetime import datetime

    fecha = datetime.now(HORA_ARGENTINA).strftime("%Y-%m-%d %H:%M")
    orden = user_data.get("order") or user_data.get("numero_evento", "")
    items_por_tanque = user_data.get("items_reparacion", {})

    fotos = [(sufijo, f, False) for sufijo, lista in user_data.get("fotos_reparaciones", {}).items()
             for f in lista if isinstance(f, dict)]
    fotos += [(f.get("sufijo"), f, True) for f in user_data.get("fotos_descartadas", [])]

    resultado = []
    for sufijo, foto, descartada in fotos:
        if sufijo not in TANQUES:
            continue
        clave_rep, clave_tanque = TANQUES[sufijo]
        items = items_por_tanque.get(sufijo, {}).get("items", {})
        declarados = "; ".join(
            f"{g} x{i['cantidad']}" + (f" [{', '.join(i['codigos'])}]" if i.get("codigos") else "")
            for g, i in items.items())
        a = foto.get("analisis") or {}
        resultado.append([
            fecha, orden, user_data.get("code", ""), user_data.get("service", ""),
            user_data.get(clave_tanque, ""), user_data.get(clave_rep, ""), declarados,
            foto.get("file_id", ""), foto.get("estado", ""), _si_no(descartada),
            foto.get("grupo_ia") or "", "" if descartada else (foto.get("grupo") or ""),
            _si_no(foto.get("corregida", False)), a.get("elemento_detectado", ""),
            _si_no(a.get("tipo_tapa_seguro")), a.get("estado", ""), a.get("calidad_foto", ""),
            _si_no(a.get("respalda_la_reparacion")), _si_no(a.get("requiere_revoque")),
            "; ".join(a.get("danos_visibles", [])), a.get("comentario", ""),
            vision_service.VISION_MODEL if a else "",
        ])
    return resultado


def _sesion():
    from google.oauth2 import service_account
    from google.auth.transport.requests import AuthorizedSession
    info = json.loads(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"))
    credenciales = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
    return AuthorizedSession(credenciales)


def _agregar(filas_nuevas: list) -> None:
    global _encabezado_ok
    base = f"https://sheets.googleapis.com/v4/spreadsheets/{os.getenv('DATASET_SHEET_ID')}/values"
    try:
        sesion = _sesion()
        with _lock:
            if not _encabezado_ok:
                r = sesion.get(f"{base}/{HOJA}!A1:A1", timeout=15)
                r.raise_for_status()
                if not r.json().get("values"):
                    filas_nuevas = [COLUMNAS] + filas_nuevas
                _encabezado_ok = True
        r = sesion.post(f"{base}/{HOJA}!A1:append",
                        params={"valueInputOption": "RAW", "insertDataOption": "INSERT_ROWS"},
                        json={"values": filas_nuevas}, timeout=15)
        r.raise_for_status()
        logger.info("Dataset: %d fila(s) agregadas", len(filas_nuevas))
    except Exception as e:
        logger.error("Dataset: no se pudieron guardar las filas (%s: %s)", type(e).__name__, e)


def registrar(user_data: dict) -> None:
    """Guarda las fotos del reporte en la hoja, en segundo plano. No hace nada si no está configurado."""
    if not configurado():
        return
    try:
        nuevas = filas(user_data)
    except Exception as e:
        logger.error("Dataset: no se pudieron armar las filas: %s", e)
        return
    if nuevas:
        _executor.submit(_agregar, nuevas)
