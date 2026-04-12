"""
articles_service.py
-------------------
Carga el CSV de artículos al arrancar el bot y provee
una función para buscar el código más cercano a lo que
dijo el operario.
"""

import csv
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

# Ruta al CSV en el repositorio
CSV_PATH = Path(__file__).parent.parent.parent / "Articulos Python - Hoja 1.csv"

# Diccionario global: {codigo: descripcion}
ARTICLES: dict[str, str] = {}


def load_articles() -> None:
    """Carga el CSV de artículos en memoria. Llamar al arrancar el bot."""
    global ARTICLES
    try:
        with open(CSV_PATH, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                codigo = row.get("Codigo", "").strip()
                descripcion = row.get("Descripcion Asociada", "").strip()
                if codigo and descripcion:
                    ARTICLES[codigo] = descripcion
        logger.info("Artículos cargados: %d entradas", len(ARTICLES))
    except Exception as e:
        logger.error("Error cargando artículos: %s", e)


def get_articles_context() -> str:
    """
    Devuelve el contenido del CSV como texto para incluir en el prompt de GPT.
    Formato: CODIGO: Descripción asociada
    """
    if not ARTICLES:
        load_articles()
    lines = [f"{code}: {desc}" for code, desc in ARTICLES.items()]
    return "\n".join(lines)
