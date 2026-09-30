from telegram.ext import (ConversationHandler, MessageHandler, CallbackQueryHandler, Filters)

from bot.states import *
from bot.handlers.common    import start_conversation, back_handler
from bot.handlers.shared    import (get_code, service_selection, get_order, get_address,
                                     get_start_time, get_end_time, get_contact,
                                     handle_hora_boton, handle_atras_boton)
from bot.handlers.fumigacion import fumigation_data, get_fum_obs, handle_fum_photos
from bot.handlers.tanques   import (handle_tank_type,
                                     get_measure_main, get_tapas_inspeccion_main,
                                     get_tapas_acceso_main, get_sealing_main,
                                     get_repair_main, get_suggestions_main,
                                     handle_ask_second,
                                     get_measure_alt1, get_tapas_inspeccion_alt1,
                                     get_tapas_acceso_alt1, get_sealing_alt1,
                                     get_repair_alt1, get_suggestions_alt1,
                                     handle_ask_third,
                                     get_measure_alt2, get_tapas_inspeccion_alt2,
                                     get_tapas_acceso_alt2, get_sealing_alt2,
                                     get_repair_alt2, get_suggestions_alt2,
                                     handle_tank_photos)
from bot.handlers.avisos        import get_avisos_address, handle_avisos_photos
from bot.handlers.fotos_reparaciones import (handle_repair_photos, handle_repair_photo_button,
                                             handle_boton_vencido)
from bot.handlers.voice_handler import (handle_voice_message, handle_reprompt_response,
                                         handle_alt_reprompt_response, handle_admin_code_response)
from bot.handlers.final_summary import (show_final_summary, handle_final_summary_callback,
                                         handle_final_edit_response)
from bot.services.qr_service    import scan_qr

BACK = MessageHandler(Filters.regex("(?i)^atr[aá]s$"), back_handler)
TEXT = Filters.text & ~Filters.command
VOICE = Filters.voice | Filters.audio


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
                # sin "rf:" ni "hora:": botones de pasos anteriores no son una elección de tanque
                CallbackQueryHandler(handle_tank_type, pattern="^(?!rf:|hora:)"),
                MessageHandler(VOICE, handle_voice_message),
                MessageHandler(TEXT,  handle_reprompt_response),
                BACK,
            ],

            MEASURE_MAIN:          [MessageHandler(TEXT, get_measure_main)],
            TAPAS_INSPECCION_MAIN: [MessageHandler(TEXT, get_tapas_inspeccion_main)],
            TAPAS_ACCESO_MAIN:     [MessageHandler(TEXT, get_tapas_acceso_main)],
            SEALING_MAIN:          [MessageHandler(TEXT, get_sealing_main)],
            REPAIR_MAIN:           [MessageHandler(TEXT, get_repair_main)],
            SUGGESTIONS_MAIN:      [MessageHandler(TEXT, get_suggestions_main)],

            ASK_SECOND: [CallbackQueryHandler(handle_ask_second, pattern="^(si|no|back)$"), BACK],

            MEASURE_ALT1:          [MessageHandler(TEXT, get_measure_alt1)],
            TAPAS_INSPECCION_ALT1: [MessageHandler(TEXT, get_tapas_inspeccion_alt1)],
            TAPAS_ACCESO_ALT1:     [MessageHandler(TEXT, get_tapas_acceso_alt1)],
            SEALING_ALT1:          [MessageHandler(TEXT, get_sealing_alt1)],
            REPAIR_ALT1:           [MessageHandler(TEXT, get_repair_alt1)],
            SUGGESTIONS_ALT1:      [MessageHandler(TEXT, get_suggestions_alt1)],

            ASK_THIRD: [CallbackQueryHandler(handle_ask_third, pattern="^(si|no|back)$"), BACK],

            MEASURE_ALT2:          [MessageHandler(TEXT, get_measure_alt2)],
            TAPAS_INSPECCION_ALT2: [MessageHandler(TEXT, get_tapas_inspeccion_alt2)],
            TAPAS_ACCESO_ALT2:     [MessageHandler(TEXT, get_tapas_acceso_alt2)],
            SEALING_ALT2:          [MessageHandler(TEXT, get_sealing_alt2)],
            REPAIR_ALT2:           [MessageHandler(TEXT, get_repair_alt2)],
            SUGGESTIONS_ALT2:      [MessageHandler(TEXT, get_suggestions_alt2)],

            # Fotos de las reparaciones de cada tanque ("atrás" lo maneja el handler)
            REPAIR_PHOTOS: [
                CallbackQueryHandler(handle_repair_photo_button, pattern="^rf:"),
                MessageHandler(Filters.photo,    handle_repair_photos),
                MessageHandler(Filters.document, handle_repair_photos),
                MessageHandler(TEXT,             handle_repair_photos),
            ],

            CONTACT: [BACK, MessageHandler(TEXT, get_contact)],

            PHOTOS: [
                BACK,
                MessageHandler(Filters.photo,    handle_tank_photos),  # rechazadas con aviso
                MessageHandler(Filters.document, handle_tank_photos),  # aceptadas
                MessageHandler(TEXT,             handle_tank_photos),
            ],

            AVISOS_ADDRESS: [BACK, MessageHandler(TEXT, get_avisos_address)],

            SCAN_QR: [MessageHandler(Filters.photo & ~Filters.command, scan_qr)],

            FINAL_SUMMARY: [
                CallbackQueryHandler(handle_final_summary_callback,
                    pattern="^(final_send|final_edit)$"),
                MessageHandler(VOICE, handle_final_edit_response),
                MessageHandler(TEXT,  handle_final_edit_response),
            ],
        },
        # Botón de una foto o de la hora tocado cuando ese paso ya terminó
        fallbacks=[CallbackQueryHandler(handle_boton_vencido, pattern="^(rf|hora):")],
    )
