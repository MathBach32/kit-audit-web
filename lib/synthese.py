# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Synthèse automatique d'un audit : HTML puis PDF (navigateur sans interface : Google Chrome ou Chromium).

  python3 -m synthese DOSSIER_AUDIT   → DOSSIER_AUDIT/synthese/synthese.html et synthese.pdf

Lit les résultats présents ; un outil non exécuté est signalé sans bloquer. Le document est
factuel : chiffres, constats automatiques et voyants indicatifs, sans recommandations rédigées.
"""
import datetime as dt
import html
import json
import re
import subprocess
import sys
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path

from kit import colonne, lire_csv, navigateur, sans_navigateur

RACINE = Path(__file__).resolve().parents[1]
CHROME = navigateur()  # CHROME_PATH (défini par lib/commun.sh), sinon Google Chrome ou Chromium détecté
MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre", "novembre", "décembre"]
OUTILS = {  # sous-dossier → libellé
    "entetes": "En-têtes, TLS, DNS, domaine", "sf": "Screaming Frog SEO Spider", "seo": "advertools (SEO)",
    "inventaire": "Inventaire des contenus", "liens": "lychee (liens)", "accessibilite": "pa11y-ci + axe (accessibilité)",
    "lighthouse": "Lighthouse local", "psi": "PageSpeed Insights", "unlighthouse": "Unlighthouse", "captures": "Captures d'écran",
}


def t(v):
    """Texte échappé pour le HTML."""
    return html.escape("" if v is None else str(v), quote=True)


def virgule(v, n=1):
    try:
        return f"{float(v):.{n}f}".replace(".", ",")
    except (TypeError, ValueError):
        return "–"


def date_fr(iso):
    try:
        d = dt.date.fromisoformat(iso[:10])
    except ValueError:
        return iso
    return f"{'1er' if d.day == 1 else d.day} {MOIS[d.month - 1]} {d.year}"


def chemin_court(url):
    p = urllib.parse.urlsplit(url)
    return (p.path or "/") + ("?" + p.query if p.query else "")


def lire_json(chemin):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def tableau(entetes, lignes, classe="compact"):
    """entetes : liste de libellés (préfixe « # » pour une colonne numérique alignée à droite)."""
    tete = "".join(f'<th class="num">{t(h[1:])}</th>' if h.startswith("#") else f"<th>{t(h)}</th>" for h in entetes)
    corps = []
    for l in lignes:
        cellules = []
        for h, v in zip(entetes, l):
            brut = v[1] if isinstance(v, tuple) else t(v)  # (« html », valeur) pour du HTML déjà construit
            cellules.append(f'<td class="num">{brut}</td>' if h.startswith("#") else f"<td>{brut}</td>")
        corps.append("<tr>" + "".join(cellules) + "</tr>")
    entete = f"<thead><tr>{tete}</tr></thead>" if any(entetes) else ""
    return f'<table class="{classe}">{entete}<tbody>{"".join(corps)}</tbody></table>'


def pastille(classe, texte):
    return ("html", f'<span class="grav {classe}">{t(texte)}</span>')


def couleur_score(s):
    try:
        s = float(s)
    except (TypeError, ValueError):
        return ""
    return "vert" if s >= 90 else "jaune" if s >= 50 else "rouge"


def typographie(texte):
    """Espaces insécables de la typographie française, hors balises, <style> et <svg>."""
    blocs = re.split(r"(<style.*?</style>|<svg.*?</svg>)", texte, flags=re.S)
    for i, b in enumerate(blocs):
        if b.startswith(("<style", "<svg")):
            continue
        morceaux = re.split(r"(<[^>]+>)", b)
        for j, m in enumerate(morceaux):
            if m.startswith("<") or not m.strip():
                continue
            m = re.sub(r" ([:])", "\u00a0\\1", m)
            m = re.sub(r" ([;!?])", "\u202f\\1", m)
            m = m.replace("« ", "«\u00a0").replace(" »", "\u00a0»")
            m = re.sub(r"(\d) (€|Mo|Ko|Go|ko|s|ms|%|px|h|min|jours?)(?!\w)", "\\1\u00a0\\2", m)
            morceaux[j] = m
        blocs[i] = "".join(morceaux)
    return "".join(blocs)


class Synthese:
    def __init__(self, dossier):
        self.d = Path(dossier)
        self.site = (self.d / "site.txt").read_text(encoding="utf-8").strip() if (self.d / "site.txt").exists() else ""
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.d.name):
            self.date = self.d.name
        else:  # dossier imposé par --dossier : date de création de site.txt, au début des relevés
            repere = self.d / "site.txt"
            jour = dt.date.fromtimestamp(repere.stat().st_mtime) if repere.exists() else dt.date.today()
            self.date = jour.isoformat()
        try:
            self.chemin = str(self.d.resolve().relative_to(RACINE))
        except ValueError:
            self.chemin = self.d.name
        self.voyants, self.chiffres, self.sections, self.absents = [], [], [], []

    def present(self, outil):
        ok = (self.d / outil).is_dir() and any((self.d / outil).iterdir())
        if not ok:
            self.absents.append(OUTILS.get(outil, outil))
        return ok

    def voyant(self, domaine, couleur, texte):
        etats = {"vert": "Bon état", "orange": "À surveiller", "rouge": "À traiter", "gris": "Non mesuré"}
        self.voyants.append((domaine, couleur, etats[couleur], texte))

    def chiffre(self, valeur, libelle):
        self.chiffres.append((valeur, libelle))

    def section(self, titre, contenu):
        self.sections.append((titre, contenu))

    # --- Performance -----------------------------------------------------------------------------
    def performance(self):
        parties, perf_mobile, lcp_mobile = [], [], []
        for outil, nom in (("psi", "PageSpeed Insights (Lighthouse chez Google)"), ("lighthouse", "Lighthouse local (navigateur du poste)")):
            lignes = lire_csv(self.d / outil / "resume.csv")
            if not lignes:
                continue
            par_page = defaultdict(dict)
            for l in lignes:
                par_page[l["url"] or l["page"]][l["strategie"]] = l
            rangees = []
            for url, s in par_page.items():
                m, o = s.get("mobile", {}), s.get("desktop", {})
                rangees.append([chemin_court(url)] + [pastille(couleur_score(m.get(k)), m.get(k, "–")) if m.get(k) else "–"
                                                      for k in ("perf", "acces", "bonnes_pratiques", "referencement")]
                               + [f"{virgule(m.get('lcp_s'))} s" if m.get("lcp_s") else "–",
                                  pastille(couleur_score(o.get("perf")), o.get("perf", "–")) if o.get("perf") else "–",
                                  f"{virgule(o.get('lcp_s'))} s" if o.get("lcp_s") else "–"])
            if not perf_mobile:
                perf_mobile = [float(l["perf"]) for l in lignes if l["strategie"] == "mobile" and l["perf"]]
                lcp_mobile = [float(l["lcp_s"]) for l in lignes if l["strategie"] == "mobile" and l["lcp_s"]]
            parties.append(f"<h3>{t(nom)}</h3>" + tableau(
                ["Page", "#Perf.", "#Acc.", "#B. p.", "#Réf.", "#LCP", "#Perf. ord.", "#LCP ord."], rangees))
            terrain = [l for l in lignes if l.get("terrain_lcp_ms") and l["strategie"] == "mobile"]
            if outil == "psi":
                if terrain:
                    parties.append("<p>Données de vrais visiteurs (Chrome, 28 derniers jours) :</p>" + tableau(
                        ["Page", "#LCP réel", "#INP réel", "#CLS réel", "Portée"],
                        [[chemin_court(l["url"]), f"{virgule(int(l['terrain_lcp_ms']) / 1000)} s", f"{l['terrain_inp_ms']} ms",
                          l["terrain_cls"], l["terrain_origine"]] for l in terrain]))
                else:
                    parties.append('<p class="petit">Google ne publie aucune donnée de vrais visiteurs pour ce site '
                                   "(trafic insuffisant) : les mesures ci-dessus sont des simulations.</p>")
        u = lire_json(self.d / "unlighthouse/resume.json")
        if u:
            lignes = sorted(lire_csv(self.d / "unlighthouse/resume.csv"), key=lambda l: -float(l["lcp_s"] or 0))
            m = u["moyennes"]
            parties.append(f"<h3>Unlighthouse : toutes les pages ({u['pages']})</h3>"
                           f"<p>Moyennes mobiles : performance {m.get('performance', '–')}, accessibilité {m.get('accessibility', '–')}, "
                           f"bonnes pratiques {m.get('best-practices', '–')}, référencement {m.get('seo', '–')} ; "
                           f"LCP moyen {virgule(u.get('lcp_moyen_s'))} s. Les 10 pages les plus lentes :</p>"
                           + tableau(["Page", "#Perf.", "#LCP", "#CLS", "#TBT"],
                                     [[l["chemin"], pastille(couleur_score(l["perf"]), l["perf"]), f"{virgule(l['lcp_s'])} s",
                                       l["cls"], f"{l['tbt_ms']} ms"] for l in lignes[:10]]))
            if not perf_mobile:
                perf_mobile, lcp_mobile = [m.get("performance", 0)], [u.get("lcp_moyen_s") or 0]
        for o in ("psi", "lighthouse", "unlighthouse"):
            self.present(o)
        if not parties:
            self.voyant("Vitesse", "gris", "Aucune mesure de performance.")
            return
        p, lcp = sum(perf_mobile) / len(perf_mobile), sum(lcp_mobile) / max(len(lcp_mobile), 1)
        couleur = "vert" if p >= 90 and lcp <= 2.5 else "rouge" if p < 50 or lcp > 4 else "orange"
        self.voyant("Vitesse", couleur, f"Score mobile moyen {round(p)}/100, affichage du contenu principal (LCP) en {virgule(lcp)} s "
                                        "(objectif : 2,5 s).")
        self.chiffre(f"{round(p)}/100", "score de performance mobile moyen")
        self.chiffre(f"{virgule(lcp)} s", "LCP mobile moyen (objectif 2,5 s)")
        intro = ('<p class="petit">Scores sur 100 (90 et plus : bon ; 50 à 89 : moyen ; moins de 50 : mauvais). '
                 "LCP : temps d'affichage du plus gros élément visible, objectif 2,5 s sur téléphone. Perf. : performance, "
                 "Acc. : accessibilité, B. p. : bonnes pratiques, Réf. : référencement ; « ord. » : ordinateur.</p>")
        self.section("Vitesse d'affichage", intro + "".join(parties))

    # --- Référencement ---------------------------------------------------------------------------
    def referencement(self):
        parties = []
        seo = lire_json(self.d / "seo/resume.json") if self.present("seo") else None
        nb_pages = None
        if seo:
            nb_pages = seo["pages_html"]
            parties.append(f"<h3>Contrôles automatiques (advertools)</h3><p>{seo['pages_html']} pages HTML explorées en suivant les liens, "
                           f"{seo['sitemap']} pages déclarées dans le sitemap, texte médian de {seo['mots_median']} mots, "
                           f"profondeur maximale de {seo['profondeur_max']} clics depuis l'accueil.</p>"
                           + tableau(["Constat", "#Pages"], [[k, n] for k, n in seo["problemes"].items()]))
            if seo.get("plafond_atteint"):
                parties.append('<p class="petit">Le nombre maximal de pages explorées a été atteint : relancer bin/seo avec --max.</p>')
        if self.present("sf"):
            base = self.d / "sf/3-liste" if (self.d / "sf/3-liste/interne_tous.csv").exists() else self.d / "sf/1-crawl"
            interne = lire_csv(base / "interne_tous.csv") or lire_csv(base / "internal_all.csv")
            html_ = [l for l in interne if "html" in colonne(l, "Type de contenu", "Content Type").lower()]
            if html_:
                nb_pages = max(nb_pages or 0, len(html_))
                codes = Counter(colonne(l, "Code HTTP", "Status Code") for l in html_)
                index = Counter(colonne(l, "Indexabilité", "Indexability") for l in html_)
                parties.append(f"<h3>Screaming Frog : {len(html_)} pages HTML</h3><p>Codes de réponse : "
                               + ", ".join(f"{k} × {n}" for k, n in codes.most_common()) + ". Indexabilité : "
                               + ", ".join(f"{k.lower()} × {n}" for k, n in index.most_common()) + ".</p>")
            problemes = lire_csv(base / "rapport_aperçu_problemes.csv") or lire_csv(base / "issues_overview_report.csv")
            if problemes:
                problemes.sort(key=lambda l: -int(colonne(l, "URL", "URLs") or 0))
                parties.append(tableau(["Problème relevé par Screaming Frog", "Type", "Priorité", "#URL"],
                                       [[colonne(l, "Nom du problème", "Issue Name"), colonne(l, "Type de problème", "Issue Type"),
                                         colonne(l, "Priorité du problème", "Issue Priority"), colonne(l, "URL", "URLs")]
                                        for l in problemes[:25]]))
            if (self.d / "sf/3-liste/lots/lot-01.txt").exists():
                parties.append('<p class="petit">Passe 3 en plusieurs lots : le tableau des problèmes ne porte que sur le premier lot.</p>')
            apercu = (self.d / "sf/1-crawl/aperçu_du_crawl.csv")
            if apercu.exists() and re.search(r'"Total des URL rencontrées","500"', apercu.read_text(encoding="utf-8-sig")):
                parties.append('<p class="petit">Le crawl normal a atteint le plafond de 500 URL de la version gratuite ; '
                               "les données ci-dessus viennent du crawl en mode liste de toutes les pages connues.</p>")
        if nb_pages:
            self.chiffres.insert(0, (str(nb_pages), "pages HTML trouvées"))
        if not parties:
            self.voyant("Référencement", "gris", "Aucune analyse SEO.")
            return
        if seo:
            majeurs = sum(n for k, n in seo["problemes"].items()
                          if k.startswith(("erreur", "title absent", "H1 absent", "title en double", "meta description absente")))
            part = majeurs / max(seo["pages_html"], 1)
            couleur = "vert" if majeurs == 0 else "orange" if part < 0.2 else "rouge"
            self.voyant("Référencement", couleur, f"{majeurs} constat(s) majeur(s) (erreurs, titres absents ou en double, H1 absents, "
                                                 f"descriptions absentes) pour {seo['pages_html']} pages.")
        self.section("Référencement naturel", "".join(parties))

    # --- Liens -----------------------------------------------------------------------------------
    def liens(self):
        r = lire_json(self.d / "liens/resume.json") if self.present("liens") else None
        if not r:
            self.voyant("Liens", "gris", "Liens non vérifiés.")
            return
        casses = lire_csv(self.d / "liens/liens_casses.csv")
        par_lien = defaultdict(list)
        for c in casses:
            par_lien[(c["lien"], c["code"], c["detail"], c["interne"])].append(c["page"])
        rangees = [[("html", f'<a href="{t(l)}">{t(l[:110])}</a>'), code or "–", "interne" if interne == "True" else "externe",
                    len(pages), chemin_court(pages[0])]
                   for (l, code, detail, interne), pages in sorted(par_lien.items(), key=lambda kv: (kv[0][3] != "True", -len(kv[1])))]
        a_verifier = Counter(r.get("a_verifier_par_famille") or
                             {urllib.parse.urlsplit(c["lien"]).netloc: 1 for c in lire_csv(self.d / "liens/a_verifier.csv")})
        contenu = (f"<p>{r['liens_verifies']} liens vérifiés ({r['liens_uniques']} adresses différentes) sur {r['pages_analysees']} pages : "
                   f"<strong>{r['liens_casses']} liens cassés</strong>, dont {r['liens_casses_internes']} vers le site lui-même.</p>")
        if rangees:
            contenu += tableau(["Lien cassé", "Code", "Cible", "#Pages", "Première page"], rangees[:40])
            if len(rangees) > 40:
                contenu += f'<p class="petit">… et {len(rangees) - 40} autres : voir liens/liens_casses.csv.</p>'
        if a_verifier:
            contenu += ("<h3>À vérifier dans un navigateur</h3><p>Ces services bloquent les robots ; leurs liens n'ont pas été "
                        "vérifiés automatiquement (liste dans config/lychee.toml, détail dans liens/a_verifier.csv) :</p>"
                        + tableau(["Famille de liens", "#Adresses distinctes"], [[d, n] for d, n in a_verifier.most_common(20)]))
        couleur = "rouge" if r["liens_casses_internes"] else "orange" if r["liens_casses"] > 2 else "vert"
        self.voyant("Liens", couleur, f"{r['liens_casses']} lien(s) cassé(s) dont {r['liens_casses_internes']} interne(s) ; "
                                      f"{r['a_verifier_navigateur']} à vérifier à la main.")
        self.chiffre(str(r["liens_casses"]), "liens cassés (adresses distinctes)")
        self.section("Liens cassés", contenu)

    # --- Accessibilité ---------------------------------------------------------------------------
    def accessibilite(self):
        r = lire_json(self.d / "accessibilite/resume.json") if self.present("accessibilite") else None
        if not r:
            self.voyant("Accessibilité", "gris", "Accessibilité non testée.")
            return
        regles = lire_csv(self.d / "accessibilite/regles.csv")
        classes = {"critique": "critique", "grave": "grave", "modéré": "modere", "mineur": "mineur"}
        info = r["par_impact"].get("à vérifier", 0)
        contenu = (f"<p>{r['pages_testees']} pages testées avec axe (norme WCAG 2.1 AA) : {r['problemes'] - info} problèmes relevés"
                   + (f" et {info} contenus intégrés à vérifier" if info else "")
                   + f" ; {r['pages_sans_probleme']} pages sans problème détecté"
                   + (f", {r['pages_en_echec']} pages non testées (erreur)" if r["pages_en_echec"] else "") + ".</p>"
                   '<p class="petit">Un test automatique ne détecte qu\'une partie des difficultés : la navigation au clavier, '
                   "la lecture d'écran et la pertinence des textes alternatifs restent à vérifier à la main.</p>"
                   + tableau(["Règle", "Gravité", "#Pages", "#Occurrences", "Description"],
                             [[("html", f'<a href="{t(l["aide"])}">{t(l["regle"])}</a>'), pastille(classes.get(l["impact"], ""), l["impact"]),
                               l["pages"], l["occurrences"], l["description"]] for l in regles]))
        if r["par_impact"].get("à vérifier"):
            contenu += ('<p class="petit">« À vérifier » : contenus intégrés (vidéos, publicités, formulaires externes) '
                        "que le test n'a pas pu analyser ; ce n'est pas un défaut en soi.</p>")
        graves =r["par_impact"].get("critique", 0) + r["par_impact"].get("grave", 0)
        couleur = "vert" if graves == 0 else "rouge" if r["par_impact"].get("critique", 0) else "orange"
        self.voyant("Accessibilité", couleur, f"{graves} problème(s) critique(s) ou grave(s) selon axe, sur {r['pages_testees']} pages.")
        self.chiffre(str(graves), "problèmes d'accessibilité critiques ou graves")
        self.section("Accessibilité", contenu)

    # --- Sécurité et domaine ---------------------------------------------------------------------
    def securite(self):
        r = lire_json(self.d / "entetes/resume.json") if self.present("entetes") else None
        if not r:
            self.voyant("Sécurité", "gris", "En-têtes non relevés.")
            return
        sec = r["securite"]
        absents = [k for k, v in sec.items() if not v["present"]]
        rangees = [[k, pastille("vert" if v["present"] else "orange", "présent" if v["present"] else "absent"), v["role"]]
                   for k, v in sec.items()]
        variantes = [[u, v.get("code", "–"), v.get("redirections", "–"), chemin_court(v["finale"]) if "finale" in v and
                      urllib.parse.urlsplit(v["finale"]).netloc == urllib.parse.urlsplit(u).netloc else v.get("finale", "–")]
                     for u, v in r["variantes"].items()]
        c, dom, dns = r["certificat"], r["domaine"], r["dns"]
        http_ok = all(v.get("finale", "").startswith("https://") for u, v in r["variantes"].items() if u.startswith("http://"))
        fiche = [
            ["Certificat", f"{c['emetteur']} ; expire le {date_fr(c['expire_le'])} ({c['jours_restants']} jours)" if c["expire_le"] else "non lu"],
            ["Protocoles TLS", ", ".join(f"{k.replace('tls1_', 'TLS 1.')} {v}" for k, v in r["tls"].items())],
            ["Passage automatique en HTTPS", "oui" if http_ok else "NON : une variante http:// n'aboutit pas en https://"],
            ["Nom de domaine", f"{dom['bureau_enregistrement'] or '?'} ; créé le {date_fr(dom['cree_le'])} ; expire le {date_fr(dom['expire_le'])}"
             + (f" ({dom['jours_restants']} jours)" if "jours_restants" in dom else "")],
            ["Serveurs de noms", ", ".join(dns["ns"]) or "–"],
            ["Adresses IP", ", ".join(dns["a"] + dns["aaaa"]) or "–"],
            ["Courriel (MX)", ", ".join(dns["mx"]) or "aucun"],
            ["SPF / DMARC", f"{'présent' if dns['spf'] else 'absent'} / {dns['dmarc'] or 'absent'}"],
            ["DNSSEC / CAA", f"{'activé' if dns['dnssec'] else 'non activé'} / {', '.join(dns['caa']) or 'aucun'}"],
            ["Informations divulguées", ", ".join(f"{k} : {v}" for k, v in r["divulgation"].items()) or "aucune"],
            ["Fichiers publics", ", ".join(f"{k} ({v})" for k, v in r["fichiers_publics"].items())],
        ]
        contenu = ("<h3>En-têtes de sécurité de la page d'accueil</h3>" + tableau(["En-tête", "État", "Rôle"], rangees)
                   + "<h3>Certificat, domaine et DNS</h3>" + tableau(["", ""], fiche, "fiche")
                   + "<h3>Variantes d'adresse et adresses sensibles</h3>" + tableau(["Adresse testée", "#Code", "#Redir.", "Aboutit à"], variantes))
        jours = [x for x in (c.get("jours_restants"), dom.get("jours_restants")) if x is not None]
        couleur = "rouge" if not http_ok or (jours and min(jours) < 15) else "orange" if len(absents) >= 3 or (jours and min(jours) < 45) else "vert"
        self.voyant("Sécurité et domaine", couleur, f"{len(absents)} en-tête(s) de sécurité absent(s) sur {len(sec)} ; "
                                                    f"certificat valable {c['jours_restants']} jours ; domaine jusqu'au {date_fr(dom['expire_le'])}.")
        self.chiffre(f"{len(sec) - len(absents)}/{len(sec)}", "en-têtes de sécurité présents")
        self.section("Sécurité, domaine et DNS", contenu)

    # --- Contenus et médias ----------------------------------------------------------------------
    def contenus(self):
        r = lire_json(self.d / "inventaire/resume.json") if self.present("inventaire") else None
        if not r:
            return
        parties = []
        if "contenus" in r:
            c = r["contenus"]
            parties.append(f"<p>Le site compte {c['pages']} pages et {c['articles']} articles (API WordPress). "
                           f"Dernière modification : {date_fr(c['derniere_modification'])} ; plus ancienne : {date_fr(c['plus_ancienne_modification'])} ; "
                           f"{c['sans_texte']} contenus ont moins de 50 mots de texte.</p>")
        parties.append(tableau(["", ""], [
            ["Pages analysées", r["pages_analysees"]],
            ["Logiciel déclaré", ", ".join(r["generateurs"]) or "non déclaré"],
            ["Pages sans langue déclarée", r["sans_lang"]],
            ["Pages sans image d'aperçu de partage (og:image)", r["sans_og_image"]],
            ["Pages sans données structurées (JSON-LD)", r["sans_donnees_structurees"]],
            ["Liens internes / externes", f"{r['liens_internes']} / {r['liens_externes']}"],
            ["Liens sans texte (image seule ou vide)", r["liens_ancre_vide"]],
            ["Images (fichiers originaux)", f"{r['images']} images, {virgule(r['images_mo'])} Mo au total"],
            ["Vidéos YouTube / indisponibles", f"{r['videos']} / {r['videos_indisponibles']}"],
        ], "fiche"))
        if r["images_lourdes"]:
            parties.append("<h3>Images les plus lourdes</h3>" + tableau(
                ["Image", "#Poids"], [[("html", f'<a href="{t(i["url"])}">{t(chemin_court(i["url"])[-90:])}</a>'),
                                       f"{virgule(i['ko'] / 1024)} Mo" if i["ko"] >= 1024 else f"{i['ko']} Ko"] for i in r["images_lourdes"]]))
        indispo = [v for v in lire_csv(self.d / "inventaire/videos.csv") if v["statut_oembed"] != "200"]
        if indispo:
            parties.append("<h3>Vidéos indisponibles</h3>" + tableau(
                ["Page", "Vidéo", "Code"], [[chemin_court(v["page"]), v["video_id"], v["statut_oembed"]] for v in indispo]))
        self.section("Contenus et médias", "".join(parties))

    def captures(self):
        if not self.present("captures"):
            return
        figures = []
        for nom in ("accueil",):
            o, m = self.d / f"captures/{nom}_ordinateur.png", self.d / f"captures/{nom}_mobile.png"
            images = "".join(f'<img src="../captures/{f.name}" alt="Capture {t(f.stem)}">' for f in (o, m) if f.exists())
            if images:
                figures.append(f'<figure><div class="captures">{images}</div><figcaption>Page d\'accueil sur ordinateur '
                               "(1366 px) et sur téléphone (390 px).</figcaption></figure>")
        autres = sorted(p.stem.rsplit("_", 1)[0] for p in (self.d / "captures").glob("*_ordinateur.png") if not p.name.startswith("accueil_"))
        if autres:
            figures.append(f'<p class="petit">Autres captures dans captures/ : {t(", ".join(autres))}.</p>')
        if figures:
            self.section("Aperçu", "".join(figures))

    # --- Assemblage ------------------------------------------------------------------------------
    def annexe(self):
        m = lire_json(self.d / "manifeste.json")
        contenu = ""
        if m:
            contenu += tableau(["Outil", "État", "#Durée"], [[OUTILS.get(o["outil"], o["outil"]),
                               pastille("vert" if o["code"] == 0 else "rouge", "réussi" if o["code"] == 0 else f"échec ({o['code']})"),
                               f"{o['duree_s'] // 60} min {o['duree_s'] % 60:02d} s"] for o in m["outils"]])
            if m.get("versions"):
                contenu += "<p class=\"petit\">Versions : " + t(" ; ".join(f"{k} {v}" for k, v in m["versions"].items())) + ".</p>"
        if self.absents:
            contenu += f"<p>Non exécutés ou sans résultat : {t(', '.join(sorted(set(self.absents))))}.</p>"
        contenu += (f'<p class="petit">Données brutes : dossier {t(self.chemin)}. '
                    "Synthèse produite automatiquement par le kit d'audit web ; les voyants sont des indications calculées selon des seuils usuels, à interpréter.</p>")
        self.section("Méthode et outils", contenu)

    def html(self):
        for etape in (self.performance, self.referencement, self.liens, self.accessibilite, self.securite, self.contenus, self.captures):
            try:
                etape()
            except Exception as e:  # noqa: BLE001 — une donnée inattendue ne doit pas bloquer toute la synthèse
                self.section(f"Erreur : {etape.__name__}", f"<p>Section non produite : {t(repr(e))}</p>")
                print(f"section {etape.__name__} : {e!r}", file=sys.stderr)
        self.annexe()
        domaine = urllib.parse.urlsplit(self.site).netloc
        # commentaires retirés : les mentions de licence du gabarit n'ont pas à figurer dans les rapports
        style = re.sub(r"/\*.*?\*/", "", (RACINE / "gabarit/style.css").read_text(encoding="utf-8"), flags=re.S)
        style += f'\n@page {{ @bottom-left {{ content: "{domaine} — audit du {date_fr(self.date)}"; font: 7.5pt "Noto Sans", sans-serif; color: #898781; }} }}\n'
        voyants = "".join(f'<div class="voyant {c}"><div class="dom">{t(d)}</div><div class="etat">{t(e)}</div><p>{t(x)}</p></div>'
                          for d, c, e, x in self.voyants)
        chiffres = "".join(f'<div class="chiffre"><div class="val">{t(v)}</div><div class="lib">{t(l)}</div></div>' for v, l in self.chiffres[:8])
        sections = "".join(f'<section><h2><span class="num">{i}</span>{t(titre)}</h2>{contenu}</section>'
                           for i, (titre, contenu) in enumerate(self.sections, 1))
        return typographie(f"""<!doctype html>
<html lang="fr"><head><meta charset="utf-8"><title>Audit {t(domaine)} — {t(date_fr(self.date))}</title>
<style>{style}</style></head><body>
<div class="entete"><div class="surtitre">Audit technique du site</div><h1>{t(domaine)}</h1>
<div class="meta">{t(self.site)} · relevés du {t(date_fr(self.date))}</div></div>
<div class="encadre"><p>Cette synthèse rassemble les mesures automatiques du kit d'audit. Chaque voyant résume un domaine
selon des seuils usuels ; le détail et les données brutes suivent.</p></div>
<div class="voyants">{voyants}</div><div class="chiffres">{chiffres}</div>
{sections}
</body></html>""")


def principal(dossier):
    d = Path(dossier)
    s = Synthese(d)
    sortie = d / "synthese"
    sortie.mkdir(exist_ok=True)
    page = sortie / "synthese.html"
    page.write_text(s.html(), encoding="utf-8")
    pdf = sortie / "synthese.pdf"
    if not CHROME:
        print(f"{page} produit, PDF impossible : {sans_navigateur()}", file=sys.stderr)
        return 1
    subprocess.run([CHROME, "--headless=new", "--no-sandbox", "--no-pdf-header-footer", "--allow-file-access-from-files",
                    f"--print-to-pdf={pdf}", page.as_uri()], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"→ {page}\n→ {pdf}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(principal(sys.argv[1]))
