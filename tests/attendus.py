# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Compare un audit du site témoin (tests/site-temoin) avec les défauts qu'on y a placés.

  python3 tests/attendus.py DOSSIER_AUDIT

Le danger visé n'est pas le plantage, qui se voit, mais l'outil mis à jour qui change son format
de sortie : le kit lirait alors « 0 problème » et le rapport paraîtrait propre. Chaque défaut
déterministe est donc exigé exactement ; les mesures qui varient (scores Lighthouse) ne sont
contrôlées que dans leur forme. Une règle d'accessibilité nouvelle est signalée sans faire échouer
le test (axe en ajoute à chaque version) ; une règle attendue qui disparaît le fait échouer.
Code de retour : 0 si tout est conforme, 1 sinon.
"""
import csv
import json
import subprocess
import sys
import urllib.parse
from collections import defaultdict
from pathlib import Path

from kit import lire_catalogue

OUTILS = ["entetes", "seo", "inventaire", "liens", "accessibilite", "lighthouse", "unlighthouse", "captures"]

# Constats SEO attendus : code → chemins des pages concernées (exactement)
LONGUE = "/rubrique-tres-longue/une-adresse-beaucoup-trop-longue-pour-etre-lue-partagee-ou-retenue-par-un-visiteur-ordinaire.html"
SEO = {
    "erreur-4xx": {"/page-absente.html", "/supprimee.html"},
    "erreur-5xx": {"/erreur-serveur"},
    "soft-404": {"/404-deguisee.html"},
    "meta-refresh": {"/refresh.html"},
    "reponse-lente": {"/lente.html"},
    "noindex": {"/mentions.html", "/x-robots.html"},
    "nofollow-meta": {LONGUE},
    "canonique-absente": {"/contact.html", "/404-deguisee.html"},
    "canonique-autre": {"/a-propos/", "/actualites.html?page=2"},
    "canonique-cassee": {"/canonique-cassee.html"},
    "absente-sitemap": {"/cgu.html", "/confidentialite.html", "/Infos_Pratiques.html", "/rafraichie.html", LONGUE},
    "sitemap-erreur": {"/ancienne-page", "/supprimee.html"},
    "sitemap-non-indexable": {"/a-propos/", "/mentions.html", "/canonique-cassee.html", "/x-robots.html"},
    "orpheline": {"/orpheline.html", "/orpheline2.html"},
    "profonde": {"/profond/4.html"},
    "liens-redirection": {"/"},
    "liens-nofollow": {"/"},
    "liens-sans-texte": {"/"},
    "liens-sans-protocole": {"/"},
    "title-absent": {"/actualites.html", "/actualites.html?page=2"},
    "title-court": {"/contact.html", "/404-deguisee.html"},
    "title-long": {"/profond/2.html"},
    "title-pixels": {"/a-propos/", "/orpheline.html"},
    "title-double": {"/cgu.html", "/confidentialite.html"},
    "description-absente": {"/contact.html", "/404-deguisee.html"},
    "description-courte": {LONGUE},
    "description-longue": {"/profond/2.html"},
    "description-pixels": {"/a-propos/"},
    "description-double": {"/cgu.html", "/confidentialite.html"},
    "h1-absent": {LONGUE},
    "h1-multiple": {"/a-propos/"},
    "h1-double": {"/cgu.html", "/confidentialite.html"},
    "h2-absent": {"/a-propos/", "/presque.html"},
    "h2-desordre": {"/actualites.html", "/actualites.html?page=2"},
    "contenu-double": {"/cgu.html", "/confidentialite.html"},
    "images-sans-alt": {"/"},
    "adresse-soulignement": {"/Infos_Pratiques.html"},
    "adresse-majuscules": {"/Infos_Pratiques.html"},
    "adresse-parametres": {"/actualites.html?page=2"},
    "adresse-longue": {LONGUE},
    "lang-absent": {"/actualites.html", "/actualites.html?page=2"},
    "viewport-absent": {"/lente.html"},
    "donnees-structurees-invalides": {"/lente.html"},
    "reperes-absents": {"/lente.html"},
}
# Pages indexables : seules à être contrôlées pour l'Open Graph et les données structurées. L'accueil a
# un balisage complet (JSON-LD en @graph), /profond/2.html des microdonnées.
INDEXABLES = {"/", "/404-deguisee.html", "/Infos_Pratiques.html", "/actualites.html", "/cgu.html", "/confidentialite.html",
              "/contact.html", "/lente.html", "/presque.html", "/rafraichie.html", LONGUE, "/orpheline.html", "/orpheline2.html",
              *(f"/profond/{n}.html" for n in range(1, 5))}
SEO["opengraph-incomplet"] = INDEXABLES - {"/"}
SEO["donnees-structurees-absentes"] = INDEXABLES - {"/", "/profond/2.html"}
SEMANTIQUE = {"/": ("Organization, WebSite", ""), "/profond/2.html": ("WebPage (microdonnées)", "og:title, og:description, og:image"),
              "/lente.html": ("", "viewport, og:title, og:description, og:image, données structurées, header, nav, footer")}
PAGES_200 = 23      # pages HTML en 200, reprises par les autres outils
SEO_RESUME = {"pages_html": 26, "pages_sitemap_seules": 3, "redirections": 3, "orphelines": 2, "profondeur_max": 4}
EXCLUES = ("replytocom", "/feed/", "wp-login")   # config/exclusions_pages.txt : jamais explorées ni auditées
# Règles axe attendues : règle → pages
AXE = {"image-alt": 1, "label": 1, "color-contrast": 1, "link-name": 1, "document-title": 2, "html-has-lang": 2,
       "meta-refresh": 1}


class Verification:
    def __init__(self, dossier):
        self.d = Path(dossier)
        self.erreurs, self.avertissements, self.controles = [], [], 0

    def exiger(self, condition, message):
        self.controles += 1
        if not condition:
            self.erreurs.append(message)
        return condition

    def lire_json(self, chemin):
        try:
            return json.loads((self.d / chemin).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.exiger(False, f"{chemin} absent ou illisible")
            return {}

    def lire_csv(self, chemin):
        f = self.d / chemin
        if not self.exiger(f.exists(), f"{chemin} absent"):
            return []
        with open(f, newline="", encoding="utf-8-sig") as e:
            return list(csv.DictReader(e))

    def manifeste(self):
        m = self.lire_json("manifeste.json")
        codes = {o["outil"]: o["code"] for o in m.get("outils", [])}
        for outil in OUTILS:
            self.exiger(codes.get(outil) == 0, f"{outil} : code {codes.get(outil, 'absent')} au lieu de 0")
        for nom in ("Lighthouse", "Unlighthouse", "pa11y-ci", "lychee", "advertools"):
            self.exiger(m.get("versions", {}).get(nom), f"version de {nom} absente du manifeste")

    def seo(self):
        r = self.lire_json("seo/resume.json")
        for cle, attendu in SEO_RESUME.items():
            self.exiger(r.get(cle) == attendu, f"seo : {cle} = {r.get(cle)} au lieu de {attendu}")
        trouves = defaultdict(set)
        for l in self.lire_csv("seo/problemes.csv"):
            p = urllib.parse.urlsplit(l["url"])
            trouves[l["code"]].add(p.path + ("?" + p.query if p.query else ""))
        for code, chemins in SEO.items():
            self.exiger(trouves.get(code, set()) == chemins,
                        f"seo : {code} sur {sorted(trouves.get(code, set()))} au lieu de {sorted(chemins)}")
        inattendus = set(trouves) - set(SEO) - {"entetes-securite", "peu-de-texte", "contenu-proche"}
        self.exiger(not inattendus, f"seo : constats inattendus {sorted(inattendus)}")
        jamais = set(lire_catalogue()) - set(trouves)   # le site témoin doit déclencher chaque contrôle du catalogue
        self.exiger(not jamais, f"seo : contrôles du catalogue jamais déclenchés sur le site témoin : {sorted(jamais)}")
        for p in self.lire_csv("seo/pages.csv"):
            self.exiger(not any(x in p["url"] for x in EXCLUES), f"seo : adresse exclue explorée : {p['url']}")
        # toutes les pages en 200 sauf la page de redirection meta refresh, qui n'est pas contrôlée plus avant
        self.exiger(len(trouves.get("entetes-securite", ())) == PAGES_200 - 1, f"seo : en-têtes de sécurité absents sur "
                    f"{len(trouves.get('entetes-securite', ()))} pages au lieu de {PAGES_200 - 1}")
        # pages indexables au texte presque identique (/a-propos/, canonisée vers l'accueil, est exclue)
        self.exiger({"/profond/1.html", "/profond/3.html", "/orpheline2.html"} <= trouves.get("contenu-proche", set()),
                    f"seo : rubrique profonde attendue parmi les contenus presque identiques ({sorted(trouves.get('contenu-proche', set()))})")
        # balisage page par page : une ligne par page en 200 contrôlée (toutes, sauf la page meta refresh)
        chemin = lambda u: (lambda p: p.path + ("?" + p.query if p.query else ""))(urllib.parse.urlsplit(u))
        sem = {chemin(l["url"]): l for l in self.lire_csv("seo/semantique.csv")}
        self.exiger(len(sem) == PAGES_200 - 1, f"seo : semantique.csv a {len(sem)} pages au lieu de {PAGES_200 - 1}")
        for chemin, (types, manquants) in SEMANTIQUE.items():
            l = sem.get(chemin, {})
            self.exiger((l.get("donnees_structurees", ""), l.get("manquants", "")) == (types, manquants),
                        f"seo : balisage de {chemin} : {l.get('donnees_structurees')!r}, manquants {l.get('manquants')!r} "
                        f"au lieu de {types!r}, {manquants!r}")
        liste = (self.d / "urls_html.txt").read_text(encoding="utf-8").split() if (self.d / "urls_html.txt").exists() else []
        accueil = (self.d / "site.txt").read_text(encoding="utf-8").strip() if (self.d / "site.txt").exists() else ""
        self.exiger(len(liste) == PAGES_200 and liste[:1] == [accueil],
                    f"urls_html.txt : {len(liste)} pages ({PAGES_200} attendues, l'accueil en premier)")

    def liens(self):
        r = self.lire_json("liens/resume.json")
        casses = {urllib.parse.urlsplit(l["lien"]).path for l in self.lire_csv("liens/liens_casses.csv")}
        self.exiger("/page-absente.html" in casses, f"liens : /page-absente.html absent des liens cassés ({sorted(casses)})")
        a_verifier = {urllib.parse.urlsplit(l["lien"]).path: l["famille"] for l in self.lire_csv("liens/a_verifier.csv")}
        # 429 : refus temporaire « à vérifier », pas un lien cassé ; défi par cookie : franchi grâce à la boîte à cookies
        self.exiger("/surcharge.xml" not in casses and "refus temporaire" in a_verifier.get("/surcharge.xml", ""),
                    f"liens : /surcharge.xml (429) devrait être un refus temporaire à vérifier ({a_verifier.get('/surcharge.xml')})")
        self.exiger("/defi.xml" not in casses and "/defi.xml" not in a_verifier, "liens : le défi par cookie de /defi.xml n'a pas été franchi")
        speciaux = [l["lien"] for l in self.lire_csv("liens/a_verifier.csv") if l["lien"].startswith(("tel:", "mailto:"))]
        self.exiger(not speciaux, f"liens : liens téléphone ou courriel classés à vérifier ({speciaux[:3]})")
        # la page de redirection meta refresh n'a aucun lien à vérifier
        self.exiger(r.get("pages_analysees") == PAGES_200 - 1, f"liens : {r.get('pages_analysees')} pages analysées au lieu de {PAGES_200 - 1}")
        self.exiger(r.get("redirections", 0) >= 2, f"liens : {r.get('redirections')} redirection(s) au lieu d'au moins 2")

    def accessibilite(self):
        r = self.lire_json("accessibilite/resume.json")
        lignes = self.lire_csv("accessibilite/regles.csv")
        regles = {l["regle"]: int(l["pages"]) for l in lignes if l["impact"] != "à vérifier"}
        # texte sur une image : axe ne peut pas trancher, le kit le range « à vérifier » et non en défaut
        self.exiger(any(l["regle"] == "color-contrast" and l["impact"] == "à vérifier" for l in lignes),
                    "accessibilité : le texte sur une image devrait être un contraste « à vérifier »")
        for regle, pages in AXE.items():
            self.exiger(regles.get(regle) == pages, f"accessibilité : {regle} sur {regles.get(regle, 0)} page(s) au lieu de {pages}")
        nouvelles = set(regles) - set(AXE)
        if nouvelles:
            self.avertissements.append(f"accessibilité : règles nouvelles (à examiner, sans échec) : {sorted(nouvelles)}")
        self.exiger(r.get("pages_en_echec") == 0, f"accessibilité : {r.get('pages_en_echec')} page(s) non testée(s)")
        self.exiger(r.get("pages_testees", 0) >= 19, f"accessibilité : {r.get('pages_testees')} pages testées seulement")

    def inventaire(self):
        r = self.lire_json("inventaire/resume.json")
        self.exiger(r.get("pages_analysees") == PAGES_200, f"inventaire : {r.get('pages_analysees')} pages au lieu de {PAGES_200}")
        self.exiger(r.get("sans_lang") == 2, f"inventaire : {r.get('sans_lang')} page(s) sans langue au lieu de 2")
        self.exiger(r.get("liens_ancre_vide", 0) >= 1, "inventaire : aucun lien sans texte relevé")

    def mesures(self):
        lignes = self.lire_csv("lighthouse/resume.csv")
        self.exiger(len(lignes) >= 6 and {l["strategie"] for l in lignes} == {"mobile", "desktop"},
                    f"lighthouse : {len(lignes)} mesures, stratégies {sorted({l['strategie'] for l in lignes})}")
        for l in lignes:
            for cle in ("perf", "acces", "bonnes_pratiques", "referencement"):
                ok = l.get(cle, "").isdigit() and 0 <= int(l[cle]) <= 100
                self.exiger(ok, f"lighthouse : {cle} = {l.get(cle)!r} pour {l.get('page')} {l.get('strategie')}")
        u = self.lire_csv("unlighthouse/resume.csv")
        self.exiger(len(u) == PAGES_200, f"unlighthouse : {len(u)} pages mesurées au lieu de {PAGES_200}")
        self.exiger(all(l.get("perf", "").isdigit() for l in u), "unlighthouse : score de performance manquant")
        for vue in ("accueil_ordinateur.png", "accueil_mobile.png"):
            f = self.d / "captures" / vue
            self.exiger(f.exists() and f.stat().st_size > 2000, f"captures : {vue} absente ou vide")

    def synthese(self):
        pdf = self.d / "synthese/synthese.pdf"
        if not self.exiger(pdf.exists() and pdf.stat().st_size > 20000, "synthèse : PDF absent ou vide"):
            return
        try:
            texte = subprocess.run(["pdftotext", "-layout", str(pdf), "-"], capture_output=True, text=True, check=True).stdout
        except (OSError, subprocess.CalledProcessError):
            self.avertissements.append("synthèse : pdftotext indisponible, texte du PDF non vérifié")
            return
        for titre in ("Vitesse d'affichage", "Référencement naturel", "Liens cassés", "Accessibilité",
                      "Sécurité, domaine et DNS", "Méthode et outils", "Canonique vers une page en erreur ou redirigée",
                      "Balisage sémantique", "Champs manquants, page par page", "Ergonomie sur téléphone",
                      "Zones à toucher assez grandes et espacées"):
            self.exiger(titre in texte, f"synthèse : « {titre} » absent du PDF")
        self.exiger("Erreur :" not in texte, "synthèse : une section a échoué (« Erreur : » dans le PDF)")
        self.exiger("Relevés incomplets" not in texte, "synthèse : relevés incomplets signalés sur le site témoin")
        v = self.lire_json("synthese/voyants.json")
        domaines = {x["domaine"] for x in v.get("voyants", []) if x.get("couleur") != "gris"}
        self.exiger({"Balisage sémantique", "Ergonomie"} <= domaines, f"synthèse : voyants {sorted(domaines)}")

    def lancer(self):
        for etape in (self.manifeste, self.seo, self.liens, self.accessibilite, self.inventaire, self.mesures, self.synthese):
            try:
                etape()
            except Exception as e:  # noqa: BLE001 — une donnée inattendue est une erreur du test, pas un plantage
                self.exiger(False, f"{etape.__name__} : {e!r}")
        for a in self.avertissements:
            print(f"ATTENTION  {a}")
        for e in self.erreurs:
            print(f"ÉCHEC      {e}")
        print(f"{self.controles - len(self.erreurs)}/{self.controles} contrôles conformes")
        return 1 if self.erreurs else 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(Verification(sys.argv[1]).lancer())
