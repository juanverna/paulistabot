from telegram.ext import (ConversationHandler, MessageHandler, CallbackQueryHandler, Filters)

from bot.states import *
from bot.handlers.common    import start_conversation, back_handler, atras_boton
from bot.handlers.shared    import (get_code, service_selection, get_order, get_address,
                                     get_start_time, get_end_time,
                                     handle_hora_boton, handle_atras_boton)
from bot.handlers.fumigacion import fumigation_data, get_fum_obs, handle_fum_photos
from bot.handlers.tanques   import (handle_tank_type,
                                     get_suggestions_main,
                                     handle_ask_second,
                                     get_suggestions_alt1,
                                     handle_ask_third,
                                     get_suggestions_alt2,
                                     handle_tank_photos)
from bot.handlers import campos_tanque as ct
from bot.handlers.avisos        import get_avisos_address, handle_avisos_photos
from bot.handlers.fotos_reparaciones import (handle_repair_photos, handle_repair_photo_button,
                                             handle_repair_photos_atras, handle_boton_vencido)
from bot.handlers.final_summary import handle_final_summary_callback, handle_final_text
from bot.services.qr_service    import scan_qr

BACK = MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler)
TEXT = Filters.text & ~Filters.command


def _pasos_tanque(sufijo: str) -> dict:
    """Medida (validada), tapas y sellado (texto) y reparaciones (menú) de un tanque. Ver campos_tanque.py."""
    p = ct.PASOS[sufijo]
    return {
        p["medida"][0]:  [CallbackQueryHandler(ct.boton_material(sufijo), pattern="^md:"),
                          MessageHandler(TEXT, ct.recibir_medida(sufijo))],
        p["insp"][0]:    [MessageHandler(TEXT, ct.recibir_texto(sufijo, "insp"))],
        p["acceso"][0]:  [MessageHandler(TEXT, ct.recibir_texto(sufijo, "acceso"))],
        p["sellado"][0]: [MessageHandler(TEXT, ct.recibir_texto(sufijo, "sellado"))],
        p["reparaciones"][0]: [CallbackQueryHandler(ct.boton_reparaciones(sufijo), pattern="^(rp:|back$)"),
                               MessageHandler(TEXT, ct.texto_reparaciones(sufijo))],
    }


def build_conversation_handler() -> ConversationHandler:
    return ConversationHandler(
        entry_points=[MessageHandler(Filters.regex("(?i)^hola$"), start_conversation)],
        states={
            CODE: [MessageHandler(TEXT, get_code)],

            SERVICE: [
                CallbackQueryHandler(service_selection,
                    pattern="^(Fumigaciones|Limpieza y Reparacion de Tanques|Presupuestos|Avisos|back)$"),
                BACK,
            ],

            ORDER:      [BACK, MessageHandler(TEXT, get_order)],
            ADDRESS:    [BACK, MessageHandler(TEXT, get_address)],
            # Hora con botones (24 hs) o escrita
            START_TIME: [BACK, CallbackQueryHandler(handle_hora_boton, pattern="^hora:"),
                         CallbackQueryHandler(handle_atras_boton, pattern="^back$"),
                         MessageHandler(TEXT, get_start_time)],
            END_TIME:   [BACK, CallbackQueryHandler(handle_hora_boton, pattern="^hora:"),
                         CallbackQueryHandler(handle_atras_boton, pattern="^back$"),
                         MessageHandler(TEXT, get_end_time)],

            FUMIGATION: [BACK, MessageHandler(TEXT, fumigation_data)],
            FUM_OBS:    [BACK, MessageHandler(TEXT, get_fum_obs)],

            TANK_TYPE: [
                # Botones de pasos anteriores (fotos, hora, tapas...) no son una elección de tanque
                CallbackQueryHandler(handle_tank_type, pattern="^(?!(rf|hora|tp|se|md|ct|rp|ed):)"),
                BACK,
            ],

            **_pasos_tanque("main"),
            SUGGESTIONS_MAIN:      [MessageHandler(TEXT, get_suggestions_main)],

            ASK_SECOND: [CallbackQueryHandler(handle_ask_second, pattern="^(si|no|back)$"), BACK],

            **_pasos_tanque("alt1"),
            SUGGESTIONS_ALT1:      [MessageHandler(TEXT, get_suggestions_alt1)],

            ASK_THIRD: [CallbackQueryHandler(handle_ask_third, pattern="^(si|no|back)$"), BACK],

            **_pasos_tanque("alt2"),
            SUGGESTIONS_ALT2:      [MessageHandler(TEXT, get_suggestions_alt2)],

            # Fotos de las reparaciones de cada tanque ("atrás" lo maneja el handler)
            REPAIR_PHOTOS: [
                CallbackQueryHandler(handle_repair_photo_button, pattern="^rf:"),
                CallbackQueryHandler(handle_repair_photos_atras, pattern="^back$"),
                MessageHandler(Filters.photo,    handle_repair_photos),
                MessageHandler(Filters.document, handle_repair_photos),
                MessageHandler(TEXT,             handle_repair_photos),
            ],

            # Contacto: nombre y después teléfono
            CONTACT:       [BACK, MessageHandler(TEXT, ct.recibir_nombre)],
            CONTACT_PHONE: [BACK, MessageHandler(TEXT, ct.recibir_telefono)],

            PHOTOS: [
                BACK,
                MessageHandler(Filters.photo,    handle_tank_photos),  # rechazadas con aviso
                MessageHandler(Filters.document, handle_tank_photos),  # aceptadas
                MessageHandler(TEXT,             handle_tank_photos),
            ],

            AVISOS_ADDRESS: [BACK, MessageHandler(TEXT, get_avisos_address)],

            SCAN_QR: [BACK, MessageHandler(Filters.photo & ~Filters.command, scan_qr)],

            FINAL_SUMMARY: [
                CallbackQueryHandler(handle_final_summary_callback, pattern="^(final_send|final_edit|ed:)"),
                MessageHandler(TEXT, handle_final_text),
            ],
        },
        # Botón de una foto, de la hora, de reparaciones, material o contacto tocado cuando ese
        # paso ya terminó ("tp" y "se": tapas y sellado con botones de una versión anterior)
        fallbacks=[CallbackQueryHandler(handle_boton_vencido, pattern="^(rf|hora|tp|se|md|ct|rp|ed):"),
                   # ATRAS de las preguntas cuyo paso no lo maneja él mismo (medida, tapas, contacto...)
                   CallbackQueryHandler(atras_boton, pattern="^back$")],
    )
