#!/usr/bin/env bash
# Verifica un repo en GitHub ANTES de clonarlo, sin bajar ni ejecutar nada.
# Uso: bash scripts/verificar-remoto.sh juanverna/swap-crm-clean [rama]
# Requiere: gh (logueado), python3.
set -u
REPO="${1:?uso: verificar-remoto.sh owner/repo [rama]}"
RAMA="${2:-}"
PROBLEMAS=0
rojo(){ printf '  \033[31m✗ %s\033[0m\n' "$*"; PROBLEMAS=$((PROBLEMAS+1)); }
ok(){ printf '  \033[32m✓ %s\033[0m\n' "$*"; }
info(){ printf '  · %s\n' "$*"; }

[ -z "$RAMA" ] && RAMA=$(gh api "repos/$REPO" --jq .default_branch 2>/dev/null)
HEAD=$(gh api "repos/$REPO/branches/$RAMA" --jq .commit.sha 2>/dev/null) || { echo "No pude leer $REPO rama $RAMA"; exit 2; }
echo "Repo $REPO, rama $RAMA, HEAD ${HEAD:0:7}"

echo "1) Force pushes recientes"
FP=$(gh api "repos/$REPO/activity?per_page=50" --jq '.[] | select(.activity_type=="force_push") | "\(.timestamp) \(.actor.login) \(.ref|sub("refs/heads/";"")) \(.before[0:7])->\(.after[0:7])"')
if [ -z "$FP" ]; then ok "ningún force push en los últimos 50 eventos"; else
  echo "$FP" | while read -r l; do info "$l"; done
  ULTIMO=$(echo "$FP" | head -1 | cut -d' ' -f1)
  if [[ "$ULTIMO" > "2026-09-17T04:00:00Z" ]]; then rojo "hay un force push NUEVO ($ULTIMO) posterior a la restauración del 17-sep: si no lo hiciste vos, es el atacante"; else ok "el último force push es de la restauración del 17-sep o anterior (ya revisados)"; fi; fi

echo "2) Últimos 15 commits: autor vs committer"
gh api "repos/$REPO/commits?sha=$RAMA&per_page=15" --jq '.[] | "\(.sha[0:7])|\(.commit.author.name)|\(.commit.author.date)|\(.commit.committer.name)|\(.commit.committer.date)|\(.commit.message|split("\n")[0][0:50])"' | HEAD7="${HEAD:0:7}" python3 -c '
import sys,os
bad=0; head=os.environ["HEAD7"]
for l in sys.stdin:
    sha,an,ad,cn,cd,msg=l.rstrip("\n").split("|",5)
    flags=[]
    if cn.strip()=="Juan": flags.append("committer \"Juan\" (firma del atacante)")
    if an!=cn and cn not in ("GitHub","github-actions[bot]","Juan Verna","Juan Vergniaud","juanverna"): flags.append(f"committer distinto al autor ({cn})")
    if ad[:10]!=cd[:10]: flags.append(f"fecha de committer {cd[:10]} distinta a la de autor {ad[:10]}")
    if "�" in msg or "├" in msg or "Ã" in msg: flags.append("acentos rotos en el mensaje (consola Windows)")
    if flags and sha==head:
        bad+=1; print(f"  \033[31m✗ {sha} (ES EL HEAD) {msg}: "+"; ".join(flags)+"\033[0m")
    elif flags:
        print(f"  \033[33m! {sha} (en el historial, no es el HEAD) {msg}: "+"; ".join(flags)+". El árbol actual se valida en 3 y 4.\033[0m")
    else: print(f"  · {sha} {an} {ad[:10]} {msg}")
sys.exit(1 if bad else 0)' || PROBLEMAS=$((PROBLEMAS+1))

TREE=$(gh api "repos/$REPO/git/trees/$HEAD?recursive=1")
echo "3) Archivos de config: línea más larga (el cargador es UNA línea de 7.000 a 32.000 caracteres)"
echo "$TREE" | python3 -c '
import sys,json,re
t=json.load(sys.stdin)
if t.get("truncated"): print("  · aviso: árbol truncado, revisión parcial")
pat=re.compile(r"(^|/)(postcss|vite|vitest|tailwind|next|webpack|babel|jest|eslint|drizzle|tsx|rollup|esbuild|svelte|nuxt|astro|remix|playwright|cypress|prettier|commitlint|lint-staged)[\w.-]*\.(config\.)?(js|cjs|mjs|ts|mts|cts|json)$|(^|/)\.(eslintrc|babelrc|prettierrc)[\w.]*$|(^|/)\.vscode/tasks\.json$|(^|/)Dockerfile[\w.-]*$|(^|/)(requirements[\w.-]*\.(txt|in)|pyproject\.toml|setup\.(py|cfg)|conftest\.py|tox\.ini|pytest\.ini|pip\.conf|__init__\.py|[\w.-]*\.code-workspace|[\w.-]*\.ya?ml)$|(^|/)\.vscode/[\w.-]+\.json$|(^|/)\.github/workflows/[^/]+$")
for b in t["tree"]:
    if b["type"]=="blob" and "node_modules" not in b["path"] and pat.search(b["path"]):
        print(b["sha"]+" "+b["path"])' > /tmp/verificar-remoto-cfg.$$
NCFG=$(wc -l < /tmp/verificar-remoto-cfg.$$ | tr -d ' ')
BADCFG=0
while read -r sha path; do
  [ -z "$sha" ] && continue
  MAXL=$(gh api "repos/$REPO/git/blobs/$sha" --jq .content 2>/dev/null | base64 -d 2>/dev/null | awk '{ if (length($0)>m) m=length($0) } END {print m+0}')
  if [ "$MAXL" -gt 500 ]; then BADCFG=$((BADCFG+1)); rojo "$path tiene una línea de $MAXL caracteres"; fi
done < /tmp/verificar-remoto-cfg.$$
rm -f /tmp/verificar-remoto-cfg.$$
if [ "$BADCFG" = "0" ]; then ok "los $NCFG archivos de config tienen líneas normales"; else PROBLEMAS=$((PROBLEMAS+1)); fi

echo "4) Fuentes e imágenes que en realidad son texto (payload disfrazado)"
echo "$TREE" | python3 -c '
import sys,json
t=json.load(sys.stdin)
for b in t["tree"]:
    if b["type"]=="blob" and "node_modules" not in b["path"] and b["path"].lower().endswith((".woff",".woff2",".ttf",".otf",".eot",".png",".jpg",".jpeg",".gif",".ico",".webp")):
        print(b["sha"]+" "+b["path"])' > /tmp/verificar-remoto-bin.$$ 
NBIN=$(wc -l < /tmp/verificar-remoto-bin.$$ | tr -d ' ')
if [ "$NBIN" = "0" ]; then ok "no hay fuentes ni imágenes en el repo"; else
  BAD=0
  while read -r sha path; do
    head8=$(gh api "repos/$REPO/git/blobs/$sha" --jq .content 2>/dev/null | base64 -d 2>/dev/null | head -c 8 | xxd -p)
    case "$head8" in
      774f4646*|774f4632*|00010000*|4f54544f*|89504e47*|ffd8ff*|47494638*|52494646*|00000100*|0000020*) ;;   # wOFF wOF2 ttf OTTO PNG JPG GIF RIFF ICO
      *) BAD=$((BAD+1)); rojo "$path no tiene cabecera de su formato (empieza con $head8)";;
    esac
  done < /tmp/verificar-remoto-bin.$$
  [ "$BAD" = "0" ] && ok "las $NBIN fuentes/imágenes tienen cabecera correcta"
fi
rm -f /tmp/verificar-remoto-bin.$$

echo "5) Chequeo automático (GitHub Actions) del HEAD"
RUN=$(gh run list --repo "$REPO" --commit "$HEAD" --limit 1 --json name,conclusion,status --jq '.[0] | "\(.name): \(.status) \(.conclusion)"' 2>/dev/null)
if [ -z "$RUN" ] || [ "$RUN" = ": " ] || echo "$RUN" | grep -q "^null"; then info "este repo no tiene chequeo automático (solo swap-crm-clean lo tiene)"; elif echo "$RUN" | grep -q success; then ok "$RUN"; else rojo "$RUN"; fi

echo
if [ "$PROBLEMAS" = "0" ]; then
  printf '\033[32mVEREDICTO: sin señales del atacante. Podés clonar %s y, antes de instalar o correr nada, ejecutar scripts/security-check.sh.\033[0m\n' "${HEAD:0:7}"
else
  printf '\033[31mVEREDICTO: %s problema(s). NO clones ni corras nada: mandame esta salida.\033[0m\n' "$PROBLEMAS"; exit 1
fi
