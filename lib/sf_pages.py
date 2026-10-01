"""Outils pour enchaîner les crawls Screaming Frog (version gratuite plafonnée à 500 URL).

  python3 -m sf_pages liste URL SITEMAP.txt CRAWL_DIR [CRAWL_DIR…]
      → toutes les pages HTML internes connues : pages HTML des crawls, cibles des liens
        internes entrants et sortants (hyperliens et canoniques) et pages du sitemap,
        sans les exclusions de config/exclusions_pages.txt
  python3 -m sf_pages fusionner DESTINATION LOT1 LOT2 …
      → concatène les CSV de même nom des lots (en-tête conservé une seule fois)
  python3 -m sf_pages plafond CRAWL_DIR
      → affiche le nombre d'URL du crawl (pour signaler le plafond de 500)

Les exports sont lus en français ou en anglais (« Adresse »/« Address », etc.).
"""
import csv
import os
import re
import sys
import urllib.parse
from pathlib import Path

from kit import colonne, est_page, lire_csv, lire_liste, meme_site

RACINE = Path(__file__).resolve().parents[1]
TYPES_LIENS = {"hyperlien", "hyperlink", "canonique html", "html canonical"}


def exclusions():
    return [re.compile(m) for m in lire_liste(RACINE / "config/exclusions_pages.txt")]


def nettoyer(url):
    p = urllib.parse.urlsplit(url.strip())
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))


def liste(site, sitemap, crawls):
    candidats = []
    for crawl in map(Path, crawls):
        for l in lire_csv(crawl / "interne_tous.csv") or lire_csv(crawl / "internal_all.csv"):
            if "html" in colonne(l, "Type de contenu", "Content Type").lower():
                candidats.append(colonne(l, "Adresse", "Address"))
        for nom_fr, nom_en in (("liens_entrants_tous.csv", "all_inlinks.csv"), ("tous_les_liens_sortants.csv", "all_outlinks.csv")):
            for l in lire_csv(crawl / nom_fr) or lire_csv(crawl / nom_en):
                if colonne(l, "Type").strip().lower() in TYPES_LIENS:
                    candidats.append(colonne(l, "Destination"))
    if sitemap and os.path.exists(sitemap):
        candidats += lire_liste(sitemap)
    regles = exclusions()
    retenues = []
    for u in candidats:
        if not u or not meme_site(u, site) or not est_page(u):
            continue
        u = nettoyer(u)
        if not any(r.search(u) for r in regles):
            retenues.append(u)
    return sorted(dict.fromkeys(retenues))


def fusionner(destination, lots):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    noms = sorted({f.name for lot in lots for f in Path(lot).glob("*.csv")})
    for nom in noms:
        entete, lignes = None, []
        for lot in lots:
            f = Path(lot) / nom
            if not f.exists():
                continue
            with open(f, newline="", encoding="utf-8-sig") as fh:
                r = csv.reader(fh)
                tete = next(r, None)
                if tete is None:
                    continue
                entete = entete or tete
                # les fichiers de synthèse (aperçu) ne se concatènent pas : on garde le premier lot
                if nom.startswith(("aperçu", "rapport_aperçu", "crawl_overview", "issues_overview")) and lignes:
                    continue
                lignes += list(r)
        if entete:
            with open(destination / nom, "w", newline="", encoding="utf-8-sig") as fh:
                w = csv.writer(fh)
                w.writerow(entete)
                w.writerows(lignes)
    return len(noms)


def plafond(crawl):
    lignes = lire_csv(Path(crawl) / "interne_tous.csv") or lire_csv(Path(crawl) / "internal_all.csv")
    externes = lire_csv(Path(crawl) / "externe_tous.csv") or lire_csv(Path(crawl) / "external_all.csv")
    return len(lignes) + len(externes)


def _principal(argv):
    if len(argv) < 3 or argv[1] not in ("liste", "fusionner", "plafond"):
        print(__doc__, file=sys.stderr)
        return 2
    if argv[1] == "liste":
        pages = liste(argv[2], argv[3], argv[4:])
        if pages:
            print("\n".join(pages))
    elif argv[1] == "fusionner":
        print(f"{fusionner(argv[2], argv[3:])} fichiers fusionnés", file=sys.stderr)
    else:
        print(plafond(argv[2]))
    return 0


if __name__ == "__main__":
    sys.exit(_principal(sys.argv))
