#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Sauvegarde logique de la base SEOnaut (mariadb-dump compressé), indépendante de l'architecture
# et de la version : c'est ce fichier qu'on emporte pour migrer vers une autre machine.
# SEOnaut doit être démarré (./demarrer.sh).
# Usage : ./sauvegarder.sh   → sauvegardes/seonaut_AAAA-MM-JJ_HHMM.sql.gz
. "$(dirname "$(readlink -f "$0")")/lib.sh"
exiger_env
db_en_marche || echec "la base ne tourne pas : lancer d'abord ./demarrer.sh"
mkdir -p sauvegardes && chmod 700 sauvegardes
fichier="sauvegardes/seonaut_$(date +%F_%H%M).sql.gz"
umask 077
docker compose exec -T db sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb-dump -uroot \
  --single-transaction --quick --routines --triggers --databases seonaut' | gzip > "$fichier"
codes=("${PIPESTATUS[@]}")
if [ "${codes[0]}" -ne 0 ] || [ "${codes[1]}" -ne 0 ] || ! gzip -t "$fichier"; then
  rm -f "$fichier"
  echec "sauvegarde en échec"
fi
echo "Sauvegarde : $SEONAUT_DIR/$fichier ($(du -h "$fichier" | cut -f1))"
