#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Démarre SEOnaut à la demande. Quand les garde-fous sont actifs :
#   - avant : affiche la mémoire et l'état des conteneurs, refuse de démarrer si la mémoire
#     disponible est sous SEUIL_DEMARRAGE_MO ;
#   - après : vérifie de nouveau, et arrête SEOnaut de lui-même si la mémoire disponible passe
#     sous SEUIL_ALERTE_MO ou si un autre conteneur s'est arrêté ou est devenu « unhealthy ».
# Usage : ./demarrer.sh
. "$(dirname "$(readlink -f "$0")")/lib.sh"
exiger_env
docker image inspect "${SEONAUT_IMAGE:-seonaut-kit:880b312}" > /dev/null 2>&1 \
  || echec "image ${SEONAUT_IMAGE:-seonaut-kit:880b312} absente : la construire et la transférer depuis le poste (deployer.sh)"

echo "== Avant le démarrage ($(garde_fous_actifs && echo "garde-fous actifs" || echo "sans garde-fous"))"
afficher_etat
autres_avant="$(conteneurs_autres | cut -d' ' -f1)"
if garde_fous_actifs; then
  dispo=$(memoire_dispo_mo)
  [ "$dispo" -ge "$SEUIL_DEMARRAGE_MO" ] \
    || echec "mémoire disponible ${dispo} Mo, sous le seuil de ${SEUIL_DEMARRAGE_MO} Mo : démarrage refusé"
fi

echo; echo "== Démarrage"
if ! docker compose up -d --wait --wait-timeout 420; then
  docker compose logs --tail 40
  docker compose down
  echec "SEOnaut n'a pas démarré correctement : arrêté (journaux ci-dessus)"
fi
sleep 15   # laisser la mémoire se stabiliser après les migrations

echo; echo "== Après le démarrage"
afficher_etat
if garde_fous_actifs; then
  dispo=$(memoire_dispo_mo)
  autres_apres="$(conteneurs_autres)"
  perdus="$(comm -23 <(echo "$autres_avant") <(echo "$autres_apres" | cut -d' ' -f1))"
  malades="$(echo "$autres_apres" | grep -i unhealthy || true)"
  if [ "$dispo" -lt "$SEUIL_ALERTE_MO" ] || [ -n "$perdus" ] || [ -n "$malades" ]; then
    docker compose down
    echec "arrêt de sécurité : ${dispo} Mo disponibles${perdus:+, conteneurs arrêtés : $perdus}${malades:+, conteneurs en mauvaise santé : $malades}"
  fi
fi
echo
echo "SEOnaut tourne sur 127.0.0.1:${SEONAUT_PORT:-9100}. Depuis le poste : seonaut/distant.sh tunnel"
echo "  (ou ssh -N -L ${SEONAUT_PORT:-9100}:localhost:${SEONAUT_PORT:-9100} <alias SSH de cette machine>), puis http://localhost:${SEONAUT_PORT:-9100}"
echo "Arrêt : ./arreter.sh"
