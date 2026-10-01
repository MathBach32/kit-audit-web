#!/usr/bin/env bash
# Construit l'image SEOnaut sur le poste pour linux/amd64 et linux/arm64, par compilation croisée
# (Dockerfile.croise : aucune émulation, rien n'est compilé sur le Pi).
# SEOnaut n'a pas de version publiée : le commit est épinglé ci-dessous et sert d'étiquette.
#
# Usage : seonaut/construire-image.sh [PLATEFORMES]   (défaut : linux/amd64,linux/arm64)
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"
COMMIT=880b312c28fab8b0bf7fe4f9449dc4746dbb82ff
IMAGE="seonaut-kit:${COMMIT:0:7}"
PLATEFORMES="${1:-linux/amd64,linux/arm64}"
SOURCES=.source

docker buildx version > /dev/null 2>&1 || { echo "docker buildx manquant : sudo apt install docker-buildx" >&2; exit 1; }
if [ ! -d "$SOURCES/.git" ]; then
  git clone -q https://github.com/StJudeWasHere/seonaut.git "$SOURCES"
fi
git -C "$SOURCES" cat-file -e "$COMMIT^{commit}" 2> /dev/null || git -C "$SOURCES" fetch -q origin
git -C "$SOURCES" -c advice.detachedHead=false checkout -q --detach "$COMMIT"
[ -z "$(git -C "$SOURCES" status --porcelain)" ] || { echo "sources modifiées dans $SOURCES : abandon" >&2; exit 1; }

echo "Construction de $IMAGE pour $PLATEFORMES (commit $COMMIT)"
docker buildx build --platform "$PLATEFORMES" -f Dockerfile.croise -t "$IMAGE" \
  --label "org.opencontainers.image.revision=$COMMIT" --load "$SOURCES"
docker image ls --tree "$IMAGE" 2> /dev/null || docker image ls "$IMAGE"
