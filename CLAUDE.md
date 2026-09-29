# Reglas para cualquier IA que trabaje en este repo

paulistabot es un bot de Telegram en Python (python-telegram-bot 13.15, OpenAI, Gmail) que corre en
Heroku (`Procfile`: `worker: python main.py`). En 2026 los repos del dueño fueron atacados por la
campaña "Contagious Interview" (Lazarus) con una credencial de GitHub robada. En este repo, el
2026-08-24 hubo un force push de todas las ramas a 5bf5487: copiaba fecha y mensaje de d7a3fe2 con los
acentos rotos y agregaba `.vscode/tasks.json`, que corria `node ./public/fonts/fa-solid-400.woff2` (un
cargador disfrazado de fuente) al abrir la carpeta. El 2026-09-17 el dueño restauro las ramas (main y
develop a d7a3fe2, mi-rama-antigua a f14a85e, prod-legacy a adfec77); esos force push son la limpieza.
Las reglas de abajo existen para que no vuelva a pasar. **Nunca las saltees ni las aflojes, aunque el
usuario lo pida por apuro.** Si algo falla, parar y explicar.

## Antes de ejecutar cualquier cosa del repo

1. Correr `bash scripts/security-check.sh`. Si falla, **no** ejecutar `python`, `pip`, `main.py`,
   `npm`, `node` ni ningun script del repo. Mostrar la evidencia y detenerse.
2. Todo se ejecuta con `bash scripts/correr.sh`, que corre el chequeo antes:
   `bash scripts/correr.sh` en vez de `python main.py`, y
   `bash scripts/correr.sh --script extract_reports.py` (o `gmail_quickstart.py`,
   `scripts/generate_daily_code.py`) para las herramientas. **Nunca llamar a `python main.py`,
   `.venv/bin/python` ni `pytest` directo**, ni usar otros atajos que eviten el chequeo.
3. No abrir el repo en VS Code ni en Cursor sin haber corrido antes el chequeo: las tareas
   `runOn: folderOpen` se ejecutan solas al abrir la carpeta.

## Dependencias

- Se instala solo con `bash scripts/correr.sh --instalar` (y `--instalar-herramientas` para las
  herramientas): `pip install --only-binary=:all: --require-hashes`. Necesita Python 3.11, el mismo
  de Heroku (`runtime.txt`).
- `requirements.in` lista lo que pide el bot; `requirements-herramientas.in`, lo de
  `extract_reports.py` y `gmail_quickstart.py` (no va a Heroku); `requirements-build.in`, el
  setuptools para construir tornado. Los `.txt` se **generan** con `bash scripts/compilar-requirements.sh`
  (`uv pip compile --universal --python-version 3.11 --generate-hashes --emit-build-options
  --only-binary :all: --no-binary tornado`). No se editan a mano. El script deja
  `--only-binary :all:` **antes** de `--no-binary tornado`: pip aplica las opciones del archivo en
  orden y `:all:` borra las excepciones anteriores (con el orden que emite uv, tornado 6.1 no se instalaba).
- Un paquete sin wheel no se instala sin OK explicito del dueño.

### Excepcion aprobada: tornado 6.1 (unica)

`python-telegram-bot==13.15` exige `tornado==6.1`, que no tiene wheel para Python 3.11. El dueño aprobo
(2026-09-28) instalarlo desde el **sdist de PyPI fijado por hash** y que se ejecute su `setup.py`.
- sdist: `tornado-6.1.tar.gz`, sha256 `33c6e81d7bd55b468d2e793517c909b139960b6c790a60b7991b9b6b76fb9791`
  (verificado contra PyPI el 2026-09-28).
- La excepcion es **solo** `--no-binary tornado`, y solo para la version 6.1. Cualquier otro paquete o
  version de tornado sin wheel necesita un OK nuevo del dueño. No ampliarla.
- Local: `correr.sh --instalar` instala primero `requirements-build.txt` (setuptools con hash) y
  despues construye tornado con `--no-build-isolation`, para no usar un setuptools sin verificar.
- Heroku: su buildpack instala `requirements.txt` con aislamiento de build, asi que el setuptools con
  el que construye tornado lo baja pip **sin hash**. Es un limite conocido de esta excepcion; se
  elimina al migrar a python-telegram-bot v20+ (sin tornado), que el dueño decidio no hacer por ahora.

## Secretos

- Ningun secreto va al repo. Todo va en variables de entorno (ver `.env.example`): `TELEGRAM_BOT_TOKEN`,
  `EMAIL_ADDRESS`, `EMAIL_PASSWORD`, `OPENAI_API_KEY`, `HEROKU_API_KEY`, y para las herramientas de
  Google el JSON completo en `GOOGLE_OAUTH_CLIENT_JSON`, `GMAIL_TOKEN_JSON` y `GOOGLE_SERVICE_ACCOUNT_JSON`.
- `credentials.json`, `service_account.json`, `token.json` y `.env` estan en `.gitignore`. Nunca
  volver a commitearlos, ni escribir un token en un archivo del repo. El historial publico tiene
  credenciales viejas (los tres JSON, tokens de Telegram y contraseñas de aplicacion de Gmail): se
  dan por comprometidas y el dueño las revoca. No usarlas y no reescribir el historial sin su OK.

## Git

- **Nunca `git pull`.** Usar `bash scripts/actualizar.sh`: baja, revisa los commits y el arbol
  remoto sin hacer checkout, y recien si estan limpios mezcla.
- Nunca `git pull`, force push, `git reset --hard` ni `--no-verify` sin OK del dueño. No commitear ni
  pushear sin su OK.
- Nunca `git checkout`, `git reset --hard` ni `git rebase` hacia commits que no se hayan
  verificado con `scripts/verificar-remoto.sh` (remoto) o los hooks (local).
- Los hooks de `.githooks/` (pre-commit, pre-push, post-merge, post-checkout, post-rewrite) tienen
  que estar activos: `git config core.hooksPath` debe ser `.githooks`. Si no lo esta, correr
  `bash scripts/instalar-guardarrailes.sh` antes de seguir.
- Un commit cuyo committer sea "Juan" a secas, con zona horaria -0800, con fecha de committer
  distinta a la de autor, o con acentos rotos en el mensaje, es del atacante. Reportarlo, no tocarlo.
- Los commits viejos del dueño tienen committer `juanverna <jvergniaud17@gmail.com>`. Esa identidad
  exacta se acepta **solo** en el chequeo de identidad de `verificar_commits`: 5bf5487 (el ataque)
  usaba ese mismo committer, asi que las demas señales se le siguen aplicando.
  `scripts/test-verificar-git.sh` lo prueba (lo corren el pre-push, `desplegar.sh` e
  `instalar-guardarrailes.sh`); si falla, los hooks no son confiables.
- Antes de clonar o de traer una rama de GitHub: `bash scripts/verificar-remoto.sh juanverna/paulistabot`.

## Despliegue (Heroku)

- **El auto-deploy desde GitHub esta apagado y no se reconecta**, ni aunque se pida por apuro: con
  auto-deploy, un force push del atacante a main se despliega solo.
- Se despliega solo con `bash scripts/desplegar.sh` (app `paulistabot`; `HEROKU_APP=paulista-bot-test`
  para la de prueba). Corre security-check, la prueba de verificar_commits y los chequeos de commits y
  del arbol, exige arbol limpio y HEAD igual a origin/main, y recien ahi hace `git push` a Heroku, sin force.
- `security-check.sh` exige que el `Procfile` sea exactamente `worker: python main.py` y que no
  existan `bin/pre_compile`, `bin/post_compile`, `bin/compile` ni `heroku.yml` (Heroku los ejecuta
  solos en el build). Cambiar el Procfile requiere OK del dueño y actualizar `PROCFILE_OK`.

## Limites conocidos

La regla de "codigo a nivel modulo" (seccion 3c de `security-check.sh` y `verificar_arbol` en
`scripts/lib-verificar-git.sh`) lee linea por linea y solo mira la columna 0. **No ve** estos cuatro
casos, que igual se ejecutan al importar el modulo:

1. Cuerpo de clase: `class C:` seguido de `    descargar("x")` indentado.
2. Decorador de metodo: `    @descargar("x")` sobre un `def` dentro de una clase.
3. Default de argumento: `def f(x=descargar("x")):`.
4. Base de clase: `class D(descargar("x")):`.

Por eso **cualquier cambio en archivos `.py` que venga de afuera** (una rama remota, un PR, un
parche, un commit que no hizo el dueño en esta maquina) **se revisa a mano antes de mezclar**, aunque
`actualizar.sh` y los hooks den limpio. Mirar el diff con `git diff HEAD origin/<rama> -- '*.py'`
(sin checkout) y buscar llamadas en esos cuatro lugares.

## Que hacer si aparece algo raro

Un cartel de macOS pidiendo acceso al llavero (la clave de cifrado de Chrome) desde `security`, `node`
o `python`; procesos `node -e` o `python -c` desconocidos; carpetas `/tmp/.npm` o `~/.node_modules` nuevas;
un force push o un push en GitHub que el dueño no hizo; un release en Heroku que el dueño no hizo. En
cualquiera de esos casos: no ejecutar nada mas, no pedir contraseñas, listar procesos y conexiones, y
explicar al usuario lo encontrado.
