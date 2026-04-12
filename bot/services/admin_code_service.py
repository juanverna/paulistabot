"""
admin_code_service.py
---------------------
Genera y valida el código diario de administrador.

El código se guarda como variable de entorno ADMIN_DAILY_CODE en Heroku.
El script generate_daily_code.py lo actualiza todos los días a las 7 AM
via Heroku Scheduler.
"""

import os
import logging
from datetime import date

logger = logging.getLogger(__name__)


def get_current_code() -> str:
    """Obtiene el código diario actual desde la variable de entorno."""
    return os.getenv("ADMIN_DAILY_CODE", "")


def validate_code(user_input: str) -> bool:
    """
    Valida que el código ingresado por el operario coincida con el del día.
    Acepta el código con o sin espacios.
    """
    current = get_current_code().strip()
    user = user_input.strip().replace(" ", "")
    if not current:
        logger.warning("No hay ADMIN_DAILY_CODE configurado.")
        return False
    return user == current
