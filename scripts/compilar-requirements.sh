#!/usr/bin/env bash
# Genera requirements.txt, requirements-build.txt y requirements-herramientas.txt desde sus .in.
# Los .txt NO se editan a mano: se regeneran con este script (ver CLAUDE.md).
#
# uv escribe "--no-binary tornado" ANTES de "--only-binary :all:", y pip aplica las opciones del
# archivo en orden: ":all:" borra las excepciones anteriores, asi que la de tornado (unica aprobada)
# se perdia y pip no encontraba tornado 6.1 (ni local ni en Heroku). Por eso, despues de compilar,
# se deja siempre "--only-binary :all:" primero y "--no-binary tornado" una sola vez despues.
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
command -v uv >/dev/null || { echo "Falta uv: brew install uv"; exit 1; }

OPCIONES=(--universal --python-version 3.11 --generate-hashes --emit-build-options --no-header
          --only-binary :all: --no-binary tornado)

ordenar_opciones() {
  local tmp
  tmp=$(mktemp)
  { printf '%s\n' "--only-binary :all:" "--no-binary tornado"
    grep -vxE -- '--only-binary :all:|--no-binary tornado' "$1"; } > "$tmp"
  mv "$tmp" "$1"
}

uv pip compile requirements.in -o requirements.txt "${OPCIONES[@]}"
uv pip compile requirements-build.in -c requirements.txt -o requirements-build.txt "${OPCIONES[@]}"
uv pip compile requirements-herramientas.in -c requirements.txt -o requirements-herramientas.txt "${OPCIONES[@]}"
for f in requirements.txt requirements-build.txt requirements-herramientas.txt; do
  ordenar_opciones "$f"
done
echo "OK: requirements*.txt regenerados. Revisar con: git diff -- 'requirements*.txt'"
