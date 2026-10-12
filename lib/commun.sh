#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Fonctions communes aux commandes de bin/ : arguments, dossier de résultats, listes de pages, secrets.
# S'utilise par : . "$(dirname "$(readlink -f "$0")")/../lib/commun.sh"
#
# Variables d'environnement reconnues :
#   KIT_AUDIT_RESULTATS  racine des résultats (défaut : <kit>/resultats)
#   KIT_AUDIT_DOSSIER    dossier d'audit imposé (sinon <résultats>/<domaine>/<AAAA-MM-JJ>)
#   KIT_AUDIT_SECRETS    fichier des secrets (défaut : ~/.config/audit-kit/secrets.env)
#   CHROME_PATH          navigateur imposé (défaut : Google Chrome ou Chromium détecté par lib/kit.py)
#   KIT_NAVIGATEUR_LIBRE 1 : CHROME_PATH accepté sans contrôle de version (Brave, Microsoft Edge…)

set -uo pipefail

KIT_RACINE="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")/.." && pwd)"
export KIT_RACINE
export PATH="$KIT_RACINE/node_modules/.bin:$KIT_RACINE/.venv/bin:$HOME/.local/bin:$PATH"
export PUPPETEER_SKIP_DOWNLOAD=1
# Chrome crée un socket Unix dans TMPDIR : au-delà d'environ 60 caractères, le chemin dépasse la
# limite du système (108) et Chrome s'arrête aussitôt (SIGABRT). On se rabat alors sur /tmp.
[ -z "${TMPDIR:-}" ] || [ "${#TMPDIR}" -le 60 ] || export TMPDIR=/tmp
export KIT_UA="${KIT_UA:-Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/154.0 Safari/537.36 kit-audit-web}"
export PYTHONPATH="$KIT_RACINE/lib${PYTHONPATH:+:$PYTHONPATH}"
PYTHON="$KIT_RACINE/.venv/bin/python"
[ -x "$PYTHON" ] || PYTHON=python3
# Navigateur : CHROME_PATH s'il est défini et accepté (chemin absolu), sinon Google Chrome ou Chromium
# détecté. KIT_NAVIGATEUR vide si aucun : CHROME_PATH garde alors sa valeur d'origine, que le message
# d'erreur cite, et exiger_navigateur arrête les commandes qui ont besoin d'un navigateur.
KIT_NAVIGATEUR="$("$PYTHON" -m kit navigateur 2> /dev/null)"
if [ -n "$KIT_NAVIGATEUR" ]; then export CHROME_PATH="$KIT_NAVIGATEUR" PUPPETEER_EXECUTABLE_PATH="${PUPPETEER_EXECUTABLE_PATH:-$KIT_NAVIGATEUR}"; fi

declare -A OPTS=()

journal() { printf '[%s] %s\n' "$(date +%H:%M:%S)" "$*" >&2; }
echec() { journal "ERREUR : $*"; exit 1; }

# Affiche le bloc de commentaires d'en-tête du script appelant (mode d'emploi), sans les
# mentions de droit d'auteur et de licence.
aide() { awk 'NR == 1 { next } !/^#/ { exit } /^# (SPDX-|Sous licence EUPL)/ { next } { sub(/^# ?/, ""); if (!vu && $0 == "") next; vu = 1; print }' "$0"; }

# lire_arguments "$@" : remplit URL_ARG et le tableau OPTS.
# Le script appelant déclare avant l'appel OPTIONS (options suivies d'une valeur)
# et DRAPEAUX (options sans valeur). --dossier est commun à toutes les commandes.
lire_arguments() {
  URL_ARG=""
  while [ $# -gt 0 ]; do
    case "$1" in
      -h|--help) aide; exit 0 ;;
      --*=*) _option "${1%%=*}" "${1#*=}"; shift ;;
      --*)
        if [[ " ${DRAPEAUX:-} " == *" $1 "* ]]; then OPTS[$1]=1; shift
        else [ $# -ge 2 ] || echec "valeur manquante pour $1"; _option "$1" "$2"; shift 2; fi ;;
      *) [ -z "$URL_ARG" ] || echec "argument inattendu : $1"; URL_ARG="$1"; shift ;;
    esac
  done
  [ -n "$URL_ARG" ] || { aide >&2; exit 2; }
  [ -n "${OPTS[--dossier]:-}" ] && export KIT_AUDIT_DOSSIER="$(readlink -m "${OPTS[--dossier]}")"
  [ -n "${OPTS[--pages]:-}" ] && { OPTS[--pages]="$(readlink -f "${OPTS[--pages]}")"; [ -s "${OPTS[--pages]}" ] || echec "liste de pages vide ou absente"; }
  return 0
}
_option() {
  [[ " --dossier ${OPTIONS:-} " == *" $1 "* ]] || echec "option inconnue : $1 (voir --help)"
  OPTS[$1]="$2"
}

# definir_dossier : définit SITE_URL, SITE_DOMAINE et DOSSIER_AUDIT à partir de URL_ARG.
definir_dossier() {
  SITE_URL="$("$PYTHON" -m kit url "$URL_ARG")" || echec "URL invalide : $URL_ARG"
  SITE_DOMAINE="$("$PYTHON" -m kit domaine "$SITE_URL")"
  DOSSIER_AUDIT="${KIT_AUDIT_DOSSIER:-${KIT_AUDIT_RESULTATS:-$KIT_RACINE/resultats}/$SITE_DOMAINE/$(date +%F)}"
  mkdir -p "$DOSSIER_AUDIT"
  export SITE_URL SITE_DOMAINE DOSSIER_AUDIT
}

# verrouiller_dossier : un seul bin/tout ou bin/synthese à la fois par dossier d'audit (ligne de
# commande ou interface graphique). Verrou flock sur <dossier>/.verrou, tenu par le descripteur 9
# jusqu'à la fin du script ; bin/tout le ferme pour les commandes qu'il lance (9>&-), et
# KIT_AUDIT_VERROU dit à bin/synthese que son parent le tient déjà.
verrouiller_dossier() {
  [ "${KIT_AUDIT_VERROU:-}" = "$DOSSIER_AUDIT" ] && return 0
  command -v flock > /dev/null || { journal "attention : flock introuvable, dossier d'audit non verrouillé"; return 0; }
  exec 9> "$DOSSIER_AUDIT/.verrou"
  flock -w 3 9 || echec "un audit est déjà en cours dans $DOSSIER_AUDIT : attendre sa fin"
  export KIT_AUDIT_VERROU="$DOSSIER_AUDIT"
}

# preparer_sortie OUTIL : definir_dossier, puis SORTIE=<dossier d'audit>/OUTIL (vidé s'il existait).
preparer_sortie() {
  local outil="$1"
  [[ -n "$outil" && "$outil" != */* ]] || echec "nom d'outil invalide"
  definir_dossier
  SORTIE="$DOSSIER_AUDIT/$outil"
  [ -d "$SORTIE" ] && rm -rf -- "${SORTIE:?}"
  mkdir -p "$SORTIE"
  [ -s "$DOSSIER_AUDIT/site.txt" ] || echo "$SITE_URL" > "$DOSSIER_AUDIT/site.txt"
  export SITE_URL SITE_DOMAINE DOSSIER_AUDIT SORTIE
  journal "$outil : $SITE_URL → $SORTIE"
}

# urls_sitemap : chemin du fichier (mis en cache dans le dossier d'audit) des pages du sitemap.
urls_sitemap() {
  local f="$DOSSIER_AUDIT/urls_sitemap.txt"
  [ -s "$f" ] || "$PYTHON" -m sitemap pages "$SITE_URL" > "$f" 2>/dev/null || true
  echo "$f"
}

# pages_a_auditer : écrit $SORTIE/pages.txt et renvoie son chemin. Par ordre de préférence :
# --pages, pages HTML trouvées par bin/seo (liens et sitemap, l'accueil d'abord), la liste
# urls_html_advertools.txt des dossiers produits par une version antérieure du kit, le sitemap,
# sinon l'accueil. --max N limite le nombre de pages (les moins profondes d'abord).
pages_a_auditer() {
  local f source=""
  for f in "${OPTS[--pages]:-}" "$DOSSIER_AUDIT/urls_html.txt" "$DOSSIER_AUDIT/urls_html_advertools.txt" "$(urls_sitemap)"; do
    if [ -n "$f" ] && [ -s "$f" ]; then source="$f"; break; fi
  done
  if [ -n "$source" ]; then
    grep -v '^\s*\(#\|$\)' "$source" | head -n "${OPTS[--max]:-100000}" > "$SORTIE/pages.txt"
  else
    echo "$SITE_URL" > "$SORTIE/pages.txt"
  fi
  journal "$(wc -l < "$SORTIE/pages.txt") page(s) à auditer (source : ${source:-accueil seule})"
  echo "$SORTIE/pages.txt"
}

# pages_types [N] : écrit $SORTIE/pages.txt avec N pages représentatives (défaut 6) et renvoie son chemin.
pages_types() {
  if [ -n "${OPTS[--pages]:-}" ]; then
    grep -v '^\s*\(#\|$\)' "${OPTS[--pages]}" > "$SORTIE/pages.txt"
  else
    local liste; liste="$(urls_sitemap)"
    if [ -s "$liste" ]; then
      "$PYTHON" -m sitemap types "$SITE_URL" "${1:-6}" "$liste" > "$SORTIE/pages.txt"
    else
      echo "$SITE_URL" > "$SORTIE/pages.txt"
    fi
  fi
  echo "$SORTIE/pages.txt"
}

slug() { "$PYTHON" -m kit slug "$1"; }

# charger_cle_psi : lit PSI_API_KEY dans le fichier des secrets (sans l'exécuter ni l'exporter).
charger_cle_psi() {
  [ -n "${PSI_API_KEY:-}" ] && return 0
  local f="${KIT_AUDIT_SECRETS:-$HOME/.config/audit-kit/secrets.env}"
  [ -r "$f" ] || return 1
  [ "$(stat -c %a "$f")" = 600 ] || journal "attention : $f devrait avoir les droits 600 (chmod 600)"
  PSI_API_KEY="$(sed -n 's/^[[:space:]]*\(export[[:space:]]\{1,\}\)\{0,1\}PSI_API_KEY=//p' "$f" | tail -n 1 | tr -d "\"'[:space:]")"
  [ -n "$PSI_API_KEY" ]
}

# exiger COMMANDE [conseil] : arrête le script si la commande est introuvable.
exiger() { command -v "$1" > /dev/null || echec "$1 introuvable. ${2:-Lancer ./installer.sh}"; }
# exiger_navigateur : arrête le script si aucun navigateur (Google Chrome ou Chromium) n'est utilisable.
exiger_navigateur() { [ -n "$KIT_NAVIGATEUR" ] || echec "$("$PYTHON" -m kit navigateur 2>&1 > /dev/null)"; }
