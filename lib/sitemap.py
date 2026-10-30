# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Lecture des sitemaps d'un site (robots.txt, index de sitemaps, fichiers .gz).

  python3 -m sitemap pages URL                 → URL des pages déclarées (ressources exclues)
  python3 -m sitemap images URL                → URL des images déclarées (balises image:loc)
  python3 -m sitemap sources URL               → fichiers sitemap trouvés
  python3 -m sitemap types URL N [LISTE]       → N pages types : l'accueil, les pages les moins profondes
                                                 et une page profonde (article), tirées de LISTE ou du sitemap
"""
import gzip
import sys
import urllib.parse
import xml.etree.ElementTree as ET

from kit import est_page, lire_liste, meme_site, normaliser_url, recuperer

CANDIDATS = ("/sitemap.xml", "/sitemap_index.xml", "/wp-sitemap.xml", "/sitemap-index.xml")


def _racine(url):
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def trouver_sitemaps(url):
    """Sitemaps annoncés dans robots.txt, sinon premier emplacement usuel qui répond en XML."""
    racine = _racine(url)
    statut, _, corps, _ = recuperer(racine + "/robots.txt")
    annonces = []
    if statut == 200:
        for ligne in corps.decode("utf-8", "replace").splitlines():
            if ligne.lower().startswith("sitemap:"):
                annonces.append(ligne.split(":", 1)[1].strip())
    if annonces:
        return list(dict.fromkeys(annonces))
    for chemin in CANDIDATS:
        statut, _, corps, _ = recuperer(racine + chemin)
        if statut == 200 and b"<" in corps[:200] and (b"urlset" in corps or b"sitemapindex" in corps):
            return [racine + chemin]
    return []


def _xml(url):
    statut, _, corps, _ = recuperer(url, delai=60)
    if statut != 200 or not corps:
        return None
    if url.endswith(".gz") or corps[:2] == b"\x1f\x8b":
        corps = gzip.decompress(corps)
    try:
        return ET.fromstring(corps)
    except ET.ParseError:
        return None


def parcourir(url, vus=None):
    """Renvoie (pages, images) de tous les sitemaps atteignables depuis url."""
    vus = vus if vus is not None else set()
    pages, images = [], []
    if url in vus or len(vus) > 500:
        return pages, images
    vus.add(url)
    racine = _xml(url)
    if racine is None:
        return pages, images
    nom = racine.tag.rsplit("}", 1)[-1]
    for el in racine.iter():
        balise = el.tag.rsplit("}", 1)[-1]
        if balise == "loc" and el.text:
            loc = el.text.strip()
            if nom == "sitemapindex":
                p, i = parcourir(loc, vus)
                pages += p
                images += i
            elif "image" in el.tag:  # image:loc (espace de noms des images)
                images.append(loc)
            else:
                pages.append(loc)
    return pages, images


def tout(url):
    pages, images = [], []
    vus = set()
    for s in trouver_sitemaps(url):
        p, i = parcourir(s, vus)
        pages += p
        images += i
    pages = [p for p in dict.fromkeys(pages) if est_page(p) and meme_site(p, url)]
    return pages, list(dict.fromkeys(images)), sorted(vus)


def pages_types(url, n, pages):
    """L'accueil, les pages les moins profondes, et une page profonde s'il y en a."""
    accueil = normaliser_url(url)
    # l'accueil, avec ou sans www, n'est pris qu'une fois ; les doublons de la liste sont écartés
    est_accueil = lambda u: meme_site(u, accueil) and urllib.parse.urlsplit(normaliser_url(u)).path.strip("/") == "" \
        and not urllib.parse.urlsplit(u).query
    autres = list(dict.fromkeys(p for p in pages if not est_accueil(p)))
    profondeur = lambda u: len([s for s in urllib.parse.urlsplit(u).path.split("/") if s])
    triees = sorted(autres, key=lambda u: (profondeur(u), autres.index(u)))
    choix = triees[: max(n - 2, 0)]
    profondes = [u for u in triees if profondeur(u) >= 2 and u not in choix]
    choix += profondes[:1] if profondes else triees[len(choix): len(choix) + 1]
    return [accueil] + choix[: n - 1]


def _principal(argv):
    if len(argv) < 3 or argv[1] not in ("pages", "images", "sources", "types"):
        print(__doc__, file=sys.stderr)
        return 2
    url = normaliser_url(argv[2])
    if argv[1] == "types":
        n = int(argv[3]) if len(argv) > 3 else 6
        pages = lire_liste(argv[4]) if len(argv) > 4 else tout(url)[0]
        sortie = pages_types(url, n, pages)
    else:
        pages, images, sources = tout(url)
        sortie = {"pages": pages, "images": images, "sources": sources}[argv[1]]
    if sortie:
        print("\n".join(sortie))
    return 0


if __name__ == "__main__":
    sys.exit(_principal(sys.argv))
