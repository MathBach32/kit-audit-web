#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Vérification de bout en bout : sert le site témoin (tests/site-temoin) sur un port libre, lance
# un audit complet sans PageSpeed Insights (qui exige une clé), puis compare les résultats aux
# défauts attendus (tests/attendus.py). À lancer après chaque mise à jour des dépendances ou du kit.
#
# Usage : tests/verifier.sh [--garder]
#   --garder  conserve le dossier d'audit (sinon supprimé si tout est conforme)
#
# Le navigateur est celui du kit (CHROME_PATH, sinon détection). Code de retour : 0 si conforme.
set -uo pipefail
RACINE="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PYTHON="$RACINE/.venv/bin/python"; [ -x "$PYTHON" ] || PYTHON=python3
GARDER=0; [ "${1:-}" = --garder ] && GARDER=1
[ "${#TMPDIR}" -le 60 ] || export TMPDIR=/tmp   # même garde que lib/commun.sh (socket de Chrome)
PORT="$("$PYTHON" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"
TRAVAIL="$(mktemp -d "${TMPDIR:-/tmp}/kit-verif.XXXXXX")"
python3 "$RACINE/tests/serveur_temoin.py" "$PORT" > "$TRAVAIL/serveur.log" 2>&1 &
SERVEUR=$!
trap 'kill "$SERVEUR" 2> /dev/null' EXIT
for _ in $(seq 50); do curl -sf -o /dev/null "http://127.0.0.1:$PORT/" && break; sleep 0.2; done
echo "site témoin : http://127.0.0.1:$PORT/ ; audit dans $TRAVAIL/audit"
"$RACINE/bin/tout" "http://127.0.0.1:$PORT/" --sans psi --dossier "$TRAVAIL/audit" > "$TRAVAIL/tout.log" 2>&1
echo "bin/tout : code $? (journal : $TRAVAIL/tout.log)"
PYTHONPATH="$RACINE/lib" "$PYTHON" "$RACINE/tests/attendus.py" "$TRAVAIL/audit"
code=$?
if [ "$code" -eq 0 ] && [ "$GARDER" = 0 ]; then rm -rf "$TRAVAIL"; else echo "résultats conservés : $TRAVAIL"; fi
exit "$code"
