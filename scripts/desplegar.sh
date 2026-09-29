#!/usr/bin/env bash
# Despliega a Heroku DESDE TU MAC, solo si el arbol pasa todos los chequeos.
# El auto-deploy desde GitHub queda APAGADO y no se reconecta (ver CLAUDE.md): el 24-ago-2026 el
# atacante hizo force push a main, y con auto-deploy eso se despliega solo.
# Uso: bash scripts/desplegar.sh                  despliega HEAD de main a la app paulistabot
#      bash scripts/desplegar.sh --solo-chequear
#      HEROKU_APP=paulista-bot-test bash scripts/desplegar.sh
set -u
ROOT=$(git rev-parse --show-toplevel) || exit 2
cd "$ROOT"; source scripts/lib-verificar-git.sh
APP="${HEROKU_APP:-paulistabot}"
cancelar() { printf '\033[31mDESPLIEGUE CANCELADO: %s\033[0m\n' "$*"; exit 1; }

echo "1) Chequeo de seguridad del arbol de trabajo"
bash scripts/security-check.sh "$ROOT" || cancelar "el chequeo de seguridad fallo."
echo "2) Prueba de los chequeos de commits"
bash scripts/test-verificar-git.sh >/dev/null || cancelar "scripts/test-verificar-git.sh fallo: los chequeos de commits no son confiables."
echo "3) Chequeo de los ultimos 50 commits y del arbol de HEAD"
FAIL=0; verificar_commits "" HEAD || FAIL=1; verificar_arbol HEAD || FAIL=1
[ $FAIL -ne 0 ] && cancelar "hay commits con firma ajena o payloads."
echo "4) Estado del repo"
# Heroku construye lo que esta COMMITEADO, no lo que hay en disco: el disco tiene que coincidir con HEAD
# para que lo que se chequeo en el paso 1 sea lo que se sube.
[ -z "$(git status --porcelain)" ] || { git status --short | head -15; cancelar "hay cambios sin commitear."; }
[ "$(git rev-parse --abbrev-ref HEAD)" = "main" ] || cancelar "no estas en main."
git fetch -q origin main || cancelar "no se pudo hacer fetch de origin/main."
[ "$(git rev-parse HEAD)" = "$(git rev-parse origin/main)" ] || cancelar "HEAD ($(git rev-parse --short HEAD)) no es origin/main ($(git rev-parse --short origin/main)): subi o actualiza primero (bash scripts/actualizar.sh)."
echo "   HEAD: $(git log -1 --format='%h %s')"
[ "${1:-}" = "--solo-chequear" ] && { printf '\033[32mTodo listo para desplegar a %s (no se desplego).\033[0m\n' "$APP"; exit 0; }

echo "5) git push a Heroku ($APP), sin force"
command -v heroku >/dev/null || cancelar "falta el CLI de Heroku (brew install heroku/brew/heroku) y 'heroku login'."
# Nunca --force: si Heroku rechaza el push porque su historia no coincide, se para y se consulta.
git push "https://git.heroku.com/$APP.git" HEAD:refs/heads/main \
  || cancelar "Heroku rechazo el push. No uses --force sin revisar por que (ver CLAUDE.md)."
printf '\033[32mDesplegado %s a %s.\033[0m\n' "$(git rev-parse --short HEAD)" "$APP"
