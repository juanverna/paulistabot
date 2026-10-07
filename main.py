import logging
from telegram.ext import Updater
from bot.config import TELEGRAM_BOT_TOKEN
from bot.conversation import build_conversation_handler

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def crear_updater(token: str) -> Updater:
    """Updater con el bot que deja el botón ATRAS solo en la última pregunta (bot/utils/bot_atras.py)."""
    from telegram.utils.request import Request
    from bot.utils.bot_atras import BotConAtrasUnico
    # con_pool_size: los 4 hilos del dispatcher + 4, lo que Updater arma cuando recibe el token
    request = Request(con_pool_size=8, read_timeout=60, connect_timeout=60)
    return Updater(bot=BotConAtrasUnico(token, request=request), use_context=True)


def main():
    logger.info("Iniciando bot...")
    from bot.services.articles_service import load_articles
    load_articles()
    updater = crear_updater(TELEGRAM_BOT_TOKEN)
    updater.dispatcher.add_handler(build_conversation_handler())
    updater.start_polling()
    logger.info("Bot en línea. Esperando mensajes.")
    updater.idle()


if __name__ == "__main__":
    main()
