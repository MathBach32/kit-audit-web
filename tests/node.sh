#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Vérification de la recherche de Node (lib/kit.py, lib/commun.sh) quand le PATH n'en a pas de
# convenable, comme pour une commande lancée depuis le menu des applications, où nvm n'est pas chargé.
# Faux Node (scripts qui répondent à --version) et faux dossiers de nvm, dans un dossier temporaire :
#   - Node du PATH retenu s'il est assez récent, PATH des commandes inchangé ;
#   - sinon, parmi les versions de nvm (NVM_DIR, ~/.nvm, $XDG_CONFIG_HOME/nvm) : la plus récente de la
#     version majeure de .nvmrc, puis la plus récente ; versions trop anciennes ou hors service écartées ;
#   - lib/commun.sh : vrai Node retrouvé par nvm, outils de node_modules/.bin toujours en tête ;
#   - aucun Node : message explicite, et bin/lighthouse s'arrête dessus sans rien écrire.
# Appelé par tests/verifier.sh ; code 0 si conforme.
set -uo pipefail
RACINE="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
PYTHON="$RACINE/.venv/bin/python"; [ -x "$PYTHON" ] || PYTHON=python3
T="$(readlink -f "$(mktemp -d "${TMPDIR:-/tmp}/kit-node.XXXXXX")")"
trap 'rm -rf "$T"' EXIT
conformes=0; ecarts=0
verifier() {  # verifier <libellé> <commande…>
  local libelle="$1"; shift
  if "$@"; then conformes=$((conformes + 1)); else ecarts=$((ecarts + 1)); echo "ÉCART : $libelle"; fi
}
# faux_node <dossier> <version|hors-service> : script « node » qui répond à --version (ou échoue)
faux_node() {
  mkdir -p "$1"
  if [ "$2" = hors-service ]; then printf '#!/bin/sh\nexit 1\n'; else printf '#!/bin/sh\necho v%s\n' "$2"; fi > "$1/node"
  chmod +x "$1/node"
}
# nvm_factice <dossier de nvm> <version> [hors-service] : version installée par nvm
nvm_factice() { faux_node "$1/versions/node/v$2/bin" "${3:-$2}"; }
nvm_node() { echo "$1/versions/node/v$2/bin/node"; }
# kit_node <PATH> [VARIABLE=valeur…] : « python3 -m kit node », HOME vide, sans le nvm du poste
kit_node() {
  local chemin="$1"; shift
  env -u NVM_DIR -u XDG_CONFIG_HOME HOME="$T/maison" PATH="$chemin" PYTHONPATH="$RACINE/lib" "$@" "$PYTHON" -m kit node
}
egal() { [ "$1" = "$2" ] || { echo "  obtenu : ${1:-(rien)}"; echo "  attendu : $2"; return 1; }; }

MAJ="$(sed -n 's/^[[:space:]]*v\{0,1\}\([0-9]\{1,\}\).*/\1/p' "$RACINE/.nvmrc" | head -n 1)"   # version de .nvmrc
mkdir -p "$T/vide" "$T/maison"
faux_node "$T/recent" "$MAJ.0.0"
faux_node "$T/ancien" 18.20.0
faux_node "$T/casse" hors-service
NVM="$T/nvm"
nvm_factice "$NVM" 22.18.0                       # trop ancien (minimum : 22.19)
nvm_factice "$NVM" "$MAJ.1.0"
nvm_factice "$NVM" "$MAJ.3.0"
nvm_factice "$NVM" "$MAJ.4.0" hors-service       # le plus récent de .nvmrc, mais hors service
nvm_factice "$NVM" "$((MAJ + 2)).0.0"            # plus récent, mais pas la version de .nvmrc
AUTRES="$T/nvm-autres"                           # aucune version de .nvmrc
nvm_factice "$AUTRES" 22.18.0
nvm_factice "$AUTRES" "$((MAJ - 1)).5.0"
nvm_factice "$AUTRES" "$((MAJ + 1)).0.0"
nvm_factice "$T/maison-nvm/.nvm" "$MAJ.2.0"      # emplacement par défaut de nvm, NVM_DIR absent (menu)
nvm_factice "$T/config/nvm" "$MAJ.2.0"           # emplacement de nvm quand XDG_CONFIG_HOME est défini
ANCIENS="$T/nvm-anciens"
nvm_factice "$ANCIENS" 22.18.0

# --- Recherche (lib/kit.py) ----------------------------------------------------------------------
verifier "Node du PATH assez récent : retenu, nvm ignoré" egal "$(kit_node "$T/recent" NVM_DIR="$NVM")" "$T/recent/node"
verifier "Node du PATH trop ancien : version de .nvmrc la plus récente qui répond, dans nvm" \
  egal "$(kit_node "$T/ancien" NVM_DIR="$NVM")" "$(nvm_node "$NVM" "$MAJ.3.0")"
verifier "Node du PATH hors service : nvm" egal "$(kit_node "$T/casse" NVM_DIR="$NVM")" "$(nvm_node "$NVM" "$MAJ.3.0")"
verifier "Node absent du PATH : nvm" egal "$(kit_node "$T/vide" NVM_DIR="$NVM")" "$(nvm_node "$NVM" "$MAJ.3.0")"
verifier "nvm sans la version de .nvmrc : la plus récente" \
  egal "$(kit_node "$T/vide" NVM_DIR="$AUTRES")" "$(nvm_node "$AUTRES" "$((MAJ + 1)).0.0")"
verifier "NVM_DIR absent : ~/.nvm" \
  egal "$(kit_node "$T/vide" HOME="$T/maison-nvm")" "$(nvm_node "$T/maison-nvm/.nvm" "$MAJ.2.0")"
verifier "NVM_DIR absent : \$XDG_CONFIG_HOME/nvm" \
  egal "$(kit_node "$T/vide" XDG_CONFIG_HOME="$T/config")" "$(nvm_node "$T/config/nvm" "$MAJ.2.0")"
message="$(kit_node "$T/ancien" NVM_DIR="$ANCIENS" 2>&1)"
verifier "aucun Node convenable : code 1" [ "$?" = 1 ]
verifier "aucun Node convenable : message explicite" \
  bash -c '[[ "$1" == *"$2/node en version 18.20.0"* && "$1" == *"nvm install $3"* ]]' _ "$message" "$T/ancien" "$MAJ"

# --- PATH des commandes (lib/commun.sh), avec le vrai Node ----------------------------------------
NODE_REEL="$(readlink -f "$(PYTHONPATH="$RACINE/lib" "$PYTHON" -m kit node)")"
VERSION_REELLE="$("$NODE_REEL" --version)"
mkdir -p "$T/nvm-reel/versions/node/$VERSION_REELLE/bin"
ln -s "$NODE_REEL" "$T/nvm-reel/versions/node/$VERSION_REELLE/bin/node"
verifier "commun.sh : Node du PATH convenable, PATH inchangé" env PATH="$T/recent:$PATH" bash -c \
  'avant="$PATH"; . "$1/lib/commun.sh"; egal() { [ "$1" = "$2" ]; }; egal "$PATH" "$1/node_modules/.bin:$1/.venv/bin:$HOME/.local/bin:$avant"' _ "$RACINE"
verifier "commun.sh : Node hors service dans le PATH, celui de nvm passe devant ; outils du kit en tête ; outils Node lancés" \
  env -u XDG_CONFIG_HOME HOME="$T/maison" NVM_DIR="$T/nvm-reel" PATH="$T/casse:$PATH" bash -c \
  '. "$1/lib/commun.sh" && [ "$(command -v node)" = "$2" ] && [ "$(command -v lighthouse)" = "$1/node_modules/.bin/lighthouse" ] \
   && lighthouse --version > /dev/null && pa11y-ci --version > /dev/null && unlighthouse-ci --version > /dev/null' \
  _ "$RACINE" "$T/nvm-reel/versions/node/$VERSION_REELLE/bin/node"

# --- Aucun Node : arrêt explicite --------------------------------------------------------------------
env -u NVM_DIR -u XDG_CONFIG_HOME HOME="$T/maison" PATH="$T/ancien:$PATH" \
  "$RACINE/bin/lighthouse" http://127.0.0.1:9/ --dossier "$T/audit" > "$T/lighthouse.log" 2>&1
verifier "aucun Node : bin/lighthouse s'arrête (code 1)" [ "$?" = 1 ]
verifier "aucun Node : bin/lighthouse le dit" grep -q "ERREUR : Node .* introuvable" "$T/lighthouse.log"
verifier "aucun Node : bin/lighthouse n'écrit rien" [ ! -e "$T/audit" ]

echo "node : $conformes/$((conformes + ecarts)) contrôles conformes"
[ "$ecarts" -eq 0 ]
