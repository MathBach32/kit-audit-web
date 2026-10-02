#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Depuis le poste : lance un script de SEOnaut sur l'hôte cible, par SSH.
# Usage : seonaut/distant.sh demarrer|arreter|etat|sauvegarder|initialiser [arguments]
#         seonaut/distant.sh tunnel        (ouvre le tunnel vers l'interface, Ctrl+C pour fermer)
#         seonaut/distant.sh rapatrier     (copie les sauvegardes de la cible dans seonaut/sauvegardes/)
# Variables : SEONAUT_HOTE (défaut : server), SEONAUT_DOSSIER_DISTANT (défaut : seonaut),
#             SEONAUT_PORT (défaut : 9100).
set -euo pipefail
SCRIPT="$(readlink -f "$0")"
cd "$(dirname "$SCRIPT")"
HOTE="${SEONAUT_HOTE:-server}"
DISTANT="${SEONAUT_DOSSIER_DISTANT:-seonaut}"
PORT="${SEONAUT_PORT:-9100}"
commande="${1:-}"; shift || true
case "$commande" in
  demarrer|arreter|etat|sauvegarder|initialiser)
    ssh -t "$HOTE" "cd $DISTANT && ./$commande.sh $*" ;;
  tunnel)
    echo "Interface : http://localhost:$PORT (Ctrl+C pour fermer le tunnel)"
    ssh -N -L "$PORT:localhost:$PORT" "$HOTE" ;;
  rapatrier)
    mkdir -p sauvegardes && chmod 700 sauvegardes
    rsync -av "$HOTE:$DISTANT/sauvegardes/" sauvegardes/ ;;
  *)
    awk 'NR == 1 { next } !/^#/ { exit } /^# (SPDX-|Sous licence EUPL)/ { next } { sub(/^# ?/, ""); if (!vu && $0 == "") next; vu = 1; print }' "$SCRIPT"; exit 2 ;;
esac
