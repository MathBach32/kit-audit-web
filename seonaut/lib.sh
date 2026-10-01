#!/usr/bin/env bash
# Fonctions communes aux scripts de SEOnaut exécutés sur la machine hôte (Pi ou autre).
# S'utilise par : . "$(dirname "$(readlink -f "$0")")/lib.sh"
set -uo pipefail
SEONAUT_DIR="$(cd "$(dirname "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)"
cd "$SEONAUT_DIR"
PROJET=seonaut

echec() { echo "ERREUR : $*" >&2; exit 1; }

# charger_env : lit .env sans l'exécuter (variables simples NOM=valeur).
charger_env() {
  [ -f .env ] || return 1
  while IFS='=' read -r cle valeur; do
    [[ "$cle" =~ ^[A-Z_][A-Z0-9_]*$ ]] || continue
    printf -v "$cle" '%s' "$valeur"
    export "${cle?}"
  done < .env
  SEUIL_DEMARRAGE_MO="${SEUIL_DEMARRAGE_MO:-350}"
  SEUIL_ALERTE_MO="${SEUIL_ALERTE_MO:-100}"
}

garde_fous_actifs() { [[ "${COMPOSE_FILE:-}" == *garde-fous* ]]; }

memoire_dispo_mo() { awk '/^MemAvailable:/ {print int($2 / 1024)}' /proc/meminfo; }

# conteneurs_autres : conteneurs en marche qui n'appartiennent pas à SEOnaut (nom et état).
conteneurs_autres() {
  docker ps --format '{{.Names}}|{{.Label "com.docker.compose.project"}}|{{.Status}}' \
    | awk -F'|' -v p="$PROJET" '$2 != p {print $1 " : " $3}' | sort
}

afficher_etat() {
  awk '/^MemTotal:/ {t=$2} /^MemAvailable:/ {a=$2} /^SwapTotal:/ {st=$2} /^SwapFree:/ {sf=$2}
       END {printf "Mémoire : %d Mo disponibles sur %d Mo ; swap utilisé : %d Mo sur %d Mo\n", a/1024, t/1024, (st-sf)/1024, st/1024}' /proc/meminfo
  docker stats --no-stream --format 'table {{.Name}}\t{{.MemUsage}}\t{{.CPUPerc}}'
  echo
  docker ps --format 'table {{.Names}}\t{{.Status}}'
}

exiger_env() {
  charger_env || echec ".env absent : lancer d'abord ./initialiser.sh"
  [ -n "${SEONAUT_DB_PASSWORD:-}" ] && [ -n "${SEONAUT_DB_ROOT_PASSWORD:-}" ] || echec "mots de passe vides dans .env"
}

db_en_marche() { [ -n "$(docker compose ps --status running -q db 2> /dev/null)" ]; }
