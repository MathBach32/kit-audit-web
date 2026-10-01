"""Fonctions Python communes du kit : URL, identifiants de page, accès réseau, lecture de CSV.

Utilisable aussi en ligne de commande depuis les scripts shell :
  python3 -m kit url ADRESSE       → URL normalisée (https:// ajouté, chemin « / » par défaut)
  python3 -m kit domaine URL       → nom d'hôte
  python3 -m kit slug URL          → identifiant de fichier lisible (« accueil », « edition-2026 »…)
"""
import csv
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

UA = os.environ.get("KIT_UA", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                              "Chrome/154.0 Safari/537.36 kit-audit-web")
EXTENSIONS_RESSOURCES = re.compile(
    r"\.(jpe?g|png|gif|webp|avif|svg|ico|bmp|tiff?|pdf|zip|gz|mp[34]|m4a|mov|avi|webm|ogg|wav|"
    r"css|js|json|xml|txt|woff2?|ttf|otf|eot|docx?|xlsx?|pptx?|odt|ods)$", re.I)


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


def lire_csv(chemin):
    """Lit un CSV (UTF-8 avec ou sans BOM) en liste de dictionnaires ; liste vide si absent."""
    if not os.path.exists(chemin):
        return []
    with open(chemin, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def colonne(ligne, *noms):
    """Valeur de la première colonne présente parmi noms (exports Screaming Frog en français ou en anglais)."""
    for n in noms:
        if n in ligne:
            return ligne[n]
    return ""


def lire_liste(chemin):
    """Lignes non vides et non commentées d'un fichier texte."""
    with open(chemin, encoding="utf-8") as f:
        return [l.strip() for l in f if l.strip() and not l.startswith("#")]


def _principal(argv):
    commandes = {"url": normaliser_url, "domaine": domaine, "slug": slug}
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
