#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Choisit le navigateur d'une vérification automatique et écrit « CHROME_PATH=… » sur la sortie
# (à ajouter à l'environnement de la CI). Usage : tests/navigateur-ci.sh chrome|chromium
#   chrome    Google Chrome du système
#   chromium  Chromium du système s'il existe, sinon la dernière compilation du projet Chromium,
#             téléchargée (et non Chrome for Testing, qui reste une variante de Google Chrome)
set -euo pipefail
case "${1:-}" in
  chrome)
    chemin="$(command -v google-chrome-stable || command -v google-chrome)" ;;
  chromium)
    chemin="$(command -v chromium || command -v chromium-browser || true)"
    if [ -z "$chemin" ] || ! "$chemin" --version 2> /dev/null | grep -q '^Chromium '; then
      dossier="${RUNNER_TEMP:-/tmp}/navigateurs"
      sortie="$(npx --yes @puppeteer/browsers install chromium@latest --path "$dossier")"
      chemin="$(printf '%s\n' "$sortie" | tail -n 1 | awk '{print $NF}')"
    fi ;;
  *) echo "usage : $0 chrome|chromium" >&2; exit 2 ;;
esac
"$chemin" --version >&2
echo "CHROME_PATH=$chemin"
