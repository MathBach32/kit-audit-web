# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Fonctions Python communes du kit : URL, identifiants de page, accès réseau, lecture de CSV, navigateur.

Utilisable aussi en ligne de commande depuis les scripts shell :
  python3 -m kit url ADRESSE       → URL normalisée (https:// ajouté, chemin « / » par défaut)
  python3 -m kit domaine URL       → nom d'hôte
  python3 -m kit slug URL          → identifiant de fichier lisible (« accueil », « edition-2026 »…)
  python3 -m kit navigateur        → chemin du navigateur (CHROME_PATH, sinon Google Chrome ou Chromium détecté)
                                     KIT_NAVIGATEUR_LIBRE=1 : CHROME_PATH accepté sans contrôle de version
  python3 -m kit version-navigateur CHEMIN → « Google Chrome 155.0… », « Chromium 157.0… » (« … snap » pour le snap)
  python3 -m kit node              → chemin de Node (celui du PATH s'il est assez récent, sinon une version de nvm)
  python3 -m kit acces URL         → « ok » (code 0), sinon la raison du refus (code 1) : voir acces()
"""
import csv
import glob
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UA =os.environ.get("KIT_UA", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/154.0 Safari/537.36 kit-audit-web")
EXTENSIONS_RESSOURCES = re.compile(
    r"\.(jpe?g|png|gif|webp|avif|svg|ico|bmp|tiff?|pdf|zip|gz|mp[34]|m4a|mov|avi|webm|ogg|wav|"
    r"css|js|json|xml|txt|woff2?|ttf|otf|eot|docx?|xlsx?|pptx?|odt|ods)$", re.I)
# Navigateurs reconnus, par ordre de préférence : Google Chrome, puis Chromium (paquet, snap ou chemin direct).
# Le snap passe avant chromium-browser, qui sur Ubuntu n'est qu'un script de transition vers lui.
NAVIGATEURS = ("google-chrome-stable", "google-chrome", "chromium", "/snap/bin/chromium", "chromium-browser",
               "/usr/lib/chromium/chromium", "/opt/google/chrome/chrome")
VERSION_NAVIGATEUR = re.compile(r"^(Google Chrome|Chromium)\b.*?\d+(\.\d+)+( snap)?", re.M)
DELAI_VERSION = 5  # secondes accordées à « navigateur --version » et à « node --version »
NODE_MIN = (22, 19)  # version minimale de Node pour les outils de package.json ; .nvmrc donne celle de la CI


def normaliser_url(adresse):
    adresse = adresse.strip()
    if not re.match(r"^https?://", adresse, re.I):
        adresse = "https://" + adresse
    p = urllib.parse.urlsplit(adresse)
    if not p.hostname:
        raise ValueError(f"URL invalide : {adresse}")
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or "/", p.query, ""))


def domaine(url):
    return urllib.parse.urlsplit(url).hostname or ""


def domaine_racine(url_ou_hote):
    hote = domaine(url_ou_hote) if "://" in url_ou_hote else url_ou_hote
    return hote[4:] if hote.startswith("www.") else hote


def meme_site(url, site):
    """Vrai si url appartient au même site (www. ignoré)."""
    return domaine_racine(domaine(url)) == domaine_racine(domaine(site))


def slug(url):
    """Identifiant de fichier lisible tiré du chemin de l'URL."""
    p = urllib.parse.urlsplit(url)
    s = (p.path.strip("/") + ("_" + p.query if p.query else "")) or "accueil"
    s = re.sub(r"[^\w.-]+", "_", s).strip("_")
    return s[:80] or "accueil"


def est_page(url):
    """Vrai si l'URL ressemble à une page HTML (ni ressource, ni fichier téléchargeable)."""
    p = urllib.parse.urlsplit(url)
    return p.scheme in ("http", "https") and "/wp-content/" not in p.path and not EXTENSIONS_RESSOURCES.search(p.path)


def recuperer(url, methode="GET", delai=30, entetes=None):
    """Renvoie (statut, url_finale, corps, en-têtes). Statut 0 si aucune réponse."""
    h = {"User-Agent": UA, "Accept-Language": "fr,en;q=0.8"}
    h.update(entetes or {})
    req = urllib.request.Request(url, method=methode, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=delai) as r:
            corps = r.read() if methode == "GET" else b""
            return r.status, r.geturl(), corps, dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, url, b"", dict(e.headers or {})
    except Exception as e:  # noqa: BLE001 — toute erreur réseau est consignée comme « pas de réponse »
        return 0, url, str(e).encode(), {}


# Réponses d'un hébergeur qui bloque un temps les visiteurs trop actifs (o2switch « Tiger Protect »,
# pare-feu applicatifs…) : trop de requêtes (429) ou service indisponible (503)
CODES_REFUS = {429: "trop de requêtes", 503: "service indisponible"}


def acces(url, delai=20):
    """"" si le site répond normalement (y compris par une redirection ou une erreur 404 ou 500), sinon
    la raison du refus : code 429 ou 503, ou aucune réponse (connexion ou négociation TLS refusée,
    comme quand un pare-feu bloque l'adresse du poste). Une seule requête GET, sans relance."""
    statut, _, corps, _ = recuperer(url, delai=delai)
    if statut in CODES_REFUS:
        return f"code {statut} : {CODES_REFUS[statut]}"
    if not statut:
        return f"aucune réponse : {corps.decode('utf-8', 'replace')[:120]}"
    return ""


def lire_csv(chemin):
    """Lit un CSV (UTF-8 avec ou sans BOM) en liste de dictionnaires ; liste vide si absent."""
    if not os.path.exists(chemin):
        return []
    with open(chemin, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def lire_catalogue(chemin=None):
    """Catalogue des constats SEO (config/problemes.csv) : code → ligne (libellé, catégorie, gravité…)."""
    chemin = chemin or os.path.join(RACINE, "config", "problemes.csv")
    with open(chemin, newline="", encoding="utf-8") as f:
        lignes = [l for l in f if not l.startswith("#")]
    return {l["code"]: l for l in csv.DictReader(lignes)}


_LARGEURS = {}


def largeur_px(texte, taille):
    """Largeur en pixels de texte affiché en Arial à la taille donnée, sans crénage (comme les
    résultats de recherche de Google : 20 px pour le title, 14 px pour la description)."""
    if not _LARGEURS:
        with open(os.path.join(RACINE, "config", "largeurs_arial.json"), encoding="utf-8") as f:
            _LARGEURS.update(json.load(f)["largeurs"])
    defaut = _LARGEURS["n"]
    return round(sum(_LARGEURS.get(c, defaut) for c in texte) * taille / 1000)


def lire_liste(chemin):
    """Lignes non vides et non commentées d'un fichier texte."""
    with open(chemin, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def version_navigateur(chemin):
    """« Google Chrome 155.0.8059.39 » ou « Chromium 157.0.8097.0 » selon « chemin --version », suivi
    de « snap » pour le Chromium du snap, même atteint par un script de transition (chromium-browser) ;
    "" si chemin n'est ni Google Chrome ni Chromium (sur Ubuntu, chromium-browser peut n'être qu'un
    script qui propose d'installer le snap).

    Un programme qui ne répond pas en DELAI_VERSION secondes est abandonné : lancé dans sa propre
    session, il est arrêté avec tout son groupe de processus, sans laisser d'orphelin."""
    try:
        p = subprocess.Popen([chemin, "--version"], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL, text=True, errors="replace", start_new_session=True)
    except OSError:
        return ""
    try:
        sortie, _ = p.communicate(timeout=DELAI_VERSION)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
        p.stdout.close()  # sans attendre la fin de l'écriture : un descendant sorti du groupe peut la garder ouverte
        p.wait()
        return ""
    m = VERSION_NAVIGATEUR.search(sortie)
    return m.group(0) if m and p.returncode == 0 else ""


def navigateur_libre():
    """Vrai si KIT_NAVIGATEUR_LIBRE=1 : CHROME_PATH peut désigner un autre navigateur de la famille
    Chromium (Brave, Microsoft Edge…), accepté sans contrôle de sa version."""
    return os.environ.get("KIT_NAVIGATEUR_LIBRE") == "1"


def navigateur():
    """Chemin absolu du navigateur à utiliser ; "" si aucun.

    CHROME_PATH, s'il est défini, est pris tel quel (pas de repli silencieux sur un autre navigateur),
    à condition d'être exécutable et de répondre à --version par une version de Google Chrome ou de
    Chromium, sauf avec KIT_NAVIGATEUR_LIBRE=1 ; sinon, premier de NAVIGATEURS qui répond par une
    telle version."""
    impose = os.environ.get("CHROME_PATH")
    if impose:
        chemin = shutil.which(impose)
        if not chemin or not (navigateur_libre() or version_navigateur(chemin)):
            return ""
        return os.path.abspath(chemin)
    for candidat in NAVIGATEURS:
        chemin = shutil.which(candidat)
        if chemin and version_navigateur(chemin):
            return os.path.abspath(chemin)
    return ""


def sans_navigateur():
    """Message d'erreur quand navigateur() ne trouve rien."""
    impose = os.environ.get("CHROME_PATH")
    if impose and not shutil.which(impose):
        return (f"CHROME_PATH={impose} : navigateur introuvable ou non exécutable (corriger le chemin, "
                "ou retirer CHROME_PATH pour la détection automatique)")
    if impose:
        return (f"CHROME_PATH={impose} : ne répond pas à --version comme Google Chrome ou Chromium (corriger "
                "le chemin, ou retirer CHROME_PATH pour la détection automatique ; pour un autre navigateur "
                "de la famille Chromium, comme Brave ou Microsoft Edge, ajouter KIT_NAVIGATEUR_LIBRE=1)")
    return ("aucun navigateur trouvé : installer Google Chrome (https://www.google.com/chrome/) ou Chromium "
            "(paquet de la distribution ou snap), ou indiquer le chemin du navigateur dans CHROME_PATH")


def version_node(chemin):
    """(24, 19, 0)… selon « chemin --version » ; None si chemin ne répond pas comme Node."""
    try:
        r = subprocess.run([chemin, "--version"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           errors="replace", timeout=DELAI_VERSION)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.match(r"v(\d+)\.(\d+)\.(\d+)", r.stdout)
    return tuple(map(int, m.groups())) if m and r.returncode == 0 else None


def _majeure_nvmrc():
    """Version majeure de Node indiquée par .nvmrc ; None si illisible."""
    try:
        with open(os.path.join(RACINE, ".nvmrc"), encoding="utf-8") as f:
            m = re.match(r"\s*v?(\d+)", f.read())
    except OSError:
        return None
    return int(m.group(1)) if m else None


def versions_nvm():
    """Node installés par nvm : [((24, 19, 0), chemin)], d'après les noms des dossiers. Dossiers de nvm :
    NVM_DIR, ~/.nvm et $XDG_CONFIG_HOME/nvm (défaut de nvm quand XDG_CONFIG_HOME est défini)."""
    maison = os.path.expanduser("~")
    dossiers = (os.environ.get("NVM_DIR"), os.path.join(maison, ".nvm"),
                os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.join(maison, ".config"), "nvm"))
    trouves = []
    for dossier in dict.fromkeys(os.path.realpath(d) for d in dossiers if d):
        for chemin in glob.glob(os.path.join(glob.escape(dossier), "versions", "node", "v*", "bin", "node")):
            m = re.fullmatch(r"v(\d+)\.(\d+)\.(\d+)", chemin.split(os.sep)[-3])
            if m:
                trouves.append((tuple(map(int, m.groups())), chemin))
    return trouves


def node():
    """Chemin absolu de Node en version NODE_MIN ou plus récente ; "" si aucun.

    D'abord celui du PATH ; sinon une version installée par nvm. nvm ne se charge que dans les shells
    interactifs (~/.bashrc) : le PATH d'une commande lancée depuis le menu des applications (interface
    du kit), cron ou systemd n'a pas son Node. Parmi les versions de nvm : la plus récente de la version
    majeure de .nvmrc (celle de la CI), sinon la plus récente ; chacune est essayée (--version) avant
    d'être retenue."""
    chemin = shutil.which("node")
    if chemin and (version_node(chemin) or ()) >= NODE_MIN:
        return os.path.abspath(chemin)
    majeure = _majeure_nvmrc()
    for version, chemin in sorted(versions_nvm(), key=lambda v: (v[0][0] == majeure, v[0]), reverse=True):
        if version >= NODE_MIN and (version_node(chemin) or ()) >= NODE_MIN:
            return chemin
    return ""


def sans_node():
    """Message d'erreur quand node() ne trouve rien."""
    chemin = shutil.which("node")
    version = version_node(chemin) if chemin else None
    dans_path = (f"{chemin} en version {'.'.join(map(str, version))}" if version
                 else f"{chemin} ne répond pas comme Node" if chemin else "absent")
    return (f"Node {'.'.join(map(str, NODE_MIN))} ou plus récent introuvable (PATH : {dans_path} ; aucune version "
            f"convenable installée par nvm) : installer Node, par exemple avec nvm (nvm install "
            f"{_majeure_nvmrc() or NODE_MIN[0]}), puis lancer ./installer.sh")


def _principal(argv):
    recherches = {"navigateur": (navigateur, sans_navigateur), "node": (node, sans_node)}
    if len(argv) == 2 and argv[1] in recherches:
        trouver, message = recherches[argv[1]]
        chemin = trouver()
        print(chemin or message(), file=sys.stdout if chemin else sys.stderr)
        return 0 if chemin else 1
    if len(argv) == 3 and argv[1] == "acces":
        raison = acces(argv[2])
        print(raison or "ok")
        return 1 if raison else 0
    commandes = {"url": normaliser_url, "domaine": domaine, "slug": slug, "version-navigateur": version_navigateur}
    if len(argv) != 3 or argv[1] not in commandes:
        print(__doc__, file=sys.stderr)
        return 2
    try:
        print(commandes[argv[1]](argv[2]))
    except ValueError as e:
        print(e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(_principal(sys.argv))
