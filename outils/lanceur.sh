#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Entrée « Kit d'audit web » du menu des applications (Linux Mint, GNOME, KDE… : norme freedesktop
# Desktop Entry), qui ouvre l'interface graphique (bin/interface --lanceur). Installée par
# installer.sh dans une session graphique. Les chemins sont absolus : si le kit change de dossier,
# relancer ce script (ou ./installer.sh).
#
# Usage : outils/lanceur.sh [--retirer]
#   sans option  installe ou met à jour ~/.local/share/applications/kit-audit-web.desktop
#   --retirer    supprime l'entrée
set -euo pipefail
RACINE="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
DOSSIER="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
FICHIER="$DOSSIER/kit-audit-web.desktop"
case "${1:-}" in
  "") ;;
  --retirer) rm -f "$FICHIER"; echo "Entrée du menu retirée : $FICHIER"; exit 0 ;;
  -h|--help) sed -n '6,13s/^# \{0,1\}//p' "$0"; exit 0 ;;
  *) echo "argument inattendu : $1 (voir --help)" >&2; exit 2 ;;
esac
case "$RACINE" in *$'\n'*) echo "chemin du kit inutilisable (saut de ligne) : $RACINE" >&2; exit 1 ;; esac

# Exec : chemin entre guillemets doubles, où " ` $ et \ prennent une barre oblique inverse ; puis,
# comme dans toute valeur du fichier, chaque barre oblique inverse est doublée, et % aussi (codes
# de champ). Icon : seulement le doublement des barres obliques inverses.
commande="$(printf '%s' "$RACINE/bin/interface" | sed -e 's/[\\"`$]/\\&/g' -e 's/\\/\\\\/g' -e 's/%/%%/g')"
icone="$(printf '%s' "$RACINE/interface/icone.svg" | sed -e 's/\\/\\\\/g')"

temporaire="$(mktemp -d)"
trap 'rm -rf "$temporaire"' EXIT
tmp="$temporaire/kit-audit-web.desktop"   # desktop-file-validate exige l'extension
# StartupWMClass = CLASSE_FENETRE de lib/interface.py : le panneau range la fenêtre sous cette entrée
cat > "$tmp" << EOF
[Desktop Entry]
Type=Application
Name=Kit d'audit web
GenericName=Audit de site web
Comment=Lancer un audit de site, suivre son avancement et ouvrir les synthèses PDF
Exec="$commande" --lanceur
Icon=$icone
Terminal=false
Categories=Development;WebDevelopment;
Keywords=audit;site;web;SEO;référencement;accessibilité;performance;liens;PDF;
StartupNotify=true
StartupWMClass=KitAuditWeb
EOF
if command -v desktop-file-validate > /dev/null && ! desktop-file-validate "$tmp"; then
  echo "entrée du menu refusée par desktop-file-validate" >&2
  exit 1
fi
mkdir -p "$DOSSIER"
install -m 644 "$tmp" "$FICHIER"
command -v update-desktop-database > /dev/null && update-desktop-database -q "$DOSSIER" 2> /dev/null || true
echo "Entrée du menu installée : $FICHIER"
