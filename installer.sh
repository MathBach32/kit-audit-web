#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Installe les dépendances du kit sans sudo et vérifie les prérequis du système.
#   - outils Node (versions exactes de package-lock.json, sans télécharger de Chromium)
#   - environnement Python .venv (versions figées et empreintes SHA-256 de requirements.txt)
#   - lychee dans ~/.local/bin (release GitHub, somme SHA-256 vérifiée)
#   - fichier des secrets ~/.config/audit-kit/secrets.env (créé vide, droits 600, s'il manque)
#
# Usage : ./installer.sh [--verifier]
#   --verifier  contrôle seulement, n'installe rien
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"
LYCHEE_VERSION=0.24.2
declare -A LYCHEE_SHA256=(
  [x86_64]=1f4e0ef7f6554a6ed33dd7ac144fb2e1bbed98598e7af973042fc5cd43951c9a
  [aarch64]=91a7bd65685da41b90ccb9bc867a3d649a7818042dae04ff405e55a25bddee4c
)
NODE_MIN=22.19
SECRETS="${KIT_AUDIT_SECRETS:-$HOME/.config/audit-kit/secrets.env}"
VERIFIER=0; [ "${1:-}" = --verifier ] && VERIFIER=1
manques=0

ok() { printf '  \033[32mOK\033[0m      %s\n' "$*"; }
manque() { printf '  \033[31mMANQUE\033[0m  %s\n' "$*"; manques=$((manques + 1)); }
info() { printf '  \033[33mINFO\033[0m    %s\n' "$*"; }
version_ge() { [ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -n1)" = "$2" ]; }

echo "Prérequis du système"
for c in curl dig openssl python3 git; do
  command -v "$c" > /dev/null && ok "$c" || manque "$c (paquet : $c, ou bind9-dnsutils pour dig)"
done
python3 -c 'import venv, ensurepip' 2> /dev/null && ok "python3-venv" || manque "python3-venv (sudo apt install python3-venv)"
# Navigateur : même détection que les commandes du kit (lib/kit.py), CHROME_PATH pour en imposer un
if CHROME="$(python3 lib/kit.py navigateur 2> /dev/null)"; then
  VERSION_CHROME="$(python3 lib/kit.py version-navigateur "$CHROME")"
  ok "Navigateur : ${VERSION_CHROME:-version inconnue} ($CHROME)"
  [ "${KIT_NAVIGATEUR_LIBRE:-}" = 1 ] && [ -n "${CHROME_PATH:-}" ] && info "KIT_NAVIGATEUR_LIBRE=1 : navigateur imposé accepté sans contrôle de version"
  # Snap : repéré par sa version (« … snap », même derrière le script chromium-browser) ou par son chemin
  CHROME_REEL="$(readlink -f "$CHROME")"
  if [[ "$VERSION_CHROME" == *" snap" || "$CHROME_REEL" == */snap || "$CHROME_REEL" == /snap/* ]]; then
    info "Chromium en snap : pas d'accès aux dossiers cachés de \$HOME ni au /tmp de l'hôte ; garder les résultats sous \$HOME, hors dossier caché (défaut : ${KIT_AUDIT_RESULTATS:-$PWD/resultats})"
  fi
else
  manque "navigateur : $(python3 lib/kit.py navigateur 2>&1 > /dev/null)"
fi
if command -v node > /dev/null && version_ge "$(node --version | tr -d v)" "$NODE_MIN"; then
  ok "Node $(node --version)"
else
  manque "Node ≥ $NODE_MIN (par exemple via nvm : nvm install 24)"
fi
if docker buildx version > /dev/null 2>&1; then
  ok "docker buildx $(docker buildx version | awk '{print $2}') (image SEOnaut)"
else
  info "docker buildx absent : nécessaire seulement pour construire l'image SEOnaut (sudo apt install docker-buildx)"
fi

echo "Dépendances du kit"
if [ "$VERIFIER" = 0 ] && command -v npm > /dev/null; then
  PUPPETEER_SKIP_DOWNLOAD=1 npm ci --ignore-scripts --no-audit --no-fund > /dev/null && ok "outils Node installés" || manque "npm ci a échoué"
fi
for b in lighthouse unlighthouse-ci pa11y-ci; do
  [ -x "node_modules/.bin/$b" ] && ok "$b" || manque "$b (lancer ./installer.sh)"
done

if [ "$VERIFIER" = 0 ]; then
  [ -x .venv/bin/python ] || python3 -m venv .venv
  .venv/bin/pip install -q --upgrade pip && .venv/bin/pip install -q --require-hashes -r requirements.txt && ok "environnement Python installé" || manque "installation Python"
fi
.venv/bin/python -c 'import advertools' 2> /dev/null && ok "advertools $(.venv/bin/python -c 'import advertools; print(advertools.__version__)')" || manque "advertools (lancer ./installer.sh)"

LYCHEE="$HOME/.local/bin/lychee"
if [ -x "$LYCHEE" ] && "$LYCHEE" --version | grep -q " $LYCHEE_VERSION$"; then
  ok "lychee $LYCHEE_VERSION"
elif [ "$VERIFIER" = 1 ]; then
  manque "lychee $LYCHEE_VERSION (lancer ./installer.sh)"
else
  arch="$(uname -m)"; attendu="${LYCHEE_SHA256[$arch]:-}"
  if [ -z "$attendu" ]; then
    manque "lychee : architecture $arch non prévue (voir https://github.com/lycheeverse/lychee/releases)"
  else
    tmp="$(mktemp -d)"; archive="lychee-$arch-unknown-linux-gnu.tar.gz"
    curl -sSfL -o "$tmp/$archive" "https://github.com/lycheeverse/lychee/releases/download/lychee-v$LYCHEE_VERSION/$archive"
    if [ "$(sha256sum "$tmp/$archive" | cut -d' ' -f1)" = "$attendu" ]; then
      tar -xzf "$tmp/$archive" -C "$tmp" && mkdir -p "$HOME/.local/bin" \
        && install -m 755 "$tmp/lychee-$arch-unknown-linux-gnu/lychee" "$LYCHEE" && ok "lychee $LYCHEE_VERSION installé dans ~/.local/bin"
    else
      manque "lychee : somme SHA-256 inattendue, installation refusée"
    fi
    rm -rf "$tmp"
  fi
fi

echo "Secrets"
if [ -f "$SECRETS" ]; then
  [ "$(stat -c %a "$SECRETS")" = 600 ] && ok "$SECRETS (droits 600)" || manque "$SECRETS : droits $(stat -c %a "$SECRETS"), lancer chmod 600"
  grep -q '^PSI_API_KEY=..*' "$SECRETS" && ok "PSI_API_KEY renseignée" || info "PSI_API_KEY vide : bin/psi indisponible"
elif [ "$VERIFIER" = 0 ]; then
  mkdir -p "$(dirname "$SECRETS")" && chmod 700 "$(dirname "$SECRETS")"
  ( umask 077; printf '# Clé API PageSpeed Insights (Google Cloud, restreinte à « PageSpeed Insights API »)\nPSI_API_KEY=\n' > "$SECRETS" )
  info "$SECRETS créé (droits 600) : y renseigner PSI_API_KEY"
else
  info "$SECRETS absent : bin/psi indisponible"
fi

[ "$manques" -eq 0 ] && echo "Tout est prêt." || { echo "$manques prérequis manquant(s)."; exit 1; }
