#!/usr/bin/env bash
# Affiche la mémoire, les conteneurs, les garde-fous en vigueur et la taille des volumes de SEOnaut.
# Usage : ./etat.sh
. "$(dirname "$(readlink -f "$0")")/lib.sh"
charger_env || echo "(.env absent : lancer ./initialiser.sh)"
echo "Garde-fous : $(garde_fous_actifs && echo actifs || echo levés) (COMPOSE_FILE=${COMPOSE_FILE:-compose.yaml})"
afficher_etat
echo
docker system df -v 2> /dev/null | awk '/^seonaut_(db|archives) / {print "Volume " $1 " : " $NF}'
