import logging
import smtplib
import imghdr
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage

from bot.config import EMAIL_ADDRESS, EMAIL_PASSWORD, CC_EMAIL
from bot.utils.helpers import apply_bold_keywords
from telegram import Update
from telegram.ext import CallbackContext
from telegram import ParseMode

logger = logging.getLogger(__name__)


def _build_body(user_data: dict) -> str:
    service = user_data.get("service", "")
    lines = []

    # Campos del QR (Fumigaciones)
    for key, label in [
        ("numero_evento",  "Número de evento"),
        ("direccion_qr",   "Dirección"),
        ("codigo_interno", "Código interno"),
        ("tipo_evento_qr", "Tipo de evento"),
    ]:
        if key in user_data:
            lines.append(f"{label}: {user_data[key]}")

    if "code" in user_data:
        lines.append(f"Código: {user_data['code']}")

    if service == "Avisos":
        for key, label in [
            ("avisos_address", "Dirección/es"),
            ("start_time",     "Hora de inicio"),
            ("end_time",       "Hora de finalización"),
            ("contact",        "Contacto"),
        ]:
            if key in user_data:
                lines.append(f"{label}: {user_data[key]}")
    else:
        ordered_fields = []
        if service in ("Fumigaciones", "Limpieza y Reparacion de Tanques"):
            ordered_fields.append(("order", "Número de Orden"))

        ordered_fields += [
            ("address",   "Dirección"),
            ("start_time", "Hora de inicio"),
            ("end_time",   "Hora de finalización"),
            ("service",    "Servicio seleccionado"),
        ]

        if service in ("Limpieza y Reparacion de Tanques", "Presupuestos"):
            selected = user_data.get("selected_category", "")
            alt1     = user_data.get("alternative_1", "")
            alt2     = user_data.get("alternative_2", "")
            ordered_fields += [
                ("selected_category",    "Tipo de tanque"),
                ("measure_main",         "Medida principal"),
                ("tapas_inspeccion_main","Tapas inspección"),
                ("tapas_acceso_main",    "Tapas acceso"),
                ("sealing_main",         f"Sellado {selected}"),
                ("repairs",              f"Reparaciones {selected}"),
                ("suggestions",          f"Sugerencias {selected}"),
                ("measure_alt1",         f"Medida {alt1}"),
                ("tapas_inspeccion_alt1",f"Tapas inspección {alt1}"),
                ("tapas_acceso_alt1",    f"Tapas acceso {alt1}"),
                ("sealing_alt1",         f"Sellado {alt1}"),
                ("repair_alt1",          f"Reparaciones {alt1}"),
                ("suggestions_alt1",     f"Sugerencias {alt1}"),
                ("measure_alt2",         f"Medida {alt2}"),
                ("tapas_inspeccion_alt2",f"Tapas inspección {alt2}"),
                ("tapas_acceso_alt2",    f"Tapas acceso {alt2}"),
                ("sealing_alt2",         f"Sellado {alt2}"),
                ("repair_alt2",          f"Reparaciones {alt2}"),
                ("suggestions_alt2",     f"Sugerencias {alt2}"),
            ]

        if service == "Fumigaciones":
            ordered_fields += [
                ("fumigated_units", "Unidades con insectos"),
                ("fum_obs",         "Observaciones"),
            ]

        ordered_fields.append(("contact", "Contacto"))

        for key, label in ordered_fields:
            if key in user_data:
                lines.append(f"{label}: {user_data[key]}")

    return "Detalles del reporte:\n" + "\n".join(lines)


def send_email(user_data: dict, update: Update, context: CallbackContext) -> None:
    service = user_data.get("service", "")
    subject = f"Reporte de Servicio: {service}"
    body    = _build_body(user_data)

    msg           = MIMEMultipart()
    msg["From"]   = EMAIL_ADDRESS
    msg["To"]     = EMAIL_ADDRESS
    msg["Subject"] = subject
    if CC_EMAIL:
        msg["Cc"] = CC_EMAIL
    msg.attach(MIMEText(body, "plain"))

    # Adjuntar fotos
    for idx, file_id in enumerate(user_data.get("photos", [])):
        try:
            bio = BytesIO()
            context.bot.get_file(file_id).download(out=bio)
            bio.seek(0)
            data    = bio.read()
            subtype = imghdr.what(None, h=data) or "jpeg"
            image   = MIMEImage(data, _subtype=subtype)
            image.add_header("Content-Disposition", "attachment",
                             filename=f"foto_{idx + 1}.{subtype}")
            msg.attach(image)
        except Exception as e:
            logger.error("Error adjuntando foto %d: %s", idx + 1, e)

    recipients = [EMAIL_ADDRESS] + ([CC_EMAIL] if CC_EMAIL else [])

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.sendmail(EMAIL_ADDRESS, recipients, msg.as_string())
        server.quit()
        logger.info("Email enviado OK (service=%s)", service)
        reply = "✅ Reporte enviado correctamente."
    except Exception as e:
        logger.error("Error enviando email: %s", e)
        reply = "❌ Error al enviar el reporte. Contactá al administrador."

    if update.message:
        update.message.reply_text(apply_bold_keywords(reply), parse_mode=ParseMode.HTML)
    else:
        context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=apply_bold_keywords(reply),
            parse_mode=ParseMode.HTML,
        )
