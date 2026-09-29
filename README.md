# paulistabot

Bot de Telegram para los reportes de servicio (limpieza y reparación de tanques, presupuestos,
fumigaciones y avisos). Corre en Heroku (`worker: python main.py`).

**Antes de ejecutar o modificar algo, leer [`CLAUDE.md`](CLAUDE.md)**: todo se corre con
`bash scripts/correr.sh`, que primero pasa el chequeo de seguridad.

```bash
bash scripts/correr.sh --instalar   # crea .venv (Python 3.11) e instala dependencias con hashes
bash scripts/correr.sh --tests      # corre los tests (sin red ni credenciales reales)
bash scripts/correr.sh              # corre el bot
```

## Fotos de reparaciones y destrabe

En Limpieza y Presupuestos, cuando el operario escribe las reparaciones de un tanque (manual o por
nota de voz), el bot le pide las fotos de esas reparaciones. Puede mandar varias y termina con
"Listo". Si responde "no", "ninguna", etc., no se piden fotos.

Si escribe "Listo" o "no tengo" sin haber mandado ninguna foto, el paso queda trabado hasta que:

- mande una foto, o
- ingrese el código diario de administrador (el que genera `scripts/generate_daily_code.py`).

El destrabe con código queda registrado (tanque, motivo, fecha y hora de Argentina) y aparece en el
resumen final y en el mail. Después de `DESTRABE_MAX_INTENTOS` códigos incorrectos se bloquea por
`DESTRABE_MINUTOS_BLOQUEO` minutos.

Las fotos generales del final (orden de trabajo, ficha y tanques) no cambiaron.

## Variables de entorno

Ver [`.env.example`](.env.example). Ningún secreto va al repo.

| Variable | Obligatoria | Uso |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | sí | token del bot |
| `EMAIL_ADDRESS`, `EMAIL_PASSWORD` | sí | cuenta de Gmail que envía los reportes |
| `CC_EMAIL` | no | copia de los reportes |
| `OPENAI_API_KEY` | sí | transcripción y extracción de la nota de voz |
| `ADMIN_DAILY_CODE` | la escribe el scheduler | código diario del encargado |
| `HEROKU_API_KEY` | para el scheduler | `scripts/generate_daily_code.py` |
| `DESTRABE_MAX_INTENTOS` | no (5) | códigos incorrectos antes de bloquear el destrabe |
| `DESTRABE_MINUTOS_BLOQUEO` | no (15) | minutos de bloqueo |
| `GOOGLE_OAUTH_CLIENT_JSON`, `GMAIL_TOKEN_JSON`, `GOOGLE_SERVICE_ACCOUNT_JSON` | herramientas | `extract_reports.py`, `gmail_quickstart.py` |
