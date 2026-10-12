# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Résume le rapport JSON de lychee.

  python3 -m liens_resume DOSSIER URL
    DOSSIER/lychee.json → liens_casses.csv, a_verifier.csv, resume.json
  python3 -m liens_resume fusionner DOSSIER
    DOSSIER/par-page/*.json (vérification page par page) → DOSSIER/lychee.json
"""
import csv
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

from kit import meme_site

# Liens exclus de lychee qu'il n'y a pas lieu de vérifier à la main : vidéos YouTube (vérifiées
# par bin/inventaire, oEmbed), points d'accès techniques que lychee écarte de lui-même
# (xmlrpc.php) et liens qui ne mènent pas à une page web (téléphone, courriel, SMS, JavaScript).
NON_A_VERIFIER = re.compile(r"^https?://((www\.)?youtube(-nocookie)?\.com/(embed|watch|shorts)|youtu\.be/)|/xmlrpc\.php$"
                            r"|^(tel|mailto|sms|javascript|data):", re.I)
FAMILLES = [  # (motif, libellé) : regroupement lisible des liens « à vérifier dans un navigateur »
    (r"[?&]share=", "boutons de partage (?share=)"),
    (r"wordpress\.com/log-in", "connexion WordPress.com"),
    (r"(^|\.)(facebook\.com|fb\.me|fb\.com)$", "Facebook"),
    (r"(^|\.)instagram\.com$", "Instagram"),
    (r"(^|\.)linkedin\.com$", "LinkedIn"),
    (r"(^|\.)(twitter|x)\.com$", "X (Twitter)"),
    (r"(^|\.)helloasso\.com$", "HelloAsso"),
]


REFUS_TEMPORAIRE = "refus temporaire du serveur (protection anti-robots ou surcharge)"


def refus_temporaire(code):
    """Redirection non aboutie (défi par cookie ou boucle), 429 ou 503 : le serveur refuse pour
    l'instant de répondre au robot ; ce n'est pas la preuve d'un lien cassé."""
    try:
        code = int(code)
    except (TypeError, ValueError):
        return False
    return 300 <= code < 400 or code in (429, 503)


def famille(url):
    hote = urllib.parse.urlsplit(url).netloc.lower()
    for motif, libelle in FAMILLES:
        if re.search(motif, url if "/" in motif or "?" in motif else hote):
            return libelle
    return hote.removeprefix("www.")


def lignes(carte, site, nature):
    vues = set()
    for source, liens in (carte or {}).items():
        for l in liens:
            cle = (source, l["url"])
            if cle in vues:
                continue
            vues.add(cle)
            statut = l.get("status") or {}
            yield {"page": source, "lien": l["url"], "interne": meme_site(l["url"], site),
                   "code": statut.get("code", ""), "detail": statut.get("text", "").replace(" (cached)", ""),
                   "nature": nature, "famille": famille(l["url"])}


def ecrire(chemin, donnees):
    champs = ["page", "lien", "interne", "code", "detail", "nature", "famille"]
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=champs)
        w.writeheader()
        w.writerows(donnees)


def fusionner(dossier):
    """Réunit les relevés de lychee faits page par page en un seul lychee.json."""
    d = Path(dossier)
    total = {"total": 0, "unique": 0, "redirects": 0}
    cartes = {"success_map": {}, "error_map": {}, "excluded_map": {}, "timeout_map": {}}
    for f in sorted((d / "par-page").glob("*.json"), key=lambda f: int(f.stem)):
        r = json.loads(f.read_text(encoding="utf-8"))
        for cle in total:
            total[cle] += r.get(cle, 0) or 0
        for cle, carte in cartes.items():
            for source, liens in (r.get(cle) or {}).items():
                carte.setdefault(source, []).extend(liens)
    if not any(cartes.values()):
        return 1
    (d / "lychee.json").write_text(json.dumps({**total, **cartes}, ensure_ascii=False), encoding="utf-8")
    return 0


def principal(dossier, site):
    d = Path(dossier)
    r = json.loads((d / "lychee.json").read_text(encoding="utf-8"))
    erreurs = list(lignes(r.get("error_map"), site, "erreur"))
    casses = [l for l in erreurs if not refus_temporaire(l["code"])]
    refus = [{**l, "nature": "refus temporaire", "famille": REFUS_TEMPORAIRE} for l in erreurs if refus_temporaire(l["code"])]
    exclus = list(lignes(r.get("excluded_map"), site, "anti-robots"))
    a_verifier = [l for l in exclus if not NON_A_VERIFIER.search(l["lien"])]
    a_verifier += list(lignes(r.get("timeout_map"), site, "délai dépassé")) + refus
    ecrire(d / "liens_casses.csv", casses)
    ecrire(d / "a_verifier.csv", a_verifier)
    familles = Counter()
    for f, lien in {(l["famille"], l["lien"]) for l in a_verifier}:
        familles[f] += 1
    resume = {
        "pages_analysees": len({*r.get("success_map", {}), *r.get("error_map", {}), *r.get("excluded_map", {})}),
        "liens_verifies": r.get("total", 0), "liens_uniques": r.get("unique", 0),
        "liens_casses": len({c["lien"] for c in casses}),
        "liens_casses_internes": len({c["lien"] for c in casses if c["interne"]}),
        "occurrences_cassees": len(casses),
        "a_verifier_navigateur": len({c["lien"] for c in a_verifier}),
        "a_verifier_par_famille": dict(familles.most_common()),
        "redirections": r.get("redirects", 0),
        "refus_temporaires": len({l["lien"] for l in refus}),
        "pages_non_verifiees": [l.strip() for l in (d / "pages_non_verifiees.txt").read_text(encoding="utf-8").splitlines()
                                if l.strip()] if (d / "pages_non_verifiees.txt").exists() else [],
    }
    (d / "resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{resume['liens_verifies']} liens vérifiés, {resume['liens_casses']} cassés "
          f"(dont {resume['liens_casses_internes']} internes), {resume['a_verifier_navigateur']} à vérifier dans un navigateur"
          + (f", dont {resume['refus_temporaires']} refusés temporairement par le serveur" if refus else ""))
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "fusionner":
        sys.exit(fusionner(sys.argv[2]))
    if len(sys.argv) != 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    sys.exit(principal(sys.argv[1], sys.argv[2]))
