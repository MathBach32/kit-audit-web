# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Inventaire des contenus, pages, liens, médias et vidéos d'un site.

  python3 -m inventaire URL PAGES.txt DOSSIER

Sources : API WordPress quand le site en est un (WordPress.com : API publique v1.1 ; WordPress
installé : /wp-json/wp/v2), sitemaps et HTML des pages de PAGES.txt.
Sorties dans DOSSIER :
  contenus.csv     pages et articles (WordPress seulement) : titre, dates, nombre de mots, catégories
  pages_html.json  métadonnées extraites du HTML de chaque page (langue, title, Open Graph, titres…)
  liens.csv        tous les liens des pages (source, cible, ancre, rel, target) ; statuts : voir bin/liens
  medias.csv       images (sitemap et pages) avec leur poids
  videos.csv       vidéos YouTube intégrées ou liées et leur disponibilité (oEmbed)
  resume.json      chiffres clés pour la synthèse
"""
import concurrent.futures as cf
import csv
import html
import json
import re
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

from kit import domaine, lire_liste, meme_site, recuperer
from sitemap import tout as sitemap_tout


def ecrire_csv(chemin, lignes, champs):
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=champs, extrasaction="ignore")
        w.writeheader()
        w.writerows(lignes)


def texte_brut(contenu):
    t = re.sub(r"<[^>]+>", " ", contenu or "")
    return html.unescape(re.sub(r"\s+", " ", t)).strip()


# --- Contenus WordPress --------------------------------------------------------------------------

def contenus_wordpress_com(site):
    api = f"https://public-api.wordpress.com/rest/v1.1/sites/{site}"
    statut, _, corps, _ = recuperer(api + "/?fields=ID,name")
    if statut != 200 or b'"ID"' not in corps:
        return None
    contenus = []
    for type_ in ("page", "post"):
        page = 1
        while True:
            q = urllib.parse.urlencode({"type": type_, "number": 100, "page": page,
                                        "fields": "ID,URL,slug,title,date,modified,status,content,categories,parent"})
            _, _, corps, _ = recuperer(f"{api}/posts/?{q}")
            donnees = json.loads(corps or b"{}")
            for p in donnees.get("posts", []):
                contenus.append({
                    "type": type_, "id": p["ID"], "url": p["URL"].replace("http://", "https://"), "slug": p["slug"],
                    "titre": html.unescape(p["title"]), "publie": p["date"][:10], "modifie": p["modified"][:10],
                    "mots": len(texte_brut(p.get("content")).split()),
                    "categories": "|".join((p.get("categories") or {}).keys()),
                    "nb_images": (p.get("content") or "").count("<img"), "nb_iframes": (p.get("content") or "").count("<iframe"),
                })
            if not donnees.get("posts") or len([c for c in contenus if c["type"] == type_]) >= donnees.get("found", 0):
                break
            page += 1
    return contenus


def contenus_wordpress(racine):
    statut, _, _, _ = recuperer(racine + "/wp-json/wp/v2/types")
    if statut != 200:
        return None
    contenus = []
    for type_, route in (("page", "pages"), ("post", "posts")):
        page = 1
        while True:
            q = urllib.parse.urlencode({"per_page": 100, "page": page,
                                        "_fields": "id,link,slug,title,date,modified,status,content,categories"})
            statut, _, corps, entetes = recuperer(f"{racine}/wp-json/wp/v2/{route}?{q}")
            if statut != 200:
                break
            for p in json.loads(corps or b"[]"):
                contenu = (p.get("content") or {}).get("rendered", "")
                contenus.append({
                    "type": type_, "id": p["id"], "url": p["link"], "slug": p["slug"],
                    "titre": html.unescape((p.get("title") or {}).get("rendered", "")),
                    "publie": p["date"][:10], "modifie": p["modified"][:10], "mots": len(texte_brut(contenu).split()),
                    "categories": "|".join(map(str, p.get("categories") or [])),
                    "nb_images": contenu.count("<img"), "nb_iframes": contenu.count("<iframe"),
                })
            total = int({k.lower(): v for k, v in entetes.items()}.get("x-wp-totalpages", 1))
            if page >= total:
                break
            page += 1
    return contenus


# --- Analyse HTML --------------------------------------------------------------------------------

class AnalyseurPage(HTMLParser):
    """Extrait liens, images, iframes, balises meta et titres d'une page."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.liens, self.images, self.iframes, self.meta, self.titres = [], [], [], {}, []
        self.lang, self.title, self.jsonld = None, "", 0
        self._dans_title, self._a, self._h = False, None, None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "html":
            self.lang = a.get("lang")
        elif tag == "title":
            self._dans_title = True
        elif tag == "meta":
            cle = a.get("property") or a.get("name")
            if cle:
                self.meta[cle.lower()] = a.get("content", "")
        elif tag == "a" and a.get("href"):
            self._a = {"href": a["href"], "texte": "", "rel": a.get("rel", ""), "target": a.get("target", "")}
        elif tag == "img":
            self.images.append({"src": a.get("src") or a.get("data-src") or "", "alt": a.get("alt"),
                                "largeur": a.get("width"), "hauteur": a.get("height"), "loading": a.get("loading")})
        elif tag == "iframe":
            self.iframes.append(a.get("src") or a.get("data-src") or "")
        elif tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._h = [tag, ""]
        elif tag == "script" and a.get("type") == "application/ld+json":
            self.jsonld += 1

    def handle_endtag(self, tag):
        if tag == "title":
            self._dans_title = False
        elif tag == "a" and self._a:
            self._a["texte"] = re.sub(r"\s+", " ", self._a["texte"]).strip()
            self.liens.append(self._a)
            self._a = None
        elif self._h and tag == self._h[0]:
            self.titres.append((self._h[0], re.sub(r"\s+", " ", self._h[1]).strip()))
            self._h = None

    def handle_data(self, data):
        if self._dans_title:
            self.title += data
        if self._a is not None:
            self._a["texte"] += data
        if self._h is not None:
            self._h[1] += data


def absolue(href, page):
    href = html.unescape(href.strip())
    if href.startswith(("mailto:", "tel:", "javascript:", "#", "data:")):
        return href
    return urllib.parse.urljoin(page, href).split("#")[0]


def analyser(url):
    statut, finale, corps, _ = recuperer(url)
    p = AnalyseurPage()
    p.feed(corps.decode("utf-8", "replace") if statut else "")
    return url, statut, finale, len(corps) if statut else 0, p


# --- Programme principal -------------------------------------------------------------------------

def principal(url, fichier_pages, dossier):
    d = Path(dossier)
    racine = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))
    resume = {}

    contenus = contenus_wordpress_com(domaine(url)) or contenus_wordpress(racine) or []
    if contenus:
        ecrire_csv(d / "contenus.csv", contenus, list(contenus[0].keys()))
        dates = sorted(c["modifie"] for c in contenus)
        resume["contenus"] = {"pages": sum(c["type"] == "page" for c in contenus), "articles": sum(c["type"] == "post" for c in contenus),
                              "derniere_modification": dates[-1], "plus_ancienne_modification": dates[0],
                              "sans_texte": sum(c["mots"] < 50 for c in contenus)}
    print(f"contenus WordPress : {len(contenus) if contenus else 'API non disponible (site non WordPress ?)'}")

    pages_sm, images_sm, _ = sitemap_tout(url)
    pages = lire_liste(fichier_pages)
    infos, liens, images = {}, [], {}
    with cf.ThreadPoolExecutor(4) as ex:
        for u, statut, finale, poids, p in ex.map(analyser, pages):
            infos[u] = {"statut": statut, "url_finale": finale, "lang": p.lang, "title": html.unescape(p.title.strip()),
                        "meta_description": p.meta.get("description"), "og_title": p.meta.get("og:title"),
                        "og_image": p.meta.get("og:image"), "og_description": p.meta.get("og:description"),
                        "twitter_card": p.meta.get("twitter:card"), "robots": p.meta.get("robots"),
                        "generateur": p.meta.get("generator"), "jsonld": p.jsonld, "titres": p.titres, "iframes": p.iframes,
                        "images": p.images, "nb_liens": len(p.liens), "poids_html": poids}
            for a in p.liens:
                cible = absolue(a["href"], u)
                liens.append({"source": u, "cible": cible, "interne": meme_site(cible, url), "ancre": a["texte"][:120],
                              "rel": a["rel"], "target": a["target"]})
            for img in p.images:
                if img["src"] and not img["src"].startswith("data:"):
                    images.setdefault(absolue(img["src"], u).split("?")[0], u)
    (d / "pages_html.json").write_text(json.dumps(infos, ensure_ascii=False, indent=1), encoding="utf-8")
    ecrire_csv(d / "liens.csv", liens, ["source", "cible", "interne", "ancre", "rel", "target"])
    print(f"pages analysées : {len(infos)} ; liens : {len(liens)}")

    for i in images_sm:
        images.setdefault(i.split("?")[0], "sitemap")

    def taille(u):
        statut, _, _, h = recuperer(u, "HEAD", delai=20)
        h = {k.lower(): v for k, v in h.items()}
        return u, statut, int(h.get("content-length") or 0), h.get("content-type", "")

    medias = []
    with cf.ThreadPoolExecutor(8) as ex:
        for u, statut, octets, type_ in ex.map(taille, sorted(images)):
            medias.append({"url": u, "statut": statut, "octets": octets, "type": type_, "premiere_page": images[u]})
    ecrire_csv(d / "medias.csv", medias, ["url", "statut", "octets", "type", "premiere_page"])
    total = sum(m["octets"] for m in medias)
    print(f"images : {len(medias)}, {total / 1e6:.1f} Mo")

    videos = set()
    for u, info in infos.items():
        for src in info["iframes"]:
            m = re.search(r"youtube(?:-nocookie)?\.com/embed/([\w-]{11})", src)
            if m:
                videos.add((u, m.group(1)))
    for l in liens:
        m = re.search(r"(?:youtube\.com/(?:watch\?v=|shorts/)|youtu\.be/)([\w-]{11})", l["cible"])
        if m:
            videos.add((l["source"], m.group(1)))
    lignes_videos = []
    for page, vid in sorted(videos):
        q = urllib.parse.quote(f"https://www.youtube.com/watch?v={vid}", safe="")
        statut, _, corps, _ = recuperer(f"https://www.youtube.com/oembed?url={q}&format=json")
        titre = json.loads(corps).get("title", "") if statut == 200 else ""
        lignes_videos.append({"page": page, "video_id": vid, "statut_oembed": statut, "titre": titre})
    ecrire_csv(d / "videos.csv", lignes_videos, ["page", "video_id", "statut_oembed", "titre"])
    print(f"vidéos YouTube : {len(videos)}")

    ok = [i for i in infos.values() if i["statut"] == 200]
    resume.update({
        "pages_analysees": len(infos), "pages_sitemap": len(pages_sm),
        "sans_lang": sum(not i["lang"] for i in ok), "sans_og_image": sum(not i["og_image"] for i in ok),
        "sans_donnees_structurees": sum(i["jsonld"] == 0 for i in ok),
        "generateurs": sorted({i["generateur"] for i in ok if i["generateur"]}),
        "liens_internes": sum(l["interne"] for l in liens), "liens_externes": sum(not l["interne"] and l["cible"].startswith("http") for l in liens),
        "liens_ancre_vide": sum(not l["ancre"] for l in liens if l["cible"].startswith("http")),
        "images": len(medias), "images_mo": round(total / 1e6, 1),
        "images_lourdes": [{"url": m["url"], "ko": round(m["octets"] / 1024)} for m in sorted(medias, key=lambda m: -m["octets"])[:10]],
        "videos": len(lignes_videos), "videos_indisponibles": sum(v["statut_oembed"] != 200 for v in lignes_videos),
    })
    (d / "resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 4:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(principal(*sys.argv[1:]))
