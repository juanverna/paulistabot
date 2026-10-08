(CODE, SERVICE, ORDER, ADDRESS, START_TIME, END_TIME, FUMIGATION, FUM_OBS,
 FUM_PHOTOS, CONTACT, TANK_TYPE, MEASURE, TAPAS_INSPECCION, TAPAS_ACCESO, SEALING, REPAIR,
 SUGGESTIONS, PHOTOS, AVISOS_CODE, AVISOS_ADDRESS, AVISOS_PHOTOS, SCAN_QR, FINAL_SUMMARY,
 REPAIR_PHOTOS, CONTACT_PHONE, CUERPOS, TANK_CUERPO, OTRO_TANQUE, TANK_CUBAS) = range(29)

# Pasos de cada tanque (se repiten por cada tanque; el tanque es user_data["tanque_actual"]).
# Estado → campo del tanque (ver bot/services/tanques_reporte.py).
CAMPO_DEL_PASO = {
    MEASURE:          "measure",
    TAPAS_INSPECCION: "tapas_inspeccion",
    TAPAS_ACCESO:     "tapas_acceso",
    SEALING:          "sealing",
    REPAIR:           "repairs",
    SUGGESTIONS:      "suggestions",
}

# Mapeo estado → clave en user_data (para limpiar al hacer "atrás"). Los pasos de cada tanque
# usan CAMPO_DEL_PASO con el tanque actual.
STATE_KEYS = {
    CODE:                  "code",
    ORDER:                 "order",
    ADDRESS:               "address",
    START_TIME:            "start_time",
    END_TIME:              "end_time",
    FUMIGATION:            "fumigated_units",
    FUM_OBS:               "fum_obs",
    CONTACT:               "contact_nombre",
    CONTACT_PHONE:         "contact_telefono",
    AVISOS_ADDRESS:        "avisos_address",
    CUERPOS:               "cuerpos",
    SCAN_QR:               None,
    FINAL_SUMMARY:         None,
    REPAIR_PHOTOS:         None,
    TANK_CUERPO:           None,
    OTRO_TANQUE:           None,
    TANK_CUBAS:            None,
}
