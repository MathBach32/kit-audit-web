#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Depuis le poste : copie les fichiers de SEOnaut sur l'hôte cible et y transfère l'image
# (docker save | ssh docker load), puis télécharge MariaDB sur la cible. Ne démarre rien.
# Le .env et les sauvegardes de la cible ne sont jamais écrasés.
#
# Usage : seonaut/deployer.sh [--sans-image]
# Variables : SEONAUT_HOTE (défaut : server), SEONAUT_DOSSIER_DISTANT (défaut : seonaut, dans le
# dossier personnel), SEONAUT_PLATEFORME (défaut : déduite de l'architecture de la cible).
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
HOTE="${SEONAUT_HOTE:-server}"
DISTANT="${SEONAUT_DOSSIER_DISTANT:-seonaut}"
IMAGE="$(sed -n 's/^SEONAUT_IMAGE=//p' .env.exemple)"

echo "== Fichiers → $HOTE:~/$DISTANT"
rsync -a --chmod=D700,F600 --exclude .source --exclude .env --exclude sauvegardes --exclude Dockerfile.croise \
  --exclude construire-image.sh --exclude deployer.sh --exclude distant.sh \
  ./ "$HOTE:$DISTANT/"
ssh "$HOTE" "chmod 700 $DISTANT/*.sh && chmod 644 $DISTANT/mariadb/garde-fous.cnf"

if [ "${1:-}" != --sans-image ]; then
  arch="$(ssh "$HOTE" uname -m)"
  case "${SEONAUT_PLATEFORME:-$arch}" in
    aarch64|arm64|linux/arm64) plateforme=linux/arm64 ;;
    x86_64|amd64|linux/amd64) plateforme=linux/amd64 ;;
    *) echo "architecture $arch non prévue" >&2; exit 1 ;;
  esac
  echo "== Image $IMAGE ($plateforme) → $HOTE"
  docker save --platform "$plateforme" "$IMAGE" | gzip -1 | ssh "$HOTE" 'gunzip | docker load'
  echo "== MariaDB sur $HOTE"
  ssh "$HOTE" "docker pull -q $(sed -n 's/^ *image: \(mariadb:.*\)$/\1/p' compose.yaml)"
fi
echo "Terminé. Sur $HOTE : cd ~/$DISTANT && ./initialiser.sh && ./demarrer.sh"
