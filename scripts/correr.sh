#!/usr/bin/env bash
# Unica forma de ejecutar codigo de este repo: primero security-check.sh, despues Python.
# Nunca llamar a `python main.py` ni a `.venv/bin/python` directo (ver CLAUDE.md).
# Uso: bash scripts/correr.sh                          corre el bot (main.py, lo mismo que el Procfile)
#      bash scripts/correr.sh --script <archivo> [args] corre una herramienta: extract_reports.py,
#                                                       gmail_quickstart.py o scripts/generate_daily_code.py
#      bash scripts/correr.sh --instalar                crea .venv e instala requirements.txt (wheels + hashes)
#      bash scripts/correr.sh --instalar-herramientas   suma requirements-herramientas.txt (para --script)
#      bash scripts/correr.sh --tests                   corre los tests de tests/ (unittest, sin red)
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT" || exit 2
bash scripts/security-check.sh "$ROOT" || { printf '\033[31mNO SE EJECUTO NADA: el chequeo de seguridad fallo.\033[0m\n'; exit 1; }

PY="$ROOT/.venv/bin/python"
# -E ignora PYTHONPATH, PYTHONSTARTUP y demas variables PYTHON*; -s ignora el site-packages del usuario.
PIP=("$PY" -E -s -m pip install --require-hashes)

if [ "${1:-}" = "--instalar" ]; then
  # Heroku corre Python 3.11 (runtime.txt) y requirements.txt esta compilado para 3.11.
  if [ ! -d .venv ]; then
    command -v python3.11 >/dev/null || { echo "Falta Python 3.11 (el mismo de Heroku): brew install python@3.11"; exit 1; }
    python3.11 -m venv .venv || exit 1
  fi
  # 1) setuptools fijado por hash: es lo unico con lo que se construye tornado 6.1.
  #    --force-reinstall: el venv trae el setuptools de ensurepip (del Python instalado, sin verificar);
  #    si la version coincide pip lo daria por instalado sin chequear el hash. Asi sale siempre de PyPI.
  "${PIP[@]}" --only-binary=:all: --force-reinstall -r requirements-build.txt || exit 1
  # 2) Todo lo demas. --only-binary: pip nunca ejecuta setup.py ni build-backends, SALVO tornado 6.1
  #    (unica excepcion aprobada, ver CLAUDE.md: sdist de PyPI fijado por hash). --no-build-isolation:
  #    tornado se construye con el setuptools del paso 1 y no con uno que pip baje sin verificar.
  "${PIP[@]}" --only-binary=:all: --no-binary=tornado --no-build-isolation -r requirements.txt || exit 1
  # Lo recien instalado puede traer .pth o sitecustomize: se vuelve a chequear.
  exec bash scripts/security-check.sh "$ROOT"
fi

[ -x "$PY" ] || { echo "Falta .venv: bash scripts/correr.sh --instalar"; exit 1; }

if [ "${1:-}" = "--instalar-herramientas" ]; then
  "${PIP[@]}" --only-binary=:all: --no-binary=tornado --no-build-isolation -r requirements-herramientas.txt || exit 1
  exec bash scripts/security-check.sh "$ROOT"
fi

if [ "${1:-}" = "--tests" ]; then
  # unittest de la libreria estandar: sin dependencias nuevas. Los tests no usan red ni credenciales reales.
  exec "$PY" -E -s -m unittest discover -s tests -t . -v
fi

if [ "${1:-}" = "--script" ]; then
  shift
  case "${1:-}" in
    extract_reports.py|gmail_quickstart.py|scripts/generate_daily_code.py) ;;
    *) echo "Solo se pueden correr: extract_reports.py, gmail_quickstart.py, scripts/generate_daily_code.py"; exit 1;;
  esac
  exec "$PY" -E -s "$@"
fi

exec "$PY" -E -s main.py "$@"
