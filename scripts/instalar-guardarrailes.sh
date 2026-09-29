#!/usr/bin/env bash
# Correr UNA vez en cada clon nuevo (o en cada computadora nueva). Idempotente.
# Activa los hooks versionados en .githooks/ y comprueba la configuracion minima.
set -u
ROOT=$(git rev-parse --show-toplevel) || { echo "Corre esto dentro del repo."; exit 2; }
cd "$ROOT"
chmod +x .githooks/* scripts/*.sh 2>/dev/null
git config core.hooksPath .githooks
echo "✓ hooks activados: $(ls .githooks | tr '\n' ' ')"
if [ -z "$(git config user.name)" ] || [ -z "$(git config user.email)" ]; then
  echo "✗ falta configurar tu identidad de git (los hooks la usan para detectar commits ajenos):"
  echo "    git config user.name \"Juan Verna\" && git config user.email \"tu@email\""
else
  echo "✓ identidad git: $(git config user.name) <$(git config user.email)>"
fi
grep -q '^ignore-scripts=true' .npmrc 2>/dev/null && echo "✓ .npmrc con ignore-scripts=true" || echo "✗ .npmrc sin ignore-scripts=true"
for req in requirements.txt requirements-build.txt requirements-herramientas.txt; do
  grep -q -- '--hash=sha256:' "$req" 2>/dev/null && echo "✓ $req con versiones fijadas y hashes" || echo "✗ $req sin hashes: NO instales dependencias"
done
command -v python3.11 >/dev/null && echo "✓ Python 3.11 (el de Heroku) instalado" || echo "· falta Python 3.11 para correr el bot local: brew install python@3.11"
command -v gh >/dev/null && echo "✓ gh instalado (para scripts/verificar-remoto.sh)" || echo "· gh no instalado: brew install gh (opcional, sirve para verificar repos antes de clonar)"
command -v heroku >/dev/null && echo "✓ CLI de Heroku instalado (para scripts/desplegar.sh)" || echo "· CLI de Heroku no instalado: brew install heroku/brew/heroku (solo para desplegar)"
echo
bash scripts/test-verificar-git.sh || exit 1
echo
bash scripts/security-check.sh "$ROOT" && echo "Listo. Reglas: git pull -> bash scripts/actualizar.sh | ejecutar -> bash scripts/correr.sh | desplegar -> bash scripts/desplegar.sh"
