#!/usr/bin/env bash
# Prueba de verificar_commits (scripts/lib-verificar-git.sh), sobre todo de la excepcion de identidad vieja:
# "juanverna <email del dueño>" se acepta como identidad, pero un commit con ese committer y cualquier
# otra señal del atacante (acentos rotos, fecha de committer distinta, zona -0800) TIENE que frenar.
# El commit del atacante 5bf5487 era justamente: committer juanverna + mensaje de d7a3fe2 con acentos rotos.
# No toca el repo: arma uno temporal y lo borra al salir. Uso: bash scripts/test-verificar-git.sh
set -u
LIB="$(cd "$(dirname "$0")" && pwd)/lib-verificar-git.sh"
TMP=$(mktemp -d) || exit 2
trap 'rm -rf "$TMP"' EXIT
cd "$TMP" || exit 2
git init -q .
git config user.name "Juan Verna"
git config user.email "dueno@example.com"
git config core.hooksPath /dev/null
source "$LIB"

FALLAS=0
# caso <descripcion> <espera: pasa|frena> <committer nombre> <committer email> <fecha autor> <fecha committer> <mensaje>
caso() {
  local desc="$1" espera="$2" cn="$3" ce="$4" ad="$5" cd="$6" msg="$7" antes despues obtenido
  antes=$(git rev-parse -q --verify HEAD || echo "")
  echo "$desc" >> archivo.txt; git add archivo.txt
  GIT_AUTHOR_NAME="$cn" GIT_AUTHOR_EMAIL="$ce" GIT_AUTHOR_DATE="$ad" \
  GIT_COMMITTER_NAME="$cn" GIT_COMMITTER_EMAIL="$ce" GIT_COMMITTER_DATE="$cd" \
    git commit -q -m "$msg" || { echo "no se pudo crear el commit de prueba"; exit 2; }
  despues=$(git rev-parse HEAD)
  if verificar_commits "$antes" "$despues" >/dev/null; then obtenido=pasa; else obtenido=frena; fi
  if [ "$obtenido" = "$espera" ]; then
    printf '  \033[32m✓\033[0m %-62s %s\n' "$desc" "$obtenido"
  else
    FALLAS=1; printf '  \033[31m✗ %-62s esperaba %s, dio %s\033[0m\n' "$desc" "$espera" "$obtenido"
  fi
}

F='2026-04-22T11:32:39-03:00'
echo "test-verificar-git: verificar_commits con la identidad vieja juanverna"
caso "identidad actual, commit normal"                         pasa  "Juan Verna" dueno@example.com "$F" "$F" "fix: QR con múltiples métodos"
caso "juanverna + email del dueño, commit normal"              pasa  "juanverna"  dueno@example.com "$F" "$F" "fix: QR con múltiples métodos"
caso "juanverna + acentos rotos (├║), como 5bf5487"            frena "juanverna"  dueno@example.com "$F" "$F" "fix: QR con m├║ltiples m├®todos de decodificaci├│n"
caso "juanverna + acentos rotos (Ã)"                           frena "juanverna"  dueno@example.com "$F" "$F" "fix: QR con mÃºltiples mÃ©todos"
caso "juanverna + caracter de reemplazo (U+FFFD)"              frena "juanverna"  dueno@example.com "$F" "$F" "fix: QR con m�ltiples m�todos"
caso "juanverna + fecha de committer distinta a la de autor"   frena "juanverna"  dueno@example.com "$F" "2026-08-24T10:00:00-03:00" "fix: QR con múltiples métodos"
caso "juanverna + zona -0800"                                  frena "juanverna"  dueno@example.com "2026-08-24T10:00:00-08:00" "2026-08-24T10:00:00-08:00" "fix: QR"
caso "juanverna con OTRO email"                                frena "juanverna"  otro@example.com  "$F" "$F" "fix: QR con múltiples métodos"
caso "committer \"Juan\" a secas"                               frena "Juan"       dueno@example.com "$F" "$F" "fix: QR con múltiples métodos"
echo
if [ "$FALLAS" -ne 0 ]; then
  printf '\033[31mtest-verificar-git: FALLO. verificar_commits no frena lo que tiene que frenar: no confies en los hooks.\033[0m\n'; exit 1
fi
echo "test-verificar-git: todo OK."
