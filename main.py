import logging
from telegram.ext import Updater
from bot.config import TELEGRAM_BOT_TOKEN
from bot.conversation import build_conversation_handler

logging.basicConfig(
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)


def main():
    logger.info("Iniciando bot...")
    updater = Updater(TELEGRAM_BOT_TOKEN, use_context=True)
    updater.dispatcher.add_handler(build_conversation_handler())
    updater.start_polling()
    logger.info("Bot en línea. Esperando mensajes.")
    updater.idle()


if __name__ == "__main__":
    main()
