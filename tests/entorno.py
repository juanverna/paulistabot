"""Variables de entorno falsas para importar el bot en los tests (sin red ni credenciales reales)."""

import os
from unittest.mock import MagicMock

VARIABLES_FALSAS = {
    "TELEGRAM_BOT_TOKEN": "123:test",
    "EMAIL_ADDRESS":      "test@example.com",
    "EMAIL_PASSWORD":     "test",
    "OPENAI_API_KEY":     "sk-test",
}


def preparar() -> None:
    """Llamar al principio de cada test, antes de importar cualquier módulo de bot/."""
    for clave, valor in VARIABLES_FALSAS.items():
        os.environ.setdefault(clave, valor)


def contexto(user_data: dict = None) -> MagicMock:
    ctx = MagicMock()
    ctx.user_data = {} if user_data is None else user_data
    return ctx


def update_texto(texto: str) -> MagicMock:
    upd = MagicMock()
    upd.effective_chat.id = 1
    upd.message.text = texto
    upd.message.photo = []
    upd.message.document = None
    upd.message.media_group_id = None
    return upd


def update_foto(file_id: str, album: str = None) -> MagicMock:
    upd = update_texto(None)
    foto = MagicMock()
    foto.file_id = file_id
    upd.message.photo = [foto]
    upd.message.media_group_id = album
    return upd


def update_documento(file_id: str, mime_type: str) -> MagicMock:
    upd = update_texto(None)
    upd.message.document = MagicMock(file_id=file_id, mime_type=mime_type)
    return upd


def mensajes_enviados(ctx: MagicMock, upd: MagicMock) -> str:
    """Todo lo que el bot le mandó al operario (send_message y reply_text), en un solo texto."""
    textos = [c.kwargs.get("text", "") for c in ctx.bot.send_message.call_args_list]
    textos += [c.args[0] if c.args else c.kwargs.get("text", "")
               for c in upd.message.reply_text.call_args_list]
    return "\n".join(textos)
