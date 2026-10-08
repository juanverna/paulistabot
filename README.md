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

En Limpieza y Presupuestos, después de la hora el bot pregunta cuántos cuerpos tiene el edificio
y el operario carga los tanques de a uno, todos los que haya (puede haber 2 reservas o 2 cisternas),
diciendo de qué cuerpo es cada uno (frente, fondo, izquierda o derecha) si hay más de uno. En el
mail cada tanque tiene sus líneas con su nombre: "Reparaciones Reserva 2 (fondo): ..."
(`bot/services/tanques_reporte.py`). El operario elige las reparaciones de cada tanque con un menú de
botones (catálogo en `bot/services/campos.py`; no se escriben) y el bot le pide las fotos de esas
reparaciones. Puede mandar varias y termina con "Listo". Con "Sin reparaciones" no se piden fotos.
Las reparaciones se guardan en código: tapas y marcos con el del CSV de artículos
(`TITCEA 30x30`, `TATCC octogonal con parantes 54x54`) y el revoque con la nomenclatura del dueño:
tanque + cuba (`TC`/`TR`/`TH` + `EA`/`C`), pared (`F`, `CF`, `LI`, `LD`, `P`) y `COMP` o `PARC` con la
medida en metros (`TCEA F COMP`, `TRC LI PARC 1.50x1.50`). La carga es solo manual (la nota de voz
se sacó el 2026-10-07). "Modificar algo", en el resumen
final, vuelve a hacer la pregunta del campo elegido con los mismos controles.

Si escribe "Listo" o "no tengo" sin haber mandado ninguna foto, el paso queda trabado hasta que:

- mande una foto, o
- ingrese el código diario de administrador (el que genera `scripts/generate_daily_code.py`).

El destrabe con código queda registrado (tanque, motivo, fecha y hora de Argentina) y aparece en el
resumen final y en el mail. Después de `DESTRABE_MAX_INTENTOS` códigos incorrectos se bloquea por
`DESTRABE_MINUTOS_BLOQUEO` minutos.

### Ítems de cada reparación

Del texto de reparaciones el bot saca los ítems que necesitan foto
(`bot/services/items_reparacion.py`), tanto por código del CSV de artículos como por texto:

| Escribe | Ítem |
|---|---|
| `TIT…`, "tapa de inspección", "tapa insp" | Tapa de inspección |
| `TAT…`, "tapa de acceso" | Tapa de acceso |
| `MAT…`, "marco" | Marco |
| `TMT…`, "tapa y marco" | Tapa y marco de acceso |
| "revoque", "revocar", "mampostería", "fisura" | Revoque |
| "flotante" (en cualquier tanque, sin código) | Flotante |
| "automático" (en cualquier tanque, sin código) | Automático |
| "tapa" sola | Tapa (cualquiera de las dos) |
| nada de lo anterior | se rechaza: "No entiendo a qué reparación te referís…" |

La medida se ignora. Cada código cuenta como una unidad, y también "2 tapas de acceso", "ambas", "de
entrada de agua y ciego". **Si un ítem tiene 2 unidades, hacen falta 2 fotos de 2 objetos distintos**
(ej: la tapa de la cuba de entrada de agua y la de la cuba ciega), no la misma tapa dos veces. Si un
código es de otro tanque (ej: `TATREA` en la cisterna), el bot avisa.

### Revisión con IA (fase 2)

Cada foto de reparación se revisa con un modelo de OpenAI con visión (`VISION_MODEL`, por defecto
`gpt-6-luna`) en segundo plano: el operario no espera por cada foto, y el resultado le llega como
respuesta a esa foto.

- **Coincide**: "📷 Tapa de acceso ✅" con un botón **[Cambiar]** por si la IA la asignó mal.
- **Es una tapa y la IA no sabe si es de acceso o de inspección** (y se declararon las dos):
  pregunta "¿De cuál tapa es esta foto?" con botones. Si se declaró un solo tipo de tapa, cualquier
  tapa cuenta para ese ítem: no se depende de que la IA distinga el tipo por el tamaño.
- **No coincide** con lo declarado: se saca del apartado, no se adjunta ahí y se le pide que la
  mande con las fotos generales (botón "Sí es de las reparaciones" por si la IA se equivocó).
- **Salió oscura, borrosa o muy de lejos**, o **no muestra el daño**: se le avisa.
- **La IA falla o tarda más de `VISION_TIMEOUT_S`**: la foto queda "sin validar" y cuenta igual.

Al escribir "Listo" el bot muestra cómo quedó cada ítem (✅ / ❌). Para los ítems con 2 o más
unidades, primero descarta las fotos casi idénticas (huella visual, `PHASH_THRESHOLD`) y después le
pregunta a la IA cuántos objetos distintos hay. Si falta algo, el paso se traba con el motivo de
cada ítem (destrabe igual que arriba; el código registra cada ítem que faltaba). Las correcciones del
operario quedan marcadas en el mail. `VISION_ACTIVA=0` apaga la revisión sin tocar el código.

Las fotos generales del final (orden de trabajo, ficha y tanques) no cambiaron.

### Fotos de referencia

Para que la IA distinga mejor cada elemento (sobre todo tapa de acceso vs. inspección), se le
muestran fotos de ejemplo de la empresa junto a cada foto: una carpeta por elemento en
`bot/referencias/` (ver `bot/referencias/LEEME.md`). Van con detalle bajo (`VISION_REF_DETAIL`)
para que no encarezcan cada llamada, y la parte fija del pedido (instrucciones + ejemplos) es igual
en todas las llamadas, así que OpenAI la cachea. Sin fotos en la carpeta, funciona igual que antes.

### Datos para entrenar

Si están `DATASET_SHEET_ID` y `GOOGLE_SERVICE_ACCOUNT_JSON`, al enviar cada reporte se agrega una
fila por foto de reparación a la hoja `Fotos` (`bot/services/dataset_fotos.py`): ítems declarados,
qué vio la IA (`grupo_ia`), a qué ítem quedó asignada (`grupo_final`), si el operario la corrigió, y
el `file_id` de Telegram (con el que el bot puede volver a bajar la foto). No se guardan dirección ni
contacto. Configuración: crear la hoja, compartirla como Editor con el mail de la cuenta de servicio
y cargar las dos variables (la clave de la cuenta de servicio es nueva: las del historial del repo
están comprometidas).

Cómo se usa después:

1. **Medir**: con unas 200-300 filas, el porcentaje de fotos con `corregida_por_operario = sí` es la
   tasa de error de la IA para distinguir los ítems (sobre todo tapa de acceso vs. inspección).
   Comparar cambiando `VISION_MODEL` (ej: `gpt-6-sol`) unos días.
2. **Ejemplos en el prompt**: elegir 3-4 fotos reales bien clasificadas de cada tipo de tapa (filas
   corregidas o validadas), bajarlas con su `file_id` y sumarlas como referencia en
   `vision_service._PROMPT_FOTO`. Es barato y suele mejorar mucho.
3. **Medidas**: la IA no puede medir sin una referencia de escala. Para verificar medidas, pedir que
   la foto tenga una cinta métrica abierta sobre la tapa y probarlo con ~20 fotos.
4. **Entrenar un modelo propio** (fine-tuning), solo si lo anterior no alcanza y hay varios cientos
   de fotos etiquetadas por tipo: la columna `grupo_final` de las filas corregidas es la etiqueta.
   Confirmar en ese momento que OpenAI permite fine-tuning con imágenes del modelo elegido.

## Variables de entorno

Ver [`.env.example`](.env.example). Ningún secreto va al repo.

| Variable | Obligatoria | Uso |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | sí | token del bot |
| `EMAIL_ADDRESS`, `EMAIL_PASSWORD` | sí | cuenta de Gmail que envía los reportes |
| `CC_EMAIL` | no | copia de los reportes |
| `OPENAI_API_KEY` | sí | revisión de fotos con IA |
| `ADMIN_DAILY_CODE` | la escribe el scheduler | código diario del encargado |
| `HEROKU_API_KEY` | para el scheduler | `scripts/generate_daily_code.py` |
| `DESTRABE_MAX_INTENTOS` | no (5) | códigos incorrectos antes de bloquear el destrabe |
| `DESTRABE_MINUTOS_BLOQUEO` | no (15) | minutos de bloqueo |
| `VISION_ACTIVA` | no (1) | 0 apaga la revisión con IA de las fotos |
| `VISION_MODEL` | no (gpt-6-luna) | modelo de OpenAI con visión |
| `VISION_TIMEOUT_S` | no (30) | segundos máximos por foto antes de dejarla sin validar |
| `VISION_REASONING` | no (medium) | esfuerzo de razonamiento del modelo |
| `VISION_MAX_REF` | no (10) | fotos de referencia por elemento |
| `VISION_REF_DETAIL` | no (low) | detalle con que se mandan las referencias (low o high) |
| `PHASH_THRESHOLD` | no (8) | distancia de huella para tomar dos fotos como la misma |
| `DATASET_SHEET_ID` | no | hoja de Google Sheets para los datos de entrenamiento |
| `DATASET_SHEET_NAME` | no (Fotos) | pestaña de esa hoja |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | para datos de entrenamiento y herramientas | cuenta de servicio de Google (JSON en una línea) |
| `GOOGLE_OAUTH_CLIENT_JSON`, `GMAIL_TOKEN_JSON` | herramientas | `extract_reports.py`, `gmail_quickstart.py` |
