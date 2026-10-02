# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Analyse SEO avec advertools : robots.txt, sitemaps, crawl complet (Scrapy, sans plafond) et contrôles.

  python3 -m seo_advertools URL DOSSIER [MAX_PAGES]

Sorties dans DOSSIER : crawl.jsonl, robots.csv, sitemap.csv, pages.csv (une ligne par page),
problemes.csv (une ligne par problème), resume.json ; et ../urls_html_advertools.txt.
Seuils usuels : title 30 à 65 caractères, meta description 70 à 160, au moins 250 mots, profondeur ≤ 3 clics.
"""
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

import advertools as adv
import pandas as pd

from kit import UA, lire_liste, meme_site

RACINE = Path(__file__).resolve().parents[1]
SEP = "@@"
TITRE = (30, 65)
DESCRIPTION = (70, 160)
MOTS_MIN = 250
PROFONDEUR_MAX = 3


def normaliser(u):
    p = urllib.parse.urlsplit(str(u).strip())
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))


def morceaux(v):
    return [] if pd.isna(v) or v == "" else str(v).split(SEP)


def colonne(df, nom):
    """Colonne insensible à la casse (en-têtes de réponse), ou série vide."""
    for c in df.columns:
        if c.lower() == nom.lower():
            return df[c]
    return pd.Series([None] * len(df), index=df.index)


def crawler(url, dossier, max_pages):
    sortie = dossier / "crawl.jsonl"
    sortie.unlink(missing_ok=True)
    exclusions = "|".join(lire_liste(RACINE / "config/exclusions_pages.txt"))
    adv.crawl(url, str(sortie), follow_links=True, exclude_url_regex=exclusions or None, custom_settings={
        "USER_AGENT": UA, "ROBOTSTXT_OBEY": True, "CLOSESPIDER_PAGECOUNT": max_pages,
        "AUTOTHROTTLE_ENABLED": True, "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
        "CONCURRENT_REQUESTS_PER_DOMAIN": 4, "DOWNLOAD_DELAY": 0.25,
        "LOG_FILE": str(dossier / "scrapy.log"), "LOG_LEVEL": "INFO",
    })
    return pd.read_json(sortie, lines=True)


def principal(url, dossier, max_pages=2000):
    d = Path(dossier)
    d.mkdir(parents=True, exist_ok=True)
    racine = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))

    # robots.txt et sitemaps
    try:
        adv.robotstxt_to_df(racine + "/robots.txt").to_csv(d / "robots.csv", index=False)
    except Exception as e:  # noqa: BLE001 — robots.txt absent ou illisible
        print(f"robots.txt : {e}", file=sys.stderr)
    from sitemap import trouver_sitemaps
    cadres = []
    for s in trouver_sitemaps(url):
        try:
            cadres.append(adv.sitemap_to_df(s))
        except Exception as e:  # noqa: BLE001
            print(f"sitemap {s} : {e}", file=sys.stderr)
    sitemap = pd.concat(cadres, ignore_index=True) if cadres else pd.DataFrame(columns=["loc"])
    sitemap.to_csv(d / "sitemap.csv", index=False)
    urls_sitemap = {normaliser(u) for u in sitemap.get("loc", []) if isinstance(u, str) and "/wp-content/" not in u}

    # crawl
    df = crawler(url, d, max_pages)
    df["url_n"] = df["url"].map(normaliser)
    type_contenu = colonne(df, "resp_headers_Content-Type").fillna("").astype(str)
    html = df[type_contenu.str.contains("html") | df.get("title", pd.Series(dtype=str)).notna()].copy()

    # liens internes entrants
    entrants = Counter()
    for _, ligne in html.iterrows():
        for cible in set(morceaux(ligne.get("links_url"))):
            if meme_site(cible, url):
                entrants[normaliser(cible)] += 1

    robots_meta = colonne(html, "meta_robots").fillna("").astype(str) + " " + colonne(html, "resp_headers_X-Robots-Tag").fillna("").astype(str)
    pages, problemes = [], []
    for (i, l), robots in zip(html.iterrows(), robots_meta):
        titre = "" if pd.isna(l.get("title")) else str(l.get("title")).split(SEP)[0].strip()
        desc = "" if pd.isna(l.get("meta_desc")) else str(l.get("meta_desc")).split(SEP)[0].strip()
        h1 = [h for h in morceaux(l.get("h1")) if h.strip()]
        texte = "" if pd.isna(l.get("body_text")) else str(l.get("body_text"))
        mots = len(re.findall(r"\w+", texte))
        canonique = "" if pd.isna(l.get("canonical")) else str(l.get("canonical")).split(SEP)[0].strip()
        alts = morceaux(l.get("img_alt"))
        sources = morceaux(l.get("img_src"))
        sans_alt = sum(1 for a in alts if not a.strip()) if alts else (len(sources) if sources else 0)
        statut = int(l["status"]) if not pd.isna(l.get("status")) else 0
        profondeur = int(l["depth"]) if not pd.isna(l.get("depth")) else ""
        noindex = "noindex" in robots.lower()
        page = {"url": l["url"], "statut": statut, "profondeur": profondeur, "title": titre, "longueur_title": len(titre),
                "meta_description": desc, "longueur_description": len(desc), "nb_h1": len(h1), "h1": h1[0] if h1 else "",
                "canonique": canonique, "noindex": noindex, "mots": mots, "images": len(sources), "images_sans_alt": sans_alt,
                "liens_entrants": entrants.get(l["url_n"], 0), "dans_sitemap": l["url_n"] in urls_sitemap}
        pages.append(page)

        def ajouter(type_, detail=""):
            problemes.append({"url": l["url"], "probleme": type_, "detail": detail})

        if statut >= 400:
            ajouter(f"erreur {statut}")
            continue
        if not titre:
            ajouter("title absent")
        elif not TITRE[0] <= len(titre) <= TITRE[1]:
            ajouter("title trop court" if len(titre) < TITRE[0] else "title trop long", f"{len(titre)} caractères")
        if not desc:
            ajouter("meta description absente")
        elif not DESCRIPTION[0] <= len(desc) <= DESCRIPTION[1]:
            ajouter("meta description trop courte" if len(desc) < DESCRIPTION[0] else "meta description trop longue", f"{len(desc)} caractères")
        if not h1:
            ajouter("H1 absent")
        elif len(h1) > 1:
            ajouter("plusieurs H1", f"{len(h1)} H1")
        if mots < MOTS_MIN:
            ajouter("peu de texte", f"{mots} mots")
        if canonique and normaliser(urllib.parse.urljoin(l["url"], canonique)) != l["url_n"]:
            ajouter("canonique vers une autre adresse", canonique)
        if noindex:
            ajouter("exclue de l'indexation (noindex)")
        if sans_alt:
            ajouter("images sans texte alternatif (absent ou vide)", f"{sans_alt} image(s)")
        if isinstance(profondeur, int) and profondeur > PROFONDEUR_MAX:
            ajouter("page profonde", f"{profondeur} clics depuis l'accueil")
        if urls_sitemap and not page["dans_sitemap"] and not noindex:
            ajouter("absente du sitemap")

    pages_df = pd.DataFrame(pages)
    ok = pages_df[pages_df["statut"] == 200] if not pages_df.empty else pages_df
    for champ, nom in (("title", "title en double"), ("meta_description", "meta description en double")):
        valeurs = ok[ok[champ] != ""][champ]
        for valeur, n in valeurs.value_counts().items():
            if n > 1:
                for u in ok[ok[champ] == valeur]["url"]:
                    problemes.append({"url": u, "probleme": nom, "detail": f"{n} pages : « {valeur[:80]} »"})

    explorees = set(html["url_n"])
    accueil = normaliser(url)
    for u in sorted(urls_sitemap - explorees):
        problemes.append({"url": u, "probleme": "dans le sitemap mais non atteinte par les liens (orpheline ?)", "detail": ""})
    for p in pages:
        if p["liens_entrants"] == 0 and normaliser(p["url"]) != accueil and p["statut"] == 200:
            problemes.append({"url": p["url"], "probleme": "aucun lien interne entrant", "detail": ""})

    pages_df.to_csv(d / "pages.csv", index=False)
    pd.DataFrame(problemes, columns=["url", "probleme", "detail"]).to_csv(d / "problemes.csv", index=False)
    if not ok.empty:
        (d.parent / "urls_html_advertools.txt").write_text("\n".join(ok["url"]) + "\n", encoding="utf-8")
    resume = {
        "pages_html": len(pages), "codes": dict(Counter(str(p["statut"]) for p in pages)),
        "sitemap": len(urls_sitemap), "problemes": dict(Counter(p["probleme"] for p in problemes).most_common()),
        "mots_median": int(pages_df["mots"].median()) if not pages_df.empty else 0,
        "profondeur_max": int(pd.to_numeric(pages_df["profondeur"], errors="coerce").max()) if not pages_df.empty else 0,
        "plafond_atteint": len(df) >= max_pages,
    }
    (d / "resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{resume['pages_html']} page(s) HTML, {len(urls_sitemap)} dans le sitemap, {len(problemes)} problème(s)")
    for k, n in list(resume["problemes"].items())[:12]:
        print(f"  {n:>4}  {k}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(principal(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2000))
