#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Crée .env (droits 600) à partir de .env.exemple, avec des mots de passe aléatoires.
# Ne touche jamais à un .env existant.
# Usage : ./initialiser.sh [--sans-garde-fous]
#   --sans-garde-fous  COMPOSE_FILE=compose.yaml (machine confortable : poste, futur serveur)
. "$(dirname "$(readlink -f "$0")")/lib.sh"
[ -f .env ] && { echo ".env existe déjà : rien à faire."; exit 0; }
command -v openssl > /dev/null || echec "openssl introuvable"
umask 077
sed -e "s/^SEONAUT_DB_ROOT_PASSWORD=.*/SEONAUT_DB_ROOT_PASSWORD=$(openssl rand -hex 24)/" \
    -e "s/^SEONAUT_DB_PASSWORD=.*/SEONAUT_DB_PASSWORD=$(openssl rand -hex 24)/" .env.exemple > .env
[ "${1:-}" = --sans-garde-fous ] && sed -i 's/^COMPOSE_FILE=.*/COMPOSE_FILE=compose.yaml/' .env
echo ".env créé (droits 600) ; $(grep '^COMPOSE_FILE=' .env)"
