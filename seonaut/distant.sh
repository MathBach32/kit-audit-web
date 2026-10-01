#!/usr/bin/env bash
# Depuis le poste : lance un script de SEOnaut sur l'hôte cible, par SSH.
# Usage : seonaut/distant.sh demarrer|arreter|etat|sauvegarder|initialiser [arguments]
#         seonaut/distant.sh tunnel        (ouvre le tunnel vers l'interface, Ctrl+C pour fermer)
#         seonaut/distant.sh rapatrier     (copie les sauvegardes de la cible dans seonaut/sauvegardes/)
# Variables : SEONAUT_HOTE (défaut : server), SEONAUT_DOSSIER_DISTANT (défaut : seonaut),
#             SEONAUT_PORT (défaut : 9100).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
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
    sed -n '2,/^[^#]/{/^#/s/^# \{0,1\}//p}' "$0"; exit 2 ;;
esac
