#!/usr/bin/env bash
# Reemplaza a `git pull`. Baja los cambios, los revisa SIN tocar tu arbol de trabajo,
# y recien si estan limpios los mezcla. Uso: bash scripts/actualizar.sh [rama]
set -u
ROOT=$(git rev-parse --show-toplevel) || exit 2
cd "$ROOT"; source scripts/lib-verificar-git.sh
RAMA="${1:-$(git rev-parse --abbrev-ref HEAD)}"
ANTES=$(git rev-parse "origin/$RAMA" 2>/dev/null || echo "")
echo "1) Bajando origin/$RAMA (sin mezclar)..."
SALIDA=$(git fetch origin "$RAMA" 2>&1); RC=$?
[ $RC -ne 0 ] && { echo "$SALIDA"; echo "No se pudo hacer fetch."; exit 1; }
DESPUES=$(git rev-parse "origin/$RAMA")
if [ -n "$ANTES" ] && [ "$ANTES" != "$DESPUES" ] && ! git merge-base --is-ancestor "$ANTES" "$DESPUES"; then
  printf '\033[41;97m  ALERTA: origin/%s fue REESCRITA (force push): %s ya no esta en su historia.  \033[0m\n' "$RAMA" "${ANTES:0:7}"
  printf '\033[31mSi no fuiste vos, es el atacante. No mezcles. Avisale a Claude.\033[0m\n'; exit 1
fi
if [ "$(git rev-parse HEAD)" = "$DESPUES" ]; then echo "   Ya estas al dia (${DESPUES:0:7})."; exit 0; fi
echo "2) Revisando los commits nuevos (${ANTES:0:7}..${DESPUES:0:7})..."
FAIL=0
verificar_commits "$(git rev-parse HEAD)" "$DESPUES" || FAIL=1
echo "3) Revisando el arbol remoto sin hacer checkout..."
verificar_arbol "$DESPUES" || FAIL=1
if [ $FAIL -ne 0 ]; then
  printf '\n\033[31mNO SE MEZCLO NADA: lo que hay en origin/%s tiene señales del atacante. Tu arbol sigue como estaba.\033[0m\n' "$RAMA"; exit 1
fi
echo "4) Limpio. Mezclando..."
if git merge --ff-only "origin/$RAMA"; then :; else
  echo "   Tenes commits locales: aplicando rebase sobre origin/$RAMA"
  git rebase "origin/$RAMA" || { echo "Rebase con conflictos: resolvelos y corre 'git rebase --continue'."; exit 1; }
fi
echo "5) Chequeo final del arbol de trabajo..."
bash scripts/security-check.sh "$ROOT" || { printf '\033[31mEl arbol quedo con problemas: git reset --hard ORIG_HEAD y avisale a Claude.\033[0m\n'; exit 1; }
printf '\033[32mActualizado a %s y verificado.\033[0m\n' "$(git rev-parse --short HEAD)"
