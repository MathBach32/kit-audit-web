#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Restaure une sauvegarde de sauvegarder.sh : la base seonaut est REMPLACÉE par son contenu.
# SEOnaut doit être démarré (./demarrer.sh) ; l'application est redémarrée ensuite.
# Usage : ./restaurer.sh sauvegardes/seonaut_AAAA-MM-JJ_HHMM.sql.gz [--oui]
#   --oui  ne pas demander de confirmation
. "$(dirname "$(readlink -f "$0")")/lib.sh"
fichier="${1:-}"
[ -f "$fichier" ] || echec "usage : ./restaurer.sh FICHIER.sql.gz [--oui]"
exiger_env
gzip -t "$fichier" || echec "$fichier n'est pas une archive gzip valide"
db_en_marche || echec "la base ne tourne pas : lancer d'abord ./demarrer.sh"
if [ "${2:-}" != --oui ]; then
  read -r -p "La base seonaut actuelle sera remplacée par $fichier. Continuer ? [o/N] " reponse
  [[ "$reponse" =~ ^[oO]$ ]] || { echo "Abandon."; exit 1; }
fi
gunzip -c "$fichier" | docker compose exec -T db sh -c 'MYSQL_PWD="$MARIADB_ROOT_PASSWORD" exec mariadb -uroot'
[ "${PIPESTATUS[1]}" -eq 0 ] || echec "restauration en échec"
docker compose restart app
echo "Base restaurée depuis $fichier"
