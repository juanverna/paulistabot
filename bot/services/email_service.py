import logging
import re
import smtplib
import imghdr
from io import BytesIO
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.image import MIMEImage
from email.header import Header

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
            # Un bloque por tanque, con su nombre: "Reparaciones Reserva 2 (fondo): TREA LI COMP".
            # extract_reports.py toma "Reparaciones <tanque>" y busca "Medida <tanque>".
            from bot.services import tanques_reporte as tq
            if user_data.get("cuerpos", 1) > 1:
                ordered_fields.append(("cuerpos", "Cuerpos del edificio"))
            tanques = tq.lista(user_data)
            if tanques:
                user_data = dict(user_data, _tanques=", ".join(tq.nombre(user_data, t["id"]) for t in tanques),
                                 **{f"_cubas_{t['id']}": t["cubas"] for t in tanques if t.get("cubas")})
                ordered_fields.append(("_tanques", "Tanques"))
            for t in tanques:
                nombre = tq.nombre(user_data, t["id"])
                ordered_fields.append((f"_cubas_{t['id']}", f"Cubas {nombre}"))
                ordered_fields += [(tq.clave(campo, t["id"]), f"{etiqueta} {nombre}")
                                   for campo, etiqueta in tq.CAMPOS.items()]

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
    from bot.services.tanques_reporte import nombre
    return nombre(user_data, sufijo)


def _photo_attachments(user_data: dict) -> list:
    """(file_id, nombre base) de cada foto: primero las de reparaciones por tanque, después las generales."""
    items = []
    for sufijo, fotos in user_data.get("fotos_reparaciones", {}).items():
        # "Reserva 2 (fondo)" -> "reserva_2_fondo" (sin espacios ni paréntesis en el nombre del archivo)
        tanque = "_".join(re.findall(r"[a-z0-9]+", _tank_name(user_data, sufijo).lower())) or sufijo
        numero = {}
        for f in fotos:
            grupo = (f.get("grupo") or "foto") if isinstance(f, dict) else "foto"
            numero[grupo] = numero.get(grupo, 0) + 1
            items.append((_file_id(f), f"reparaciones_{tanque}_{grupo}_{numero[grupo]}"))
    items += [(fid, f"foto_{i + 1}") for i, fid in enumerate(user_data.get("photos", []))]
    return items


def armar_mensaje(user_data: dict, descargar) -> MIMEMultipart:
    """
    Arma el mail. descargar(file_id) → bytes de la foto.

    Limpieza y Presupuestos: informe HTML con las fotos embebidas. Estructura
    multipart/alternative [text/plain, multipart/related [text/html, fotos]]: el texto plano
    queda en el primer nivel, que es donde lo busca extract_reports.py para cotizar.
    Fumigaciones y Avisos: texto plano con las fotos adjuntas, como siempre.
    """
    from bot.services.informe_html import armar_informe, SERVICIOS_CON_INFORME
    service = user_data.get("service", "")
    direccion = user_data.get("address") or user_data.get("direccion_qr")
    # extract_reports.py busca subject:"Reporte de Servicio:": ese comienzo no se cambia
    subject = f"Reporte de Servicio: {service}" + (f" · {direccion}" if direccion else "")
    body    = _build_body(user_data)

    msg = None
    if service in SERVICIOS_CON_INFORME:
        try:
            msg = _mensaje_html(user_data, body, descargar, armar_informe)
        except Exception as e:
            # Nunca se pierde un reporte por el HTML: sale con el formato de siempre
            logger.exception("No se pudo armar el informe HTML (%s): va en texto plano", e)
    if msg is None:
        msg = MIMEMultipart()
        msg.attach(MIMEText(body, "plain", "utf-8"))
        for file_id, name in _photo_attachments(user_data):
            try:
                data    = descargar(file_id)
                subtype = imghdr.what(None, h=data) or "jpeg"
                image   = MIMEImage(data, _subtype=subtype)
                image.add_header("Content-Disposition", "attachment",
                                 filename=f"{name}.{subtype}")
                msg.attach(image)
            except Exception as e:
                logger.error("Error adjuntando foto %s: %s", name, e)

    msg["From"]    = EMAIL_ADDRESS
    msg["To"]      = EMAIL_ADDRESS
    msg["Subject"] = Header(subject, "utf-8")
    if CC_EMAIL:
        msg["Cc"] = CC_EMAIL
    return msg


def _mensaje_html(user_data, body, descargar, armar_informe) -> MIMEMultipart:
    html_doc, imagenes = armar_informe(user_data, descargar)
    msg = MIMEMultipart("alternative")
    msg.attach(MIMEText(body, "plain", "utf-8"))
    related = MIMEMultipart("related")
    related.attach(MIMEText(html_doc, "html", "utf-8"))
    for cid, jpeg, nombre in imagenes:
        image = MIMEImage(jpeg, _subtype="jpeg")
        image.add_header("Content-ID", f"<{cid}>")
        # "attachment": Gmail la muestra en el diseño (por el Content-ID) y además en la lista de
        # adjuntos, desde donde se abre grande
        image.add_header("Content-Disposition", "attachment", filename=nombre)
        related.attach(image)
    msg.attach(related)
    return msg


def _descargar_de_telegram(context: CallbackContext):
    def descargar(file_id: str) -> bytes:
        bio = BytesIO()
        context.bot.get_file(file_id).download(out=bio)
        return bio.getvalue()
    return descargar


def send_email(user_data: dict, update: Update, context: CallbackContext) -> None:
    service = user_data.get("service", "")
    msg = armar_mensaje(user_data, _descargar_de_telegram(context))

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
