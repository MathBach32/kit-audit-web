#!/usr/bin/env bash
# Arrête SEOnaut et supprime ses conteneurs. Les données (volumes seonaut_db et
# seonaut_archives) sont conservées.
# Usage : ./arreter.sh
. "$(dirname "$(readlink -f "$0")")/lib.sh"
exiger_env
docker compose down
echo; afficher_etat
