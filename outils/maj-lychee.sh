#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Met à jour dans installer.sh les empreintes SHA-256 de lychee pour la version qui y est indiquée,
# d'après les fichiers .sha256 publiés avec cette version. Appelé par Renovate après la mise à jour
# de LYCHEE_VERSION ; utilisable à la main après une modification manuelle.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
version="$(sed -n 's/^LYCHEE_VERSION=//p' installer.sh)"
[[ "$version" =~ ^[0-9][0-9.]*$ ]] || { echo "LYCHEE_VERSION illisible dans installer.sh" >&2; exit 1; }
for arch in x86_64 aarch64; do
  somme="$(curl -sSfL "https://github.com/lycheeverse/lychee/releases/download/lychee-v$version/lychee-$arch-unknown-linux-gnu.tar.gz.sha256" | awk '{print $1}')"
  [[ "$somme" =~ ^[0-9a-f]{64}$ ]] || { echo "empreinte introuvable pour lychee $version ($arch)" >&2; exit 1; }
  sed -i "s/^  \[$arch\]=[0-9a-f]\{64\}$/  [$arch]=$somme/" installer.sh
  grep -q "^  \[$arch\]=$somme$" installer.sh || { echo "installer.sh : ligne $arch introuvable" >&2; exit 1; }
done
echo "lychee $version : empreintes à jour"
