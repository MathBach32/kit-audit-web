#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Affiche la mémoire, les conteneurs, les garde-fous en vigueur et la taille des volumes de SEOnaut.
# Usage : ./etat.sh
. "$(dirname "$(readlink -f "$0")")/lib.sh"
charger_env || echo "(.env absent : lancer ./initialiser.sh)"
echo "Garde-fous : $(garde_fous_actifs && echo actifs || echo levés) (COMPOSE_FILE=${COMPOSE_FILE:-compose.yaml})"
afficher_etat
echo
docker system df -v 2> /dev/null | awk '/^seonaut_(db|archives) / {print "Volume " $1 " : " $NF}'
