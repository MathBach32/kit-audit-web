# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Exploration du site et contrôles SEO avec advertools (Scrapy).

  python3 -m seo_advertools URL DOSSIER [MAX_PAGES]

Le crawl suit les liens depuis l'accueil (respect de robots.txt, débit modéré), puis les pages du
sitemap qu'aucun lien n'atteint sont téléchargées à leur tour (orphelines). Les redirections ne sont
pas suivies en silence : chacune est enregistrée (code, destination), puis sa destination explorée.
Chaque constat porte un code du catalogue config/problemes.csv (libellé, catégorie, gravité,
explication, correction).

Sorties dans DOSSIER : crawl*.jsonl (une par passe), robots.csv, sitemap.csv, redirections.csv,
pages.csv (une ligne par page), liens.csv (liens internes), problemes.csv (une ligne par constat),
resume.json ; et ../urls_html.txt : pages HTML en 200, l'accueil d'abord puis par profondeur,
liste réutilisée par les autres commandes du kit.
"""
import hashlib
import json
import re
import sys
import urllib.parse
from collections import Counter, defaultdict, deque
from itertools import zip_longest
from pathlib import Path

import advertools as adv
import numpy as np
import pandas as pd

from entetes_resume import SECURITE
from kit import UA, est_page, largeur_px, lire_catalogue, lire_liste, meme_site, recuperer

RACINE = Path(__file__).resolve().parents[1]
SEP = "@@"
TITRE = (30, 65)                 # caractères
TITRE_PX = 561                   # largeur affichée par Google (Arial 20 px)
DESCRIPTION = (70, 160)
DESCRIPTION_PX = 985             # Arial 14 px
MOTS_MIN = 250
MOTS_H2 = 300                    # au-delà, un texte sans intertitre est signalé
PROFONDEUR_MAX = 3
LENTEUR_S = 1.5
ADRESSE_MAX = 115
PROCHE = 0.9                     # similarité (Jaccard sur des groupes de 5 mots) des contenus presque identiques
SOFT_404 = re.compile(r"\berreur\s*404\b|^\W*404\b|\bpage\s+(est\s+)?(introuvable|non\s+trouv|inexistante)"
                      r"|cette page n[’']existe (plus|pas)|\b(page\s+)?not\s+found\b", re.I)
XPATH = {
    "meta_robots": "//meta[translate(@name,'ROBTS','robts')='robots']/@content",
    "meta_refresh": "//meta[translate(@http-equiv,'REFSH','refsh')='refresh']/@content",
    "titres_avant_h2": "count((//h2)[1]/preceding::*[self::h3 or self::h4 or self::h5 or self::h6])",
    "liens_sans_texte": "count(//a[@href][not(normalize-space(string(.)))][not(.//img[normalize-space(@alt)])]"
                        "[not(normalize-space(@aria-label))][not(normalize-space(@title))])",
    "images_sans_alt": "count(//img[not(@alt)])",
    # adresses commençant par // ; les indications de connexion (dns-prefetch, preconnect) n'en chargent rien
    "sans_protocole": "count(//*[starts-with(normalize-space(@href),'//') or starts-with(normalize-space(@src),'//')]"
                      "[not(self::link[contains(concat(' ',translate(normalize-space(@rel),'DNSPRFTCO','dnsprftco'),' '),' dns-prefetch ')"
                      " or contains(concat(' ',translate(normalize-space(@rel),'DNSPRFTCO','dnsprftco'),' '),' preconnect ')])])",
    "texte_principal": "normalize-space(string((//main|//article|//*[@role='main'])[1]))",
}


def normaliser(u):
    p = urllib.parse.urlsplit(str(u).strip())
    return urllib.parse.urlunsplit((p.scheme, p.netloc.lower(), p.path or "/", p.query, ""))


def morceaux(v):
    return [] if v is None or (not isinstance(v, str) and pd.isna(v)) or v == "" else str(v).split(SEP)


def premier(v):
    m = morceaux(v)
    return m[0].strip() if m else ""


def nombre(v):
    try:
        return int(float(premier(v) or 0))
    except ValueError:
        return 0


def entier(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return 0


def directives(*valeurs):
    """Mots des directives robots (balise meta et en-tête X-Robots-Tag), en minuscules."""
    return {m for v in valeurs for m in re.split(r"[\s,]+", str(v or "").lower()) if m}


def colonne(df, nom):
    """Colonne insensible à la casse (en-têtes de réponse), ou série vide."""
    for c in df.columns:
        if c.lower() == nom.lower():
            return df[c]
    return pd.Series([None] * len(df), index=df.index, dtype=object)


def domaines_autorises(url):
    """Hôte sans port (Scrapy compare les noms d'hôte), avec et sans www."""
    hote = urllib.parse.urlsplit(url).hostname or ""
    racine = hote[4:] if hote.startswith("www.") else hote
    return sorted({hote, racine, "www." + racine})


def exclusions():
    """Expression des adresses à ne pas traiter comme des pages (config/exclusions_pages.txt)."""
    return "|".join(lire_liste(RACINE / "config/exclusions_pages.txt"))


def cible_refresh(contenu, page):
    """Adresse vers laquelle une balise meta refresh redirige, ou "" pour un simple rechargement."""
    m = re.match(r"\s*[\d.]*\s*[;,]?\s*(?:url\s*=\s*)?(['\"]?)(.*?)\1\s*$", contenu or "", re.I | re.S)
    brut = m.group(2).strip() if m else ""
    if not brut:
        return ""
    cible = normaliser(urllib.parse.urljoin(page, brut))
    return "" if cible == normaliser(page) else cible


def crawler(urls, sortie, dossier, max_pages, suivre):
    sortie.unlink(missing_ok=True)
    adv.crawl(urls, str(sortie), follow_links=suivre, allowed_domains=domaines_autorises(urls[0]),
              exclude_url_regex=exclusions() or None, xpath_selectors=XPATH, custom_settings={
                  "USER_AGENT": UA, "ROBOTSTXT_OBEY": True, "CLOSESPIDER_PAGECOUNT": max_pages,
                  "AUTOTHROTTLE_ENABLED": True, "AUTOTHROTTLE_TARGET_CONCURRENCY": 2.0,
                  "CONCURRENT_REQUESTS_PER_DOMAIN": 4, "DOWNLOAD_DELAY": 0.25,
                  "REDIRECT_ENABLED": False, "METAREFRESH_ENABLED": False,
                  "LOG_FILE": str(dossier / "scrapy.log"), "LOG_LEVEL": "INFO",
              })
    if not sortie.exists() or sortie.stat().st_size == 0:
        return pd.DataFrame()
    return pd.read_json(sortie, lines=True)


def sitemap_et_robots(racine, depart, d):
    try:
        adv.robotstxt_to_df(racine + "/robots.txt").to_csv(d / "robots.csv", index=False)
    except Exception as e:  # noqa: BLE001 — robots.txt absent ou illisible
        print(f"robots.txt : {e}", file=sys.stderr)
    from sitemap import trouver_sitemaps
    cadres = []
    for s in trouver_sitemaps(depart):
        try:
            cadres.append(adv.sitemap_to_df(s))
        except Exception as e:  # noqa: BLE001
            print(f"sitemap {s} : {e}", file=sys.stderr)
    sitemap = pd.concat(cadres, ignore_index=True) if cadres else pd.DataFrame(columns=["loc"])
    sitemap.to_csv(d / "sitemap.csv", index=False)
    locs = [u for u in sitemap.get("loc", []) if isinstance(u, str) and est_page(u) and meme_site(u, depart)]
    return list(dict.fromkeys(normaliser(u) for u in locs))


def bardeaux(texte):
    mots = re.findall(r"\w+", texte.lower())
    return {hash(" ".join(mots[i:i + 5])) & 0x7FFFFFFF for i in range(max(len(mots) - 4, 0))}


def contenus_proches(textes, seuil=PROCHE):
    """Paires de pages au contenu presque identique : MinHash (64 valeurs) et LSH (16 bandes de 4),
    puis similarité de Jaccard exacte des candidats. textes : url → texte. Renvoie {(u, v): similarité}."""
    p, rng = (1 << 31) - 1, np.random.default_rng(32)
    a, b = rng.integers(1, p, 64, dtype=np.uint64), rng.integers(0, p, 64, dtype=np.uint64)
    ensembles, seaux = {}, defaultdict(set)
    for u, texte in textes.items():
        s = bardeaux(texte)
        if len(s) < 20:  # trop peu de texte pour comparer utilement
            continue
        ensembles[u] = s
        x = np.fromiter(s, dtype=np.uint64)
        signature = ((a[:, None] * x[None, :] + b[:, None]) % p).min(axis=1)
        for bande in range(16):
            seaux[(bande, signature[bande * 4:(bande + 1) * 4].tobytes())].add(u)
    paires = {}
    for groupe in seaux.values():
        groupe = sorted(groupe)
        for i, u in enumerate(groupe):
            for v in groupe[i + 1:]:
                if (u, v) not in paires:
                    su, sv = ensembles[u], ensembles[v]
                    paires[(u, v)] = len(su & sv) / len(su | sv)
    return {k: j for k, j in paires.items() if j >= seuil}


def canonique_de(ligne):
    """Canonique déclarée dans la page, sinon dans l'en-tête HTTP Link."""
    c = premier(ligne.get("canonical"))
    if not c:
        lien = ligne.get("_entete_link") or ""
        m = re.search(r'<([^>]+)>\s*;[^,]*rel="?canonical', str(lien), re.I)
        c = m.group(1) if m else ""
    return c


def principal(url, dossier, max_pages=2000):
    d = Path(dossier)
    d.mkdir(parents=True, exist_ok=True)
    catalogue = lire_catalogue()
    resume = {"site": url}

    def terminer(erreur):
        resume["erreur"] = erreur
        for f in ("pages.csv", "liens.csv", "problemes.csv"):
            (d / f).write_text("", encoding="utf-8")
        (d / "resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"ERREUR : {erreur}", file=sys.stderr)
        return 1

    # Adresse de départ réelle (l'accueil peut rediriger vers www, https ou un autre domaine)
    statut, finale, _, _ = recuperer(url)
    if not statut:
        return terminer(f"le site ne répond pas ({url}).")
    depart = normaliser(finale)
    if depart != normaliser(url):
        resume["redirection_depart"] = depart
        print(f"l'accueil redirige vers {depart} : exploration depuis cette adresse")
    accueil = depart
    racine = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(depart))
    urls_sitemap = sitemap_et_robots(racine, depart, d)
    dans_sitemap = set(urls_sitemap)

    # Passe 1 : liens depuis l'accueil ; puis destinations des redirections (en suivant leurs
    # liens) ; enfin pages du sitemap qu'aucun lien n'atteint
    cadres, vus, non_explorees = [], set(), {}
    # advertools n'applique les exclusions qu'aux liens suivis, pas aux adresses de départ d'une passe
    exclue = re.compile(exclusions() or r"(?!)")

    def passe(urls, nom, source, suivre):
        budget = max_pages - sum(len(c) for c in cadres)
        urls = [u for u in urls if u not in vus and (u == depart or not exclue.search(u))]
        if urls and budget <= 0:
            non_explorees[source] = len(urls)
        urls = urls[:budget]
        if not urls or budget <= 0:
            return False
        c = crawler(urls, d / f"{nom}.jsonl", d, budget, suivre)
        if c.empty:
            return False
        c["source"], c["url_n"] = source, c["url"].map(normaliser)
        cadres.append(c)
        vus.update(c["url_n"])
        return True

    passe([depart], "crawl", "liens", True)
    if not cadres:
        return terminer("aucune page explorée : vérifier l'adresse, robots.txt (Disallow) et le journal seo/scrapy.log.")
    redirige = {}
    for tour in range(1, 6):
        destinations = []
        for c in cadres:
            for un, code, cible in zip(c["url_n"], c["status"], colonne(c, "resp_headers_Location")):
                if 300 <= entier(code) < 400 and isinstance(cible, str) and cible:
                    redirige[un] = normaliser(urllib.parse.urljoin(un, cible))
                    destinations.append(redirige[un])
        destinations = [u for u in dict.fromkeys(destinations) if meme_site(u, depart) and est_page(u)]
        if not passe(destinations, f"crawl_redirections_{tour}", "liens", True):
            break
    passe(urls_sitemap, "crawl_sitemap", "sitemap", False)
    df = pd.concat(cadres, ignore_index=True).drop_duplicates("url_n").reset_index(drop=True)
    resume["plafond_atteint"] = len(df) >= max_pages
    if non_explorees.get("sitemap"):
        resume["sitemap_non_explorees"] = non_explorees["sitemap"]
    df["_entete_link"] = colonne(df, "resp_headers_Link")

    # Redirections (chaînes résolues) et statut de chaque adresse connue
    def finale_de(u):
        etapes = 0
        while u in redirige and etapes < 10:
            u, etapes = redirige[u], etapes + 1
        return u
    statuts = dict(zip(df["url_n"], df["status"].fillna(0).astype(int)))
    redirections = [{"adresse": u, "code": statuts.get(u, ""), "vers": v, "destination_finale": finale_de(u),
                     "code_final": statuts.get(finale_de(u), "")} for u, v in redirige.items()]
    pd.DataFrame(redirections, columns=["adresse", "code", "vers", "destination_finale", "code_final"]).to_csv(
        d / "redirections.csv", index=False)
    type_contenu = colonne(df, "resp_headers_Content-Type").fillna("").astype(str)
    est_redirection = df["status"].fillna(0).astype(int).between(300, 399)
    html = df[~est_redirection & (type_contenu.str.contains("html") | colonne(df, "title").notna())].copy()
    if html.empty:
        return terminer("aucune page HTML parmi les adresses explorées.")

    # Graphe des liens internes (pages en 200), sans les liens d'une page vers elle-même
    liens, sortants, nofollow, vers_redirection = [], {}, Counter(), Counter()
    for _, l in html.iterrows():
        if entier(l.get("status")) != 200:
            continue
        cibles = set()
        for cible, texte, nf in zip_longest(morceaux(l.get("links_url")), morceaux(l.get("links_text")),
                                            morceaux(l.get("links_nofollow")), fillvalue=""):
            if not cible or not meme_site(cible, depart) or not est_page(cible):
                continue
            c = normaliser(cible)
            if c in redirige:
                vers_redirection[l["url_n"]] += 1
            c = finale_de(c)
            if c == l["url_n"]:
                continue
            nofollow[l["url_n"]] += nf == "True"
            cibles.add(c)
            liens.append({"source": l["url"], "cible": c, "texte": texte.strip(), "nofollow": nf == "True"})
        sortants[l["url_n"]] = cibles
    entrants = Counter(c for cibles in sortants.values() for c in cibles)
    profondeur, file = {accueil: 0}, deque([accueil])
    while file:
        u = file.popleft()
        for c in sortants.get(u, ()):
            if c not in profondeur:
                profondeur[c] = profondeur[u] + 1
                file.append(c)

    entetes = {nom: colonne(html, "resp_headers_" + nom).fillna("").astype(str) for nom in [*SECURITE, "x-robots-tag"]}
    pages, problemes = [], []

    def ajouter(u, code, detail=""):
        e = catalogue[code]
        problemes.append({"url": u, "code": code, "probleme": e["libelle"], "detail": detail,
                          "categorie": e["categorie"], "gravite": e["gravite"]})

    for ordre, (_, l) in enumerate(html.iterrows()):
        u, un = l["url"], l["url_n"]
        statut = entier(l.get("status"))
        titre, desc = premier(l.get("title")), premier(l.get("meta_desc"))
        h1 = [h.strip() for h in morceaux(l.get("h1")) if h.strip()]
        h2 = [h.strip() for h in morceaux(l.get("h2")) if h.strip()]
        texte = "" if pd.isna(l.get("body_text")) else str(l.get("body_text"))
        mots = len(re.findall(r"\w+", texte))
        robots = directives(premier(l.get("meta_robots")), entetes["x-robots-tag"][l.name])
        noindex, refresh = bool(robots & {"noindex", "none"}), cible_refresh(premier(l.get("meta_refresh")), u)
        canonique = canonique_de(l)
        canonique_n = normaliser(urllib.parse.urljoin(u, canonique)) if canonique else ""
        canonique_ailleurs = bool(canonique_n) and canonique_n != un
        indexable = statut == 200 and not noindex and not refresh and not canonique_ailleurs
        raison = ("" if indexable else f"code {statut}" if statut != 200 else "noindex" if noindex
                  else "meta refresh" if refresh else "canonique ailleurs")
        latence = float(l.get("download_latency") or 0)
        page = {"url": u, "source": l["source"], "statut": statut, "indexable": indexable, "raison_non_indexable": raison,
                "profondeur": profondeur.get(un, ""), "title": titre, "longueur_title": len(titre),
                "largeur_title_px": largeur_px(titre, 20), "meta_description": desc, "longueur_description": len(desc),
                "largeur_description_px": largeur_px(desc, 14), "nb_h1": len(h1), "h1": h1[0] if h1 else "",
                "nb_h2": len(h2), "canonique": canonique, "noindex": noindex, "mots": mots,
                "images": len(morceaux(l.get("img_src"))), "images_sans_alt": nombre(l.get("images_sans_alt")),
                "liens_entrants": entrants.get(un, 0), "liens_internes_sortants": len(sortants.get(un, ())),
                "dans_sitemap": un in dans_sitemap, "temps_reponse_s": round(latence, 2),
                "taille_ko": round(float(l.get("size") or 0) / 1024, 1), "_ordre": ordre, "_n": un,
                "_texte": premier(l.get("texte_principal")) or texte}
        pages.append(page)

        if statut >= 400:
            ajouter(u, "erreur-5xx" if statut >= 500 else "erreur-4xx", f"code {statut}")
            continue
        if statut != 200:
            continue
        if refresh:  # page de redirection : les autres contrôles n'ont pas de sens
            ajouter(u, "meta-refresh", f"vers {refresh} ({premier(l.get('meta_refresh'))})")
            continue
        if SOFT_404.search(titre) or (h1 and SOFT_404.search(h1[0])):
            ajouter(u, "soft-404", titre or h1[0])
        if latence > LENTEUR_S:
            ajouter(u, "reponse-lente", f"{latence:.2f} s".replace(".", ","))
        if noindex:
            ajouter(u, "noindex", ", ".join(sorted(robots)))
        if robots & {"nofollow", "none"}:
            ajouter(u, "nofollow-meta", ", ".join(sorted(robots)))
        if not canonique and not noindex:
            ajouter(u, "canonique-absente")
        elif canonique_ailleurs:
            if canonique_n in redirige or statuts.get(canonique_n, 200) != 200:
                ajouter(u, "canonique-cassee", canonique)
            else:
                ajouter(u, "canonique-autre", canonique)
        if not titre:
            ajouter(u, "title-absent")
        elif page["largeur_title_px"] > TITRE_PX:  # la largeur décide de la coupure ; la longueur n'est qu'un repère
            ajouter(u, "title-pixels", f"{page['largeur_title_px']} px, {len(titre)} caractères")
        elif len(titre) < TITRE[0]:
            ajouter(u, "title-court", f"{len(titre)} caractères")
        elif len(titre) > TITRE[1]:
            ajouter(u, "title-long", f"{len(titre)} caractères")
        if not desc:
            ajouter(u, "description-absente")
        elif page["largeur_description_px"] > DESCRIPTION_PX:
            ajouter(u, "description-pixels", f"{page['largeur_description_px']} px, {len(desc)} caractères")
        elif len(desc) < DESCRIPTION[0]:
            ajouter(u, "description-courte", f"{len(desc)} caractères")
        elif len(desc) > DESCRIPTION[1]:
            ajouter(u, "description-longue", f"{len(desc)} caractères")
        if not h1:
            ajouter(u, "h1-absent")
        elif len(h1) > 1:
            ajouter(u, "h1-multiple", f"{len(h1)} H1")
        if not h2 and mots >= MOTS_H2:
            ajouter(u, "h2-absent", f"{mots} mots")
        if h2 and nombre(l.get("titres_avant_h2")):
            ajouter(u, "h2-desordre", f"{nombre(l.get('titres_avant_h2'))} intertitre(s) avant le premier H2")
        if mots < MOTS_MIN:
            ajouter(u, "peu-de-texte", f"{mots} mots")
        if page["images_sans_alt"]:
            ajouter(u, "images-sans-alt", f"{page['images_sans_alt']} image(s)")
        if nombre(l.get("liens_sans_texte")):
            ajouter(u, "liens-sans-texte", f"{nombre(l.get('liens_sans_texte'))} lien(s)")
        if nofollow[un]:
            ajouter(u, "liens-nofollow", f"{nofollow[un]} lien(s)")
        if vers_redirection[un]:
            ajouter(u, "liens-redirection", f"{vers_redirection[un]} lien(s)")
        if nombre(l.get("sans_protocole")):
            ajouter(u, "liens-sans-protocole", f"{nombre(l.get('sans_protocole'))} adresse(s)")
        if un != accueil and not isinstance(page["profondeur"], int):  # aucun chemin de liens depuis l'accueil
            ajouter(u, "orpheline", (f"liée seulement depuis d'autres pages orphelines ({entrants[un]} lien(s))" if entrants.get(un)
                                     else "aucun lien interne") + (", trouvée par le sitemap" if l["source"] == "sitemap" else ""))
        elif isinstance(page["profondeur"], int) and page["profondeur"] > PROFONDEUR_MAX:
            ajouter(u, "profonde", f"{page['profondeur']} clics depuis l'accueil")
        if urls_sitemap and indexable and un not in dans_sitemap:
            ajouter(u, "absente-sitemap")
        absents = [nom for nom in SECURITE if not entetes[nom][l.name].strip()
                   and not (nom == "strict-transport-security" and not u.startswith("https://"))]
        if "frame-ancestors" in entetes["content-security-policy"][l.name] and "x-frame-options" in absents:
            absents.remove("x-frame-options")
        if absents:
            ajouter(u, "entetes-securite", ", ".join(absents))
        chemin = urllib.parse.unquote(urllib.parse.urlsplit(u).path)
        if "_" in chemin:
            ajouter(u, "adresse-soulignement", chemin)
        if chemin != chemin.lower():
            ajouter(u, "adresse-majuscules", chemin)
        if urllib.parse.urlsplit(u).query:
            ajouter(u, "adresse-parametres", urllib.parse.urlsplit(u).query)
        if len(u) > ADRESSE_MAX:
            ajouter(u, "adresse-longue", f"{len(u)} caractères")

    # Doublons entre pages indexables
    indexables = [p for p in pages if p["indexable"]]
    for champ, code in (("title", "title-double"), ("meta_description", "description-double"), ("h1", "h1-double")):
        groupes = defaultdict(list)
        for p in indexables:
            if p[champ]:
                groupes[p[champ].casefold()].append(p)
        for groupe in groupes.values():
            if len(groupe) > 1:
                for p in groupe:
                    ajouter(p["url"], code, f"{len(groupe)} pages : « {p[champ][:80]} »")
    empreintes = defaultdict(list)
    for p in indexables:
        normal = " ".join(re.findall(r"\w+", p["_texte"].lower()))
        if len(normal.split()) >= 50:
            empreintes[hashlib.md5(normal.encode()).hexdigest()].append(p)
    identiques = set()
    for groupe in empreintes.values():
        if len(groupe) > 1:
            for p in groupe:
                identiques.add(p["_n"])
                autre = next(q for q in groupe if q is not p)
                ajouter(p["url"], "contenu-double", f"comme {autre['url']}" + (f" et {len(groupe) - 2} autre(s)" if len(groupe) > 2 else ""))
    meilleur = {}
    textes = {p["_n"]: p["_texte"] for p in indexables if p["_n"] not in identiques}
    for (a, b), j in contenus_proches(textes).items():
        for x, y in ((a, b), (b, a)):
            if j > meilleur.get(x, (0, ""))[0]:
                meilleur[x] = (j, y)
    par_n = {p["_n"]: p for p in pages}
    for x, (j, y) in meilleur.items():
        ajouter(par_n[x]["url"], "contenu-proche", f"{round(j * 100)} % commun avec {par_n[y]['url']}")

    # Hygiène du sitemap
    for un in urls_sitemap:
        if un in redirige:
            ajouter(un, "sitemap-erreur", f"redirigée ({statuts.get(un, '3xx')}) vers {finale_de(un)}")
        elif un in statuts and statuts[un] != 200:
            ajouter(un, "sitemap-erreur", f"code {statuts[un]}")
        elif un in par_n and par_n[un]["statut"] == 200 and not par_n[un]["indexable"]:
            ajouter(un, "sitemap-non-indexable", par_n[un]["raison_non_indexable"])

    # Sorties
    rang = lambda p: (p["profondeur"] if isinstance(p["profondeur"], int) else 10**6, p["_ordre"])
    pages.sort(key=rang)
    pages_df = pd.DataFrame(pages).drop(columns=["_ordre", "_n", "_texte"])
    pages_df.to_csv(d / "pages.csv", index=False)
    pd.DataFrame(liens, columns=["source", "cible", "texte", "nofollow"]).to_csv(d / "liens.csv", index=False)
    cols = ["url", "code", "probleme", "detail", "categorie", "gravite"]
    pd.DataFrame(problemes, columns=cols).to_csv(d / "problemes.csv", index=False)
    en_200 = [p["url"] for p in pages if p["statut"] == 200]
    (d.parent / "urls_html.txt").write_text("\n".join(en_200) + "\n", encoding="utf-8")
    pages_par_code = defaultdict(set)
    for pb in problemes:
        pages_par_code[pb["code"]].add(normaliser(pb["url"]))
    profondeurs = [p["profondeur"] for p in pages if isinstance(p["profondeur"], int)]
    par_gravite = defaultdict(set)
    for pb in problemes:
        par_gravite[pb["gravite"]].add(normaliser(pb["url"]))
    resume.update({
        "site": depart, "pages_html": len(pages), "pages_explorees": sum(p["source"] == "liens" for p in pages),
        "pages_sitemap_seules": sum(p["source"] == "sitemap" for p in pages),
        "pages_indexables": len(indexables), "codes": dict(Counter(str(p["statut"]) for p in pages)),
        "redirections": len(redirige),
        "sitemap": len(urls_sitemap), "orphelines": len(pages_par_code.get("orpheline", ())),
        "mots_median": int(pages_df["mots"].median()), "profondeur_max": max(profondeurs, default=0),
        "problemes": {c: len(v) for c, v in sorted(pages_par_code.items(), key=lambda kv: -len(kv[1]))},
        "pages_par_gravite": {g: len(par_gravite.get(g, ())) for g in ("haute", "moyenne", "basse")},
        "constats": len(problemes), "liens_internes": len(liens),
    })
    (d / "resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{resume['pages_html']} page(s) HTML ({resume['pages_sitemap_seules']} trouvée(s) seulement par le sitemap), "
          f"{resume['pages_indexables']} indexable(s), {len(urls_sitemap)} dans le sitemap, {len(problemes)} constat(s)")
    for code, n in list(resume["problemes"].items())[:15]:
        print(f"  {n:>4}  {catalogue[code]['libelle']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(principal(sys.argv[1], sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 2000))
