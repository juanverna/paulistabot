#!/usr/bin/env bash
# security-check.sh — guardarrail contra la reinfeccion por "Contagious Interview" (Lazarus).
#
# Historia: en 2026 el malware vivia al final de la linea 10 de postcss.config.js,
# empujado fuera de pantalla con miles de espacios, y se ejecutaba con cada `npm run dev`
# o build de Vite. Este script falla (exit 1) si vuelve a aparecer algo parecido:
#
#   1. lineas de mas de 300 caracteres en archivos de configuracion
#   2. cualquier IOC conocido de la campaña (IPs, strings, hosts RPC de blockchain)
#   3. el patron del loader: global['r']=require / global['m']=module, o
#      createRequire(import.meta.url) dentro de un archivo de configuracion
#   4. scripts de ciclo de vida (preinstall/install/postinstall/prepare/prepack) en package.json
#   5. entradas "resolved" del package-lock que no apunten a https://registry.npmjs.org/
#
# Copiado de swap-ig-generator (mismas reglas) y adaptado a paulistabot (bot de Telegram en Python,
# desplegado en Heroku). Sumado a lo anterior:
#   - la sanidad exige al menos 3 archivos de configuracion de PYTHON (requirements, yaml, ...)
#   - codigo que ejecuta o importa dinamicamente en cualquier .py (exec/eval/subprocess/...)
#   - codigo ejecutable a nivel modulo en __init__.py; build-backend de pyproject.toml
#   - requirements con indices/URLs ajenos a PyPI, o sin version fijada y --hash
#   - .vscode/*.json y *.code-workspace con tareas runOn=folderOpen
#   - dentro de .venv: .pth con codigo no conocido, sitecustomize.py, usercustomize.py, pip.conf
#   - Heroku: el Procfile tiene que ser exactamente el conocido, y no puede haber bin/pre_compile,
#     bin/post_compile ni heroku.yml (el buildpack los ejecuta solos en cada deploy)
#
# Corre en macOS (BSD awk/grep) y en Ubuntu (GNU). Solo usa bash, find, awk y grep.
# Uso: bash scripts/security-check.sh [directorio]   (por defecto, la raiz del repo)

set -u
ROOT="${1:-$(cd "$(dirname "$0")/.." && pwd)}"
cd "$ROOT" || exit 2
export LC_ALL=C

FAIL=0
fail() { FAIL=1; printf '\n\033[31m[FALLA]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[OK]\033[0m %s\n' "$*"; }
# Muestra evidencia legible: colapsa corridas de blancos (el relleno con el que se esconde
# el payload) a " <...N blancos...> " y recorta a 220 caracteres.
show() { sed "s/[[:space:]]\{3,\}/ <...relleno...> /g" | cut -c1-220; }

# Directorios que nunca se inspeccionan (no son fuente).
# find_src <expresion find...>: recorre el arbol saltando esos directorios.
find_src() {
  find . \( -path ./node_modules -o -path ./.git -o -path ./dist -o -path ./client/dist -o -path ./.venv -o -name __pycache__ \) -prune -o "$@" -print
}
# Este mismo script contiene la lista de IOCs: se excluye del grep de IOCs.
SELF='./scripts/security-check.sh'
# Tambien se excluyen sus COPIAS: un `git worktree` (por ejemplo los que crea
# Claude Code en .claude/worktrees/) es una copia completa del repo, con este
# script adentro, y puede estar en otra rama con otra version del script.
#
# Se excluye por CONTENIDO, nunca por carpeta: una copia vale solo si es identica
# byte a byte a este archivo, o a alguna version de scripts/security-check.sh que
# este COMMITEADA en el historial de HEAD (se compara el hash del blob). Asi
# un worktree con un cargador de verdad sigue disparando la alarma, y una copia
# del script con una sola linea cambiada a mano tambien. Sin git (Docker, CI sin
# .git) solo vale la comparacion byte a byte.
KNOWN_BLOBS=""
if command -v git >/dev/null 2>&1 && git rev-parse --git-dir >/dev/null 2>&1; then
  # Solo el historial de HEAD, no --all: una rama remota recien bajada o un stash
  # no pueden ampliar la lista de contenidos que se dan por buenos.
  KNOWN_BLOBS=$(git log HEAD --format=%H -- scripts/security-check.sh 2>/dev/null \
    | while IFS= read -r c; do git rev-parse -q --verify "$c:scripts/security-check.sh" 2>/dev/null; done | sort -u)
fi
es_copia_conocida() {
  cmp -s "$1" "$SELF" && return 0
  [ -n "$KNOWN_BLOBS" ] || return 1
  local h; h=$(git hash-object "$1" 2>/dev/null) || return 1
  printf '%s\n' "$KNOWN_BLOBS" | grep -qxF "$h"
}
SELF_COPIES=$(find . \( -path ./node_modules -o -path ./.git \) -prune -o -type f -name 'security-check.sh' -print 2>/dev/null \
  | while IFS= read -r f; do es_copia_conocida "$f" && printf '%s:\n' "$f"; done)
# Saca SOLO las lineas cuyo PREFIJO es "<ruta de una copia>:", igual que hacia el
# `grep -v "^$SELF:"` original. Nunca por subcadena: si bastara con que la linea
# CONTENGA la ruta, cualquier archivo podria esconder un cargador escribiendo
# "./scripts/security-check.sh:" en un comentario de la misma linea.
sin_copias_propias() {
  if [ -z "$SELF_COPIES" ]; then cat; return; fi
  COPIAS="$SELF_COPIES" awk '
    BEGIN { n = split(ENVIRON["COPIAS"], c, "\n") }
    { for (i = 1; i <= n; i++) if (c[i] != "" && index($0, c[i]) == 1) next; print }'
}

# ---------- 1. lineas largas en archivos de configuracion ----------
MAX_CONFIG=300
CONFIG_FILES=$(find_src -type f \( -name '*.config.js' -o -name '*.config.ts' -o -name '*.config.mjs' \
  -o -name '*.config.cjs' -o -name 'tsconfig*' -o -name 'drizzle*' -o -name 'vite*' -o -name 'vitest*' \
  -o -name 'postcss*' -o -name 'tailwind*' -o -name 'package.json' -o -name '.npmrc' \
  -o -name 'tasks.json' -o -name 'Dockerfile*' -o -name '.eslintrc*' -o -name 'babel*' -o -name 'next.config*' \
  -o -name 'webpack*' -o -name 'jest*' -o -name 'rollup*' -o -name 'esbuild*' \) | sort)
# Configuracion de Python: la cargan pip, pytest, pre-commit, VS Code, GitHub o el propio programa.
PY_CONFIG_FILES=$(find_src -type f \( -name 'requirements*.txt' -o -name 'requirements*.in' -o -name 'pyproject.toml' \
  -o -name 'setup.py' -o -name 'setup.cfg' -o -name 'conftest.py' -o -name 'tox.ini' -o -name 'pytest.ini' \
  -o -name 'pip.conf' -o -name '*.yaml' -o -name '*.yml' -o -name '.env.example' -o -name '*.code-workspace' \
  -o -path '*/.vscode/*.json' -o -path './.github/workflows/*' \
  -o -name 'Procfile' -o -name 'runtime.txt' -o -name '.python-version' -o -name 'Aptfile' -o -name 'app.json' \) | sort)
CONFIG_FILES=$(printf '%s\n%s\n' "$CONFIG_FILES" "$PY_CONFIG_FILES" | grep . | sort -u)
N_CONFIG=$(printf '%s\n' "$CONFIG_FILES" | grep -c .)
N_PY_CONFIG=$(printf '%s\n' "$PY_CONFIG_FILES" | grep -c .)
# Sanidad: si no encuentra archivos de configuracion de Python, el chequeo no esta mirando el arbol correcto.
if [ "$N_PY_CONFIG" -lt 3 ]; then
  fail "solo se encontraron $N_PY_CONFIG archivos de configuracion de Python; el script no esta viendo el repo (cwd: $(pwd))"
fi

HITS=$(printf '%s\n' "$CONFIG_FILES" | while IFS= read -r f; do
  [ -n "$f" ] && awk -v max="$MAX_CONFIG" -v f="$f" 'length($0) > max { printf "%s:%d: %d chars\n", f, FNR, length($0) }' "$f"
done)
if [ -n "$HITS" ]; then
  fail "lineas de mas de $MAX_CONFIG caracteres en archivos de configuracion:"
  printf '%s\n' "$HITS"
else
  ok "ningun archivo de configuracion tiene lineas de mas de $MAX_CONFIG caracteres ($N_CONFIG archivos revisados)"
fi

# ---------- 2. IOCs ----------
IOCS=(
  # IPs de C2
  "194.11.226.41" "193.247.144.38"
  # strings del payload
  "tg14xq" "VSCodeUpdater" "RS260605" "verify-human" "q4FZkxX" "Sec-V" "zRlY7_JxvFY8"
  # etapa blockchain: el proyecto NO usa cripto, cualquier aparicion es maliciosa
  "blastapi.io" "1rpc.io" "drpc.org" "geomi.dev" "eth_blockNumber" "eth_getTransaction"
  # incidente 2026-09-16: canal, C2 por wallet ETH, rutas y strings del loader, herramientas de propagacion
  "A8-3489" "hellopipbot" "X-Payload-B64" "BLOCK_MULTIPLE" "NONCE_FANOUT"
  "a322E5f3D311D3080e6f0121063e9aDC2490Ef1a" "publicnode.com" "blockscout.com"
  "Chrome Safe Storage" "find-generic-password" "temp_auto_push" "temp_interactive_push"
)
GREP_ARGS=()
for i in "${IOCS[@]}"; do GREP_ARGS+=(-e "$i"); done
IOC_HITS=$(grep -rnaF --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=dist --exclude-dir=.venv --exclude-dir=__pycache__ "${GREP_ARGS[@]}" . 2>/dev/null | sin_copias_propias)
if [ -n "$IOC_HITS" ]; then
  fail "indicadores de compromiso encontrados:"
  printf '%s\n' "$IOC_HITS" | show
else
  ok "ningun IOC en el arbol (${#IOCS[@]} indicadores buscados)"
fi

# ---------- 3. patron del loader ----------
LOADER_HITS=$(grep -rnaE --exclude-dir=node_modules --exclude-dir=.git --exclude-dir=dist --exclude-dir=.venv --exclude-dir=__pycache__ \
  -e "global\[['\"]r['\"]\] *= *require" -e "global\[['\"]m['\"]\] *= *module" \
  -e "globalThis\[['\"][rm]['\"]\] *=" . 2>/dev/null | sin_copias_propias)
CFG_REQUIRE_HITS=$(printf '%s\n' "$CONFIG_FILES" | while IFS= read -r f; do
  [ -n "$f" ] && grep -naE "createRequire\(|child_process|eval\(|new Function\(|fromCharCode|Buffer\.from\([^)]*(base64|hex)" "$f" | sed "s|^|$f:|"
done)
if [ -n "$LOADER_HITS" ] || [ -n "$CFG_REQUIRE_HITS" ]; then
  fail "patron de loader malicioso:"
  printf '%s\n%s\n' "$LOADER_HITS" "$CFG_REQUIRE_HITS" | grep . | show
else
  ok "sin patron de loader (global['r']/['m'], createRequire/eval/child_process en configs)"
fi

# ---------- 3b. Python: ejecucion o importacion dinamica en cualquier .py ----------
# El equivalente Python del cargador: exec/eval/compile sueltos (no re.compile ni ast.literal_eval),
# __import__/importlib, procesos hijos, marshal y base64 decodificado desde un literal.
PY_FILES=$(find_src -type f -name '*.py' | sort)
PY_HITS=$(printf '%s\n' "$PY_FILES" | while IFS= read -r f; do
  [ -n "$f" ] && grep -naE "(^|[^.[:alnum:]_])(exec|eval|compile|__import__)[[:space:]]*\(|importlib|subprocess|os\.(system|popen|spawn|exec)|pty\.spawn|marshal\.|b64decode\([[:space:]]*b?['\"]|codecs\.decode\(" "$f" | sed "s|^|$f:|"
done)
if [ -n "$PY_HITS" ]; then
  fail "codigo Python que ejecuta o importa dinamicamente:"
  printf '%s\n' "$PY_HITS" | show
else
  ok "ningun .py usa exec/eval/compile/__import__/importlib/subprocess/os.system/marshal ($(printf '%s\n' "$PY_FILES" | grep -c .) archivos)"
fi

# ---------- 3c. Python: codigo que se ejecuta al importar (__init__.py, conftest.py) ----------
# A nivel modulo solo se aceptan docstrings, comentarios, imports, def/class, decoradores de una lista
# corta (con argumentos por nombre y valores simples) y asignaciones SIN llamadas (NOMBRE = {...}).
# Cualquier otra sentencia en columna 0, incluido un decorador desconocido, se ejecuta
# sola con el primer import del paquete.
INIT_HITS=$(find_src -type f \( -name '__init__.py' -o -name 'conftest.py' \) | while IFS= read -r f; do
  awk -v f="$f" '
    { l = $0; nq = gsub(/"""|'"'''"'/, "&", l) }
    doc { if (nq % 2 == 1) doc = 0; next }
    /^[[:space:]]/ || /^$/ || /^#/ { next }
    /^("""|'"'''"')/ { if (nq % 2 == 1) doc = 1; next }
    /^(import|from|def|class|async def)[[:space:]]/ || /^[)\]}]/ { next }
    /^@(pytest\.fixture|dataclass|dataclasses\.dataclass|property|staticmethod|classmethod|functools\.[A-Za-z_]+)[[:space:]]*(\(([[:space:]]*[A-Za-z_]+[[:space:]]*=[[:space:]]*(True|False|None|[0-9]+|"[A-Za-z0-9_-]*"|'"'"'[A-Za-z0-9_-]*'"'"')[[:space:]]*,?)*\))?[[:space:]]*(#.*)?$/ { next }
    /^[A-Za-z_][A-Za-z0-9_]*[[:space:]]*(:[^=]*)?=[^=(]*$/ { next }
    { printf "%s:%d: %s\n", f, FNR, $0 }' "$f"
done)
if [ -n "$INIT_HITS" ]; then
  fail "__init__.py o conftest.py con codigo ejecutable a nivel modulo:"
  printf '%s\n' "$INIT_HITS" | show
else
  ok "ningun __init__.py ni conftest.py ejecuta codigo a nivel modulo"
fi

# ---------- 3d. Python: build-backend de pyproject.toml ----------
# pip ejecuta el build-backend al instalar desde fuente; backend-path lo carga desde el propio repo.
PYPROJECT_HITS=$(find_src -type f -name pyproject.toml | while IFS= read -r f; do
  grep -nE '^[[:space:]]*backend-path[[:space:]]*=' "$f" | sed "s|^|$f:|"
  grep -nE '^[[:space:]]*build-backend[[:space:]]*=' "$f" \
    | grep -vE "=[[:space:]]*[\"'](setuptools\.build_meta|hatchling\.build|flit_core\.buildapi|poetry\.core\.masonry\.api|pdm\.backend)[\"']" \
    | sed "s|^|$f:|"
done)
if [ -n "$PYPROJECT_HITS" ]; then
  fail "pyproject.toml con build-backend desconocido o backend-path (codigo que pip ejecuta al instalar):"
  printf '%s\n' "$PYPROJECT_HITS" | show
else
  ok "ningun pyproject.toml con build-backend desconocido ni backend-path"
fi

# ---------- 4. scripts de ciclo de vida en package.json ----------
LIFECYCLE_HITS=$(printf '%s\n' "$CONFIG_FILES" | grep '/package\.json$' | while IFS= read -r f; do
  grep -nE '"(preinstall|install|postinstall|prepare|prepack|postpack|prepublish|prepublishOnly)"[[:space:]]*:' "$f" | sed "s|^|$f:|"
done)
if [ -n "$LIFECYCLE_HITS" ]; then
  fail "scripts de ciclo de vida en package.json (se ejecutan solos en npm install):"
  printf '%s\n' "$LIFECYCLE_HITS"
else
  ok "sin preinstall/install/postinstall/prepare/prepack en ningun package.json"
fi

# ---------- 5. package-lock: solo registry.npmjs.org ----------
LOCK_BAD=""
for lock in $(find_src -name package-lock.json); do
  bad=$(grep -n '"resolved":' "$lock" | grep -v '"resolved": "https://registry.npmjs.org/' | sed "s|^|$lock:|")
  [ -n "$bad" ] && LOCK_BAD="$LOCK_BAD$bad"$'\n'
done
if [ -n "$LOCK_BAD" ]; then
  fail "package-lock con paquetes resueltos fuera de https://registry.npmjs.org/:"
  printf '%s' "$LOCK_BAD" | show
else
  ok "todas las entradas resolved del package-lock apuntan a https://registry.npmjs.org/"
fi

# ---------- 5b. requirements: solo PyPI, versiones fijadas y con --hash ----------
# Equivalente al "resolved" del package-lock: nada de indices alternativos, URLs, git+ ni rutas
# locales. Ademas cada paquete de requirements*.txt (el compilado) tiene que estar fijado con ==
# y llevar al menos un --hash, para que `pip install --require-hashes` no acepte otra cosa.
REQ_BAD=""
for req in $(find_src -type f \( -name 'requirements*.txt' -o -name 'requirements*.in' -o -name 'pip.conf' \)); do
  bad=$(grep -nE '(^|[[:space:]])(-i|-f|-e|--index-url|--extra-index-url|--find-links|--trusted-host|--editable|index-url|extra-index-url|find-links|trusted-host)([[:space:]=]|$)|[a-z+]+://|@[[:space:]]*(file|git|http)|^[[:space:]]*[./~]' "$req" \
    | grep -vE '^[0-9]+:[[:space:]]*#' | sed "s|^|$req:|")
  [ -n "$bad" ] && REQ_BAD="$REQ_BAD$bad"$'\n'
  case "$req" in *.txt)
    bad=$(awk -v f="$req" '
      function cerrar() { if (pkg != "" && !hash) printf "%s:%d: %s sin --hash\n", f, linea, pkg; pkg = "" }
      /^[A-Za-z0-9]/ { cerrar(); pkg = $1; linea = FNR; hash = 0
                       if (pkg !~ /==/) printf "%s:%d: %s sin version fijada (==)\n", f, FNR, pkg }
      /--hash=sha256:[0-9a-f]{64}/ { hash = 1 }
      END { cerrar() }' "$req")
    [ -n "$bad" ] && REQ_BAD="$REQ_BAD$bad"$'\n' ;;
  esac
done
if [ -n "$REQ_BAD" ]; then
  fail "requirements con fuentes ajenas a PyPI, sin version fijada o sin --hash:"
  printf '%s' "$REQ_BAD" | show
else
  ok "requirements: solo PyPI, versiones fijadas y todas con --hash"
fi

# ---------- 6. fuentes e imagenes que en realidad son texto (payload disfrazado) ----------
FAKE_BIN=""
while IFS= read -r f; do
  [ -z "$f" ] && continue
  h=$(od -An -tx1 -N8 "$f" 2>/dev/null | tr -d ' \n')
  case "$h" in
    774f4646*|774f4632*|00010000*|4f54544f*|89504e47*|ffd8ff*|47494638*|52494646*|00000100*|0000020*|3c737667*|3c3f786d*|efbbbf3c*) ;;
    *) FAKE_BIN="$FAKE_BIN$f (empieza con $h)"$'\n' ;;
  esac
done < <(find_src -type f \( -iname '*.woff' -o -iname '*.woff2' -o -iname '*.ttf' -o -iname '*.otf' -o -iname '*.eot' \
  -o -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.gif' -o -iname '*.ico' -o -iname '*.webp' \))
if [ -n "$FAKE_BIN" ]; then
  fail "archivos de fuente/imagen sin la cabecera de su formato (asi se disfraza el cargador):"
  printf '%s' "$FAKE_BIN"
else
  ok "todas las fuentes e imagenes tienen cabecera de su formato"
fi

# ---------- 7. tareas de VS Code que se ejecutan solas al abrir la carpeta ----------
# tasks.json, settings.json y *.code-workspace pueden declarar tareas; allowAutomaticTasks las habilita
# sin preguntar. Se mira aunque .vscode/ no exista hoy, para que salte si aparece.
TASKS_HITS=$(find_src -type f \( -path '*/.vscode/*.json' -o -name '*.code-workspace' \) \
  -exec grep -nHE '"runOn"[[:space:]]*:[[:space:]]*"folderOpen"|"task\.allowAutomaticTasks"[[:space:]]*:[[:space:]]*"on"' {} \; 2>/dev/null)
if [ -n "$TASKS_HITS" ]; then
  fail "tareas de VS Code con runOn=folderOpen o allowAutomaticTasks (se ejecutan solas al abrir el proyecto):"
  printf '%s\n' "$TASKS_HITS"
else
  ok "sin tareas de VS Code que se ejecuten al abrir la carpeta"
fi

# ---------- 8. hooks de git activados (solo en clones locales, no en CI ni en Docker) ----------
if [ -z "${CI:-}" ] && [ -d .git ] && [ -d .githooks ]; then
  if [ "$(git config core.hooksPath 2>/dev/null)" = ".githooks" ]; then
    ok "hooks de git activados (.githooks)"
  else
    fail "los hooks de git no estan activados en este clon. Corre: bash scripts/instalar-guardarrailes.sh"
  fi
fi

# ---------- 9. .venv: codigo que Python ejecuta solo al arrancar ----------
# Python ejecuta al iniciar toda linea "import ..." de un .pth en site-packages, y los modulos
# sitecustomize/usercustomize. Un .pth con codigo se acepta SOLO si su contenido (sha256) es uno
# conocido, nunca por nombre ni por carpeta. Uno de solo rutas no ejecuta nada.
PTH_OK=(
  # setuptools 58.0.4, verificado contra el wheel de PyPI: distutils-precedence.pth (activa _distutils_hack solo si SETUPTOOLS_USE_DISTUTILS=local)
  "7ea7ffef3fe2a117ee12c68ed6553617f0d7fd2f0590257c25c484959a3b7373"
)
sha256() { { shasum -a 256 "$1" 2>/dev/null || sha256sum "$1"; } | cut -d' ' -f1; }
VENV_BAD=""
if [ -d .venv ]; then
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    grep -qE '^[[:space:]]*import[[:space:]]' "$f" || continue
    h=$(sha256 "$f")
    printf '%s\n' "${PTH_OK[@]}" | grep -qxF "$h" && continue
    VENV_BAD="$VENV_BAD$f: .pth con codigo desconocido (sha256 $h): $(grep -m1 -E '^[[:space:]]*import' "$f")"$'\n'
  done < <(find .venv -type f -name '*.pth' 2>/dev/null)
  while IFS= read -r f; do
    [ -n "$f" ] && VENV_BAD="$VENV_BAD$f: se carga solo (Python al arrancar, o pip al instalar)"$'\n'
  done < <(find .venv -type f \( -name 'sitecustomize.py' -o -name 'usercustomize.py' -o -name 'pip.conf' \) 2>/dev/null)
fi
if [ -n "$VENV_BAD" ]; then
  fail ".venv con codigo que se ejecuta al arrancar Python:"
  printf '%s' "$VENV_BAD" | show
else
  ok ".venv sin .pth desconocidos, sitecustomize, usercustomize ni pip.conf"
fi

# ---------- 10. Heroku: lo que el buildpack y el dyno ejecutan solos ----------
# El Procfile decide que comando corre el dyno; bin/pre_compile y bin/post_compile los ejecuta el
# buildpack de Python en cada deploy; heroku.yml cambia el build entero. Nada de eso tiene que cambiar
# sin que el dueño lo sepa: si hace falta cambiar el Procfile, se cambia tambien PROCFILE_OK de aca.
PROCFILE_OK='worker: python main.py'
HEROKU_BAD=""
if [ -f Procfile ]; then
  [ "$(cat Procfile)" = "$PROCFILE_OK" ] || HEROKU_BAD="${HEROKU_BAD}Procfile distinto del conocido ('$PROCFILE_OK'): $(head -c 200 Procfile | tr '\n' ' ')"$'\n'
fi
for f in bin/pre_compile bin/post_compile bin/compile heroku.yml; do
  [ -e "$f" ] && HEROKU_BAD="${HEROKU_BAD}$f existe (se ejecuta solo en el build de Heroku)"$'\n'
done
if [ -n "$HEROKU_BAD" ]; then
  fail "configuracion de Heroku que ejecuta codigo inesperado:"
  printf '%s' "$HEROKU_BAD" | show
else
  ok "Heroku: Procfile conocido, sin bin/pre_compile, bin/post_compile ni heroku.yml"
fi

echo
if [ "$FAIL" -ne 0 ]; then
  echo "security-check: FALLO. No instales, no buildees, no ejecutes nada de este arbol hasta revisar la evidencia de arriba."
  exit 1
fi
echo "security-check: todo limpio."
