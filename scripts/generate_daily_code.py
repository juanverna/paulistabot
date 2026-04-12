"""
generate_daily_code.py
----------------------
Script que corre todos los días a las 7 AM via Heroku Scheduler.

Genera un código de 4 dígitos aleatorio, lo actualiza en Heroku
como Config Var y te lo envía por mail.

Configurar en Heroku Scheduler con:
    python scripts/generate_daily_code.py
"""

import os
import random
import smtplib
import requests
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import date

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
HEROKU_API_KEY = os.getenv("HEROKU_API_KEY")
HEROKU_APP_NAME = os.getenv("HEROKU_APP_NAME", "paulistabot")


def generate_code() -> str:
    """Genera un código de 4 dígitos aleatorio."""
    return str(random.randint(1000, 9999))


def update_heroku_config(code: str) -> bool:
    """Actualiza el Config Var ADMIN_DAILY_CODE en Heroku."""
    if not HEROKU_API_KEY:
        logger.error("HEROKU_API_KEY no configurada.")
        return False
    try:
        response = requests.patch(
            f"https://api.heroku.com/apps/{HEROKU_APP_NAME}/config-vars",
            headers={
                "Accept": "application/vnd.heroku+json; version=3",
                "Authorization": f"Bearer {HEROKU_API_KEY}",
                "Content-Type": "application/json",
            },
            json={"ADMIN_DAILY_CODE": code},
            timeout=10,
        )
        if response.status_code == 200:
            logger.info("Config Var actualizado: ADMIN_DAILY_CODE=%s", code)
            return True
        else:
            logger.error("Error actualizando Config Var: %s %s", response.status_code, response.text)
            return False
    except Exception as e:
        logger.error("Error conectando a Heroku API: %s", e)
        return False


def send_code_email(code: str) -> bool:
    """Envía el código del día por mail."""
    if not EMAIL_ADDRESS or not EMAIL_PASSWORD:
        logger.error("EMAIL_ADDRESS o EMAIL_PASSWORD no configurados.")
        return False
    try:
        today = date.today().strftime("%d/%m/%Y")
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = EMAIL_ADDRESS
        msg["Subject"] = f"Código de administrador del día - {today}"
        body = (
            f"Código de administrador para el día {today}:\n\n"
            f"    🔑 {code}\n\n"
            f"Este código vence hoy a las 23:59 y se renueva mañana a las 7:00 AM.\n"
            f"Usalo solo si un operario necesita omitir una validación por una anomalía."
        )
        msg.attach(MIMEText(body, "plain"))
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, EMAIL_ADDRESS, msg.as_string())
        server.quit()
        logger.info("Mail con código enviado OK.")
        return True
    except Exception as e:
        logger.error("Error enviando mail: %s", e)
        return False


if __name__ == "__main__":
    code = generate_code()
    logger.info("Código del día generado: %s", code)

    heroku_ok = update_heroku_config(code)
    mail_ok   = send_code_email(code)

    if heroku_ok and mail_ok:
        logger.info("✅ Todo OK. Código activo: %s", code)
    else:
        logger.error("❌ Hubo errores. Revisá los logs.")
