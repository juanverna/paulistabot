#!/usr/bin/env bash
# Funciones compartidas por los hooks y por actualizar.sh / desplegar.sh.
# Verifican commits y arboles de git SIN hacer checkout ni ejecutar nada.
# Se carga con: source "$(git rev-parse --show-toplevel)/scripts/lib-verificar-git.sh"

# Archivos de configuracion que las herramientas cargan solas (ahi se esconde el cargador).
CFG_RE='(^|/)(postcss|vite|vitest|tailwind|next|webpack|babel|jest|eslint|drizzle|tsx|rollup|esbuild|svelte|nuxt|astro|remix|playwright|cypress|prettier|commitlint|lint-staged|tsconfig)[A-Za-z0-9._-]*\.(config\.)?(js|cjs|mjs|ts|mts|cts|json)$|(^|/)\.(eslintrc|babelrc|prettierrc)[A-Za-z0-9._]*$|(^|/)\.vscode/(tasks|settings|launch)\.json$|(^|/)Dockerfile[A-Za-z0-9._-]*$|(^|/)package\.json$|(^|/)\.npmrc$'
# Python (paulistabot, copiado de swap-ig-generator): lo que cargan pip, pytest, VS Code, GitHub, el import del paquete y el programa.
CFG_RE="$CFG_RE"'|(^|/)(requirements[A-Za-z0-9._-]*\.(txt|in)|pyproject\.toml|setup\.(py|cfg)|conftest\.py|tox\.ini|pytest\.ini|pip\.conf|__init__\.py|[A-Za-z0-9._-]*\.code-workspace|[A-Za-z0-9._-]*\.ya?ml)$|(^|/)\.github/workflows/[^/]+$'
# Codigo Python que ejecuta o importa dinamicamente (mismo criterio que la seccion 3b de security-check.sh).
PY_LOADER_RE="(^|[^.[:alnum:]_])(exec|eval|compile|__import__)[[:space:]]*\(|importlib|subprocess|os\.(system|popen|spawn|exec)|pty\.spawn|marshal\.|b64decode\([[:space:]]*b?['\"]|codecs\.decode\("
# Archivos que Python/pytest importan solos: su codigo a nivel modulo se ejecuta sin que nadie lo llame.
PY_MODULO_RE='(^|/)(__init__|conftest)\.py$'
# Mismo criterio que la seccion 3c de security-check.sh: a nivel modulo solo docstrings, comentarios,
# imports, def/class, decoradores de una lista corta y asignaciones SIN llamadas. Imprime lo que no cumple.
IFS= read -r -d '' PY_MODULO_AWK <<'AWK' || true
    { l = $0; nq = gsub(/"""|'''/, "&", l) }
    doc { if (nq % 2 == 1) doc = 0; next }
    /^[[:space:]]/ || /^$/ || /^#/ { next }
    /^("""|''')/ { if (nq % 2 == 1) doc = 1; next }
    /^(import|from|def|class|async def)[[:space:]]/ || /^[)\]}]/ { next }
    /^@(pytest\.fixture|dataclass|dataclasses\.dataclass|property|staticmethod|classmethod|functools\.[A-Za-z_]+)[[:space:]]*(\(([[:space:]]*[A-Za-z_]+[[:space:]]*=[[:space:]]*(True|False|None|[0-9]+|"[A-Za-z0-9_-]*"|'[A-Za-z0-9_-]*')[[:space:]]*,?)*\))?[[:space:]]*(#.*)?$/ { next }
    /^[A-Za-z_][A-Za-z0-9_]*[[:space:]]*(:[^=]*)?=[^=(]*$/ { next }
    { printf "%s:%d: %s\n", f, FNR, $0 }
AWK
# Heroku: lo que ejecutan el dyno (Procfile) y el buildpack (bin/*_compile, heroku.yml) en cada deploy.
CFG_RE="$CFG_RE"'|(^|/)(Procfile|runtime\.txt|\.python-version|Aptfile|app\.json)$'
HEROKU_PROHIBIDO_RE='^(bin/(pre_compile|post_compile|compile)|heroku\.yml)$'
BIN_RE='\.(woff2?|ttf|otf|eot|png|jpe?g|gif|ico|webp)$'
MAX_LINEA=500

# verificar_commits <desde> <hasta>: cada commit del rango debe tener el committer del usuario.
# Devuelve 1 si hay commits con firma ajena.
#
# Identidad vieja del dueño: los commits de paulistabot hasta 2026 tienen committer
# "juanverna <tu email>". Esa identidad (nombre Y email exactos) se acepta SOLO en el chequeo de
# identidad. El commit del atacante (5bf5487) usaba exactamente ese committer, asi que todos los
# demas chequeos (acentos rotos, fecha de committer distinta a la de autor, zona -0800) se le siguen
# aplicando igual. Lo demuestra scripts/test-verificar-git.sh.
NOMBRE_VIEJO="juanverna"
verificar_commits() {
  local desde="$1" hasta="$2" rango bad=0
  if [ -z "$desde" ] || [ "$desde" = "0000000000000000000000000000000000000000" ] || ! git cat-file -e "$desde" 2>/dev/null; then
    rango="$hasta --max-count=50"
  else
    rango="$desde..$hasta"
  fi
  local yo_nombre yo_email
  yo_nombre=$(git config user.name); yo_email=$(git config user.email)
  while IFS='|' read -r sha an ae ad cn ce cd msg; do
    [ -z "$sha" ] && continue
    local motivo=""
    [ "$cn" = "Juan" ] && motivo="$motivo committer \"Juan\" (firma del atacante);"
    local identidad_vieja=0
    [ "$cn" = "$NOMBRE_VIEJO" ] && [ -n "$yo_email" ] && [ "$ce" = "$yo_email" ] && identidad_vieja=1
    [ "$cn" != "$yo_nombre" ] && [ "$identidad_vieja" = 0 ] && [ "$cn" != "GitHub" ] && [ "$cn" != "github-actions[bot]" ] && motivo="$motivo committer \"$cn\" no es \"$yo_nombre\";"
    [ -n "$yo_email" ] && [ "$ce" != "$yo_email" ] && [ "$cn" != "GitHub" ] && motivo="$motivo email de committer $ce no es el tuyo;"
    [ "${ad:0:10}" != "${cd:0:10}" ] && motivo="$motivo fecha de committer (${cd:0:10}) distinta a la de autor (${ad:0:10});"
    case "$ad $cd" in *-08:00*) motivo="$motivo zona horaria -0800 (firma del atacante);";; esac
    case "$msg" in *"├"*|*"Ã"*|*$'\xef\xbf\xbd'*) motivo="$motivo acentos rotos en el mensaje (consola Windows);";; esac
    if [ -n "$motivo" ]; then
      bad=1; printf '  \033[31m✗ %s %s\n      %s\033[0m\n' "${sha:0:7}" "$msg" "$motivo"
    fi
  done < <(git log --format='%H|%an|%ae|%aI|%cn|%ce|%cI|%s' $rango 2>/dev/null)
  return $bad
}

# verificar_arbol <commit>: configs con lineas gigantes y binarios que son texto, leyendo del objeto git.
verificar_arbol() {
  local commit="$1" bad=0 path sha mode tipo
  while read -r mode tipo sha path; do
    [ "$tipo" != "blob" ] && continue
    case "$path" in node_modules/*|*/node_modules/*|dist/*|.git/*) continue;; esac
    if printf '%s' "$path" | grep -qE "$HEROKU_PROHIBIDO_RE"; then
      bad=1; printf '  \033[31m✗ %s existe: Heroku lo ejecuta solo en cada build\033[0m\n' "$path"
    fi
    if [ "$path" = "Procfile" ] && [ "$(git cat-file -p "$sha")" != "worker: python main.py" ]; then
      bad=1; printf '  \033[31m✗ Procfile distinto del conocido (worker: python main.py)\033[0m\n'
    fi
    case "$path" in *.py)
      if git cat-file -p "$sha" | grep -qE "$PY_LOADER_RE"; then
        bad=1; printf '  \033[31m✗ %s ejecuta o importa codigo dinamicamente (exec, eval, subprocess, importlib...)\033[0m\n' "$path"
      fi
      if printf '%s' "$path" | grep -qE "$PY_MODULO_RE"; then
        local modulo
        modulo=$(git cat-file -p "$sha" | awk -v f="$path" "$PY_MODULO_AWK")
        if [ -n "$modulo" ]; then
          bad=1; printf '  \033[31m✗ %s ejecuta codigo a nivel modulo (corre solo al importarse):\033[0m\n' "$path"
          printf '%s\n' "$modulo" | cut -c1-200 | sed 's/^/      /'
        fi
      fi;;
    esac
    if printf '%s' "$path" | grep -qE "$CFG_RE"; then
      local maxl
      maxl=$(git cat-file -p "$sha" | awk '{ if (length($0)>m) m=length($0) } END {print m+0}')
      if [ "$maxl" -gt "$MAX_LINEA" ]; then bad=1; printf '  \033[31m✗ %s tiene una linea de %s caracteres\033[0m\n' "$path" "$maxl"; fi
      if git cat-file -p "$sha" | grep -qE "global\[['\"][rm]['\"]\] *=|\"runOn\" *: *\"folderOpen\"|createRequire\(|child_process|eval\("; then
        case "$path" in *package.json|*tsconfig*) ;; *) bad=1; printf '  \033[31m✗ %s contiene patron de cargador (require global, eval, child_process o tarea folderOpen)\033[0m\n' "$path";; esac
      fi
    elif printf '%s' "$path" | grep -qiE "$BIN_RE"; then
      local head8
      head8=$(git cat-file -p "$sha" | head -c 8 | xxd -p)
      case "$head8" in
        774f4646*|774f4632*|00010000*|4f54544f*|89504e47*|ffd8ff*|47494638*|52494646*|00000100*|0000020*|3c737667*|3c3f786d*) ;;
        *) bad=1; printf '  \033[31m✗ %s no tiene cabecera de fuente/imagen (empieza con %s): payload disfrazado\033[0m\n' "$path" "$head8";;
      esac
    fi
  done < <(git ls-tree -r "$commit" 2>/dev/null)
  return $bad
}
