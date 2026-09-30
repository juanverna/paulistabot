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

    if "modo_ingreso" in user_data:
        lines.append(f"Modo de ingreso: {user_data['modo_ingreso']}")

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

        # Ninguna de estas líneas puede empezar con "Reparaciones": extract_reports.py
        # toma esas claves como ítems a cotizar.
        for sufijo, fotos in user_data.get("fotos_reparaciones", {}).items():
            if fotos:
                lines.append(f"Fotos reparaciones {_tank_name(user_data, sufijo)}: {len(fotos)}"
                             f"{_detalle_revision(fotos)}")
        for sufijo, datos in user_data.get("items_reparacion", {}).items():
            if datos.get("estado"):
                lines.append(f"Ítems con foto {_tank_name(user_data, sufijo)}: {_detalle_items(datos['estado'])}")
        descartadas = {}
        for foto in user_data.get("fotos_descartadas", []):
            descartadas[foto["sufijo"]] = descartadas.get(foto["sufijo"], 0) + 1
        for sufijo, cantidad in descartadas.items():
            lines.append(f"Fotos descartadas por no coincidir {_tank_name(user_data, sufijo)}: {cantidad}")
        for d in user_data.get("destrabes", []):
            lines.append(f"Destrabado por encargado ({d['tanque']}, {d['item']}): "
                         f"{d['motivo']} - {d['fecha']} {d['hora']}")

    return "Detalles del reporte:\n" + "\n".join(lines)


ESTADOS_TEXTO = {"validada": "validadas por IA", "sin_validar": "sin validar",
                 "calidad": "de calidad baja", "no_respalda": "no muestran el daño"}


def _detalle_items(estados: dict) -> str:
    """"Tapa de acceso 2/2, Marco 0/1" (fotos de objetos distintos / requeridas por ítem)."""
    from bot.services.items_reparacion import ETIQUETAS
    partes = []
    for grupo, e in estados.items():
        nota = "" if e.get("verificado", True) else " sin verificar"
        partes.append(f"{ETIQUETAS.get(grupo, grupo)} {e['distintas']}/{e['requeridas']}{nota}")
    return ", ".join(partes)


def _file_id(foto) -> str:
    return foto["file_id"] if isinstance(foto, dict) else foto


def _detalle_revision(fotos: list) -> str:
    """ " (validadas por IA: 2, sin validar: 1)" según el estado de cada foto."""
    from bot.services.revision_fotos import resumen
    cuenta = resumen(fotos)
    partes = [f"{texto}: {cuenta[estado]}" for estado, texto in ESTADOS_TEXTO.items()
              if cuenta.get(estado)]
    corregidas = sum(1 for f in fotos if isinstance(f, dict) and f.get("corregida"))
    if corregidas:
        partes.append(f"corregidas por el operario: {corregidas}")
    return f" ({', '.join(partes)})" if partes else ""


def _tank_name(user_data: dict, sufijo: str) -> str:
    key = {"main": "selected_category", "alt1": "alternative_1", "alt2": "alternative_2"}[sufijo]
    return user_data.get(key, "").capitalize()


def _photo_attachments(user_data: dict) -> list:
    """(file_id, nombre base) de cada foto: primero las de reparaciones por tanque, después las generales."""
    items = []
    for sufijo, fotos in user_data.get("fotos_reparaciones", {}).items():
        tanque = _tank_name(user_data, sufijo).lower() or sufijo
        numero = {}
        for f in fotos:
            grupo = (f.get("grupo") or "foto") if isinstance(f, dict) else "foto"
            numero[grupo] = numero.get(grupo, 0) + 1
            items.append((_file_id(f), f"reparaciones_{tanque}_{grupo}_{numero[grupo]}"))
    items += [(fid, f"foto_{i + 1}") for i, fid in enumerate(user_data.get("photos", []))]
    return items


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
    for file_id, name in _photo_attachments(user_data):
        try:
            bio = BytesIO()
            context.bot.get_file(file_id).download(out=bio)
            bio.seek(0)
            data    = bio.read()
            subtype = imghdr.what(None, h=data) or "jpeg"
            image   = MIMEImage(data, _subtype=subtype)
            image.add_header("Content-Disposition", "attachment",
                             filename=f"{name}.{subtype}")
            msg.attach(image)
        except Exception as e:
            logger.error("Error adjuntando foto %s: %s", name, e)

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
