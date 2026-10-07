"""
destrabe.py
-----------
Mecanismo de destrabe de los pasos de foto.

Cuando un paso de foto no se puede completar, queda trabado hasta que el operario
mande una foto válida o ingrese el código diario de administrador (el mismo que
genera scripts/generate_daily_code.py y valida admin_code_service.validate_code).
Cada destrabe con código queda registrado para las alertas del informe.
"""

import os
import re
import logging
from datetime import datetime, timedelta, timezone

from bot.services.admin_code_service import validate_code

logger = logging.getLogger(__name__)

# Motivos que se registran (aparecen en las alertas del informe)
MOTIVO_FOTO_FALTANTE = "foto faltante"
MOTIVO_CALIDAD_BAJA  = "foto de calidad baja"
MOTIVO_NO_RESPALDA   = "foto no respalda la reparación"
MOTIVO_CORRECCION    = "foto corregida por el operario"

# Argentina no tiene horario de verano: UTC-3 fijo (Heroku corre en UTC)
HORA_ARGENTINA = timezone(timedelta(hours=-3), "ART")

MAX_INTENTOS      = int(os.getenv("DESTRABE_MAX_INTENTOS", "5"))
MINUTOS_BLOQUEO   = int(os.getenv("DESTRABE_MINUTOS_BLOQUEO", "15"))

# Resultados de intentar_destrabe
OK         = "ok"
INCORRECTO = "incorrecto"
BLOQUEADO  = "bloqueado"


def mensaje_trabado(motivo_texto: str) -> str:
    """Mensaje que ve el operario cuando el paso queda trabado."""
    return (
        f"{motivo_texto}. Si tenés otra foto del mismo lugar en tu galería, mandala. "
        "Si no tenés, comunicate con el encargado para ver cómo seguimos."
    )


def parece_codigo(texto: str) -> bool:
    """True si el texto parece un código numérico (ej: '1234' o '12 34')."""
    return bool(re.fullmatch(r"\s*\d[\d ]*\d\s*", texto or ""))


def _ahora() -> datetime:
    return datetime.now(HORA_ARGENTINA)


def intentar_destrabe(user_data: dict, texto: str) -> str:
    """
    Valida el código de administrador con límite de intentos.
    Devuelve OK, INCORRECTO o BLOQUEADO.
    """
    estado = user_data.setdefault("destrabe_intentos", {"fallidos": 0, "bloqueado_hasta": None})
    bloqueado_hasta = estado.get("bloqueado_hasta")
    if bloqueado_hasta and _ahora() < bloqueado_hasta:
        return BLOQUEADO

    if validate_code(texto):
        estado.update({"fallidos": 0, "bloqueado_hasta": None})
        return OK

    estado["fallidos"] += 1
    logger.warning("Código de destrabe incorrecto (intento %d)", estado["fallidos"])
    if estado["fallidos"] >= MAX_INTENTOS:
        estado.update({"fallidos": 0,
                       "bloqueado_hasta": _ahora() + timedelta(minutes=MINUTOS_BLOQUEO)})
        return BLOQUEADO
    return INCORRECTO


def mensaje_bloqueado() -> str:
    return (f"⛔ Demasiados intentos. Esperá {MINUTOS_BLOQUEO} minutos "
            "y pedile el código de hoy al encargado.")


def registrar_destrabe(user_data: dict, tanque: str, item: str, motivo: str) -> dict:
    """Registra un ítem destrabado por el encargado (para las alertas del informe)."""
    ahora = _ahora()
    registro = {
        "tanque": tanque,
        "item":   item,
        "motivo": motivo,
        "fecha":  ahora.strftime("%d/%m/%Y"),
        "hora":   ahora.strftime("%H:%M"),
    }
    user_data.setdefault("destrabes", []).append(registro)
    logger.info("Destrabado por encargado: %s", registro)
    return registro
