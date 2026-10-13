#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Vérification de bout en bout : sert le site témoin (tests/site-temoin) sur un port libre, lance
# un audit complet sans PageSpeed Insights (qui exige une clé), puis compare les résultats aux
# défauts attendus (tests/attendus.py). L'audit tourne comme depuis le menu des applications, où nvm
# n'est pas chargé : un node hors service masque celui du poste, que les commandes doivent retrouver
# par un nvm factice. Vérifie aussi la recherche de Node (tests/node.sh), l'entrée du menu et le mode
# lanceur de l'interface (tests/lanceur.sh). À lancer après chaque mise à jour des dépendances ou du kit.
#
# Usage : tests/verifier.sh [--garder]
#   --garder  conserve le dossier d'audit (sinon supprimé si tout est conforme)
#
# Le navigateur est celui du kit (CHROME_PATH, sinon détection). Code de retour : 0 si conforme.
set -uo pipefail
RACINE="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PYTHON="$RACINE/.venv/bin/python"; [ -x "$PYTHON" ] || PYTHON=python3
GARDER=0; [ "${1:-}" = --garder ] && GARDER=1
[ -z "${TMPDIR:-}" ] || [ "${#TMPDIR}" -le 60 ] || export TMPDIR=/tmp   # même garde que lib/commun.sh (socket de Chrome)
PORT="$("$PYTHON" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
TRAVAIL="$(mktemp -d "${TMPDIR:-/tmp}/kit-verif.XXXXXX")"
python3 "$RACINE/tests/serveur_temoin.py" "$PORT" > "$TRAVAIL/serveur.log" 2>&1 &
SERVEUR=$!
trap 'kill "$SERVEUR" 2> /dev/null' EXIT
for _ in $(seq 50); do curl -sf -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 0.2; done
echo "site témoin : http://127.0.0.1:$PORT/ ; audit dans $TRAVAIL/audit"
# Lancement comme depuis le menu : node hors service en tête du PATH, vrai Node dans un nvm factice
NODE_REEL="$(PYTHONPATH="$RACINE/lib" "$PYTHON" -m kit node)" || { echo "audit non lancé (dossier : $TRAVAIL)"; exit 1; }
NODE_REEL="$(readlink -f "$NODE_REEL")"
NVM_FACTICE="$TRAVAIL/nvm/versions/node/$("$NODE_REEL" --version)/bin"
mkdir -p "$TRAVAIL/sans-node" "$NVM_FACTICE" && ln -s "$NODE_REEL" "$NVM_FACTICE/node"
printf '#!/bin/sh\necho "node hors service (tests/verifier.sh : lancement comme depuis le menu)" >&2\nexit 127\n' > "$TRAVAIL/sans-node/node"
chmod +x "$TRAVAIL/sans-node/node"
PATH="$TRAVAIL/sans-node:$PATH" NVM_DIR="$TRAVAIL/nvm" \
  "$RACINE/bin/tout" "http://127.0.0.1:$PORT/" --sans psi --dossier "$TRAVAIL/audit" > "$TRAVAIL/tout.log" 2>&1
echo "bin/tout (comme depuis le menu) : code $? (journal : $TRAVAIL/tout.log)"
# Relance partielle (comme « relancer un outil » dans l'interface) : le manifeste garde les autres outils
"$RACINE/bin/tout" "http://127.0.0.1:$PORT/" --seulement liens --dossier "$TRAVAIL/audit" > "$TRAVAIL/relance.log" 2>&1
echo "bin/tout --seulement liens : code $? (journal : $TRAVAIL/relance.log)"
PYTHONPATH="$RACINE/lib" "$PYTHON" "$RACINE/tests/attendus.py" "$TRAVAIL/audit"
code=$?
"$RACINE/tests/node.sh" || code=1
"$RACINE/tests/lanceur.sh" || code=1
if [ "$code" -eq 0 ] && [ "$GARDER" = 0 ]; then rm -rf "$TRAVAIL"; else echo "résultats conservés : $TRAVAIL"; fi
exit "$code"
