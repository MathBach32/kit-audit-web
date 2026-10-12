#!/usr/bin/env bash
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
#
# Vérification de l'entrée du menu et du mode lanceur de l'interface, sans écran ni vrai navigateur :
#   - outils/lanceur.sh, depuis une copie au nom piégé (espace, apostrophe, guillemets, %, $) :
#     entrée valide (desktop-file-validate s'il est là), chemins bien échappés, --retirer ;
#   - bin/interface --lanceur avec un faux navigateur qui tient le profil comme Chrome (lien
#     SingletonLock) : fenêtre ouverte, journal sans jeton, deuxième lancement reçu par l'interface
#     en cours (nouvelle fenêtre, autre jeton), arrêt quand le navigateur quitte.
# Tout se passe dans un dossier temporaire (XDG_RUNTIME_DIR, XDG_CACHE_HOME, XDG_DATA_HOME) : ni
# l'interface ni le menu du compte ne sont touchés. Appelé par tests/verifier.sh ; code 0 si conforme.
set -uo pipefail
RACINE="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
T="$(mktemp -d "${TMPDIR:-/tmp}/kit-lanceur.XXXXXX")"
export XDG_RUNTIME_DIR="$T/run" XDG_CACHE_HOME="$T/cache" XDG_DATA_HOME="$T/data" KIT_AUDIT_RESULTATS="$T/resultats"
export CHROME_PATH="$T/faux-chrome" KIT_NAVIGATEUR_LIBRE=1 FAUX_JOURNAL="$T/fenetres.txt"
export DBUS_SESSION_BUS_ADDRESS="unix:path=$T/aucun-bus"   # aucune notification sur le bureau
mkdir -m 700 "$XDG_RUNTIME_DIR"
JOURNAL="$XDG_CACHE_HOME/kit-audit-web/interface.log"
PROFIL="$XDG_CACHE_HOME/kit-audit-web/interface"
INTERFACE=
trap 'pkill -f -- "$CHROME_PATH" 2> /dev/null; [ -n "$INTERFACE" ] && kill "$INTERFACE" 2> /dev/null; rm -rf "$T"' EXIT
conformes=0; ecarts=0
verifier() {  # verifier <libellé> <commande…>
  local libelle="$1"; shift
  if "$@"; then conformes=$((conformes + 1)); else ecarts=$((ecarts + 1)); echo "ÉCART : $libelle"; fi
}
attendre() {  # attendre <secondes> <commande…> : vrai dès que la commande réussit
  local n=$(($1 * 5)); shift
  for _ in $(seq "$n"); do "$@" && return 0; sleep 0.2; done
  return 1
}

# --- Entrée du menu ------------------------------------------------------------------------------
KIT="$T/kit d'audit \"100%\" \$HOME"
mkdir -p "$KIT/outils" && cp "$RACINE/outils/lanceur.sh" "$KIT/outils/"
ENTREE="$XDG_DATA_HOME/applications/kit-audit-web.desktop"
verifier "outils/lanceur.sh : code 0" "$KIT/outils/lanceur.sh" > /dev/null
verifier "entrée du menu : Exec et Icon pointent vers le kit (échappements)" "$RACINE/.venv/bin/python" - "$ENTREE" "$KIT" << 'EOF'
import re, sys
def chaine(v):  # échappements des valeurs de chaîne (norme Desktop Entry)
    return re.sub(r"\\(.)", lambda m: {"s": " ", "n": "\n", "t": "\t", "r": "\r", "\\": "\\"}.get(m.group(1), "\\" + m.group(1)), v)
def exec_args(v):  # citation de la clé Exec (" ` $ \ échappés entre guillemets), puis %% → %
    args, cour, guill, i, v = [], None, False, 0, chaine(v)
    while i < len(v):
        c = v[i]
        if guill and c == "\\" and v[i + 1:i + 2] in ('"', "`", "$", "\\"):
            cour, i = (cour or "") + v[i + 1], i + 2
            continue
        if c == '"':
            guill, cour = not guill, cour or ""
        elif c == " " and not guill:
            if cour is not None:
                args.append(cour)
            cour = None
        else:
            cour = (cour or "") + c
        i += 1
    return [a.replace("%%", "%") for a in args + ([cour] if cour is not None else [])]
cles = dict(l.split("=", 1) for l in open(sys.argv[1], encoding="utf-8").read().splitlines() if "=" in l)
sys.exit(exec_args(cles["Exec"]) != [sys.argv[2] + "/bin/interface", "--lanceur"]
         or chaine(cles["Icon"]) != sys.argv[2] + "/interface/icone.svg"
         or cles.get("StartupWMClass") != "KitAuditWeb")
EOF
verifier "outils/lanceur.sh --retirer" bash -c '"$1/outils/lanceur.sh" --retirer > /dev/null && [ ! -e "$2" ]' _ "$KIT" "$ENTREE"
command -v desktop-file-validate > /dev/null || echo "(desktop-file-validate absent : entrée non validée)"

# --- Mode lanceur --------------------------------------------------------------------------------
# Faux navigateur : note l'adresse reçue, puis tient le profil comme Chrome (lien SingletonLock
# « hôte-PID », retiré en quittant) ; si un navigateur vivant le tient déjà, lui passe le relais.
cat > "$CHROME_PATH" << 'EOF'
#!/usr/bin/env bash
for a; do case "$a" in --user-data-dir=*) profil="${a#*=}" ;; --app=*) echo "${a#*=}" >> "$FAUX_JOURNAL" ;; esac; done
cible="$(readlink "$profil/SingletonLock" 2> /dev/null)" && kill -0 "${cible##*-}" 2> /dev/null && exit 0
mkdir -p "$profil" && ln -sfn "$HOSTNAME-$$" "$profil/SingletonLock"
trap 'rm -f "$profil/SingletonLock"; exit 0' TERM INT
while :; do sleep 0.2; done
EOF
chmod +x "$CHROME_PATH"
fenetres() { [ "$(cat "$FAUX_JOURNAL" 2> /dev/null | wc -l)" -ge "$1" ]; }
repond() { [[ "$(curl -s -o /dev/null -w '%{http_code}' "$1")" == [23]?? ]]; }
arretee() { ! kill -0 "$INTERFACE" 2> /dev/null; }
PORT="$("$RACINE/.venv/bin/python" -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')"

"$RACINE/bin/interface" --lanceur --port "$PORT" &
INTERFACE=$!
verifier "mode lanceur : fenêtre ouverte" attendre 30 fenetres 1
URL1="$(sed -n 1p "$FAUX_JOURNAL")"
verifier "mode lanceur : l'interface répond à l'adresse de la fenêtre" attendre 10 repond "$URL1"
verifier "mode lanceur : journal écrit, sans jeton" bash -c 'grep -q "^Interface du kit" "$1" && ! grep -q "jeton=" "$1"' _ "$JOURNAL"
verifier "mode lanceur : fenêtre repérée par l'interface" attendre 10 grep -q "^Fenêtre ouverte" "$JOURNAL"

timeout 30 "$RACINE/bin/interface" > "$T/second.log" 2>&1
verifier "deuxième lancement : code 0" [ "$?" = 0 ]
verifier "deuxième lancement : renvoyé à l'interface en cours, sans en démarrer une autre" \
  bash -c 'grep -q "tourne déjà" "$1" && ! grep -q "^Interface du kit" "$1"' _ "$T/second.log"
verifier "deuxième lancement : nouvelle fenêtre ouverte par l'interface en cours" attendre 10 fenetres 2
URL2="$(sed -n 2p "$FAUX_JOURNAL")"
verifier "deuxième lancement : même interface" [ "${URL1%%\?*}" = "${URL2%%\?*}" ]
verifier "deuxième lancement : autre jeton" [ "$URL1" != "$URL2" ]
verifier "deuxième lancement : le jeton de la nouvelle fenêtre est accepté" repond "$URL2"
verifier "deuxième lancement : l'interface en cours tourne toujours" kill -0 "$INTERFACE"

cible="$(readlink "$PROFIL/SingletonLock")"
kill "${cible##*-}"
verifier "fenêtre fermée : interface arrêtée" attendre 15 arretee
wait "$INTERFACE"
verifier "fenêtre fermée : code 0" [ "$?" = 0 ]
INTERFACE=
verifier "fenêtre fermée : arrêt noté dans le journal" grep -q "Fenêtre fermée : arrêt de l'interface" "$JOURNAL"

echo "lanceur : $conformes/$((conformes + ecarts)) contrôles conformes"
[ "$ecarts" -eq 0 ]
