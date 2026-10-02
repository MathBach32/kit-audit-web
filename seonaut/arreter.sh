#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Arrête SEOnaut et supprime ses conteneurs. Les données (volumes seonaut_db et
# seonaut_archives) sont conservées.
# Usage : ./arreter.sh
. "$(dirname "$(readlink -f "$0")")/lib.sh"
exiger_env
docker compose down
echo; afficher_etat
