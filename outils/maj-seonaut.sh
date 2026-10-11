#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Reporte le commit de SEOnaut épinglé dans seonaut/construire-image.sh sur l'étiquette de l'image
# (seonaut-kit:<7 caractères>) de seonaut/compose.yaml et seonaut/.env.exemple. Appelé par Renovate.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")/.."
commit="$(sed -n 's/^COMMIT=//p' seonaut/construire-image.sh)"
[[ "$commit" =~ ^[0-9a-f]{40}$ ]] || { echo "COMMIT illisible dans seonaut/construire-image.sh" >&2; exit 1; }
sed -i "s/seonaut-kit:[0-9a-f]\{7\}/seonaut-kit:${commit:0:7}/" seonaut/compose.yaml seonaut/.env.exemple
echo "SEOnaut : image seonaut-kit:${commit:0:7}"
