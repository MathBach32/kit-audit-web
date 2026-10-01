"""Résume le rapport JSON de lychee.

  python3 -m liens_resume DOSSIER URL
    DOSSIER/lychee.json → liens_casses.csv, a_verifier.csv, resume.json
"""
import csv
import json
import re
import sys
import urllib.parse
from collections import Counter
from pathlib import Path

from kit import meme_site

# Liens exclus de lychee qu'il n'y a pas lieu de vérifier à la main :
# vidéos YouTube (vérifiées par bin/inventaire, oEmbed) et points d'accès techniques que lychee
# écarte de lui-même (xmlrpc.php).
NON_A_VERIFIER = re.compile(r"^https?://((www\.)?youtube(-nocookie)?\.com/(embed|watch|shorts)|youtu\.be/)|/xmlrpc\.php$")
FAMILLES = [  # (motif, libellé) : regroupement lisible des liens « à vérifier dans un navigateur »
    (r"[?&]share=", "boutons de partage (?share=)"),
    (r"wordpress\.com/log-in", "connexion WordPress.com"),
    (r"(^|\.)(facebook\.com|fb\.me|fb\.com)$", "Facebook"),
    (r"(^|\.)instagram\.com$", "Instagram"),
    (r"(^|\.)linkedin\.com$", "LinkedIn"),
    (r"(^|\.)(twitter|x)\.com$", "X (Twitter)"),
    (r"(^|\.)helloasso\.com$", "HelloAsso"),
]


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


def principal(dossier, site):
    d = Path(dossier)
    r = json.loads((d / "lychee.json").read_text(encoding="utf-8"))
    casses = list(lignes(r.get("error_map"), site, "erreur"))
    exclus = list(lignes(r.get("excluded_map"), site, "anti-robots"))
    a_verifier = [l for l in exclus if not NON_A_VERIFIER.search(l["lien"])]
    a_verifier += list(lignes(r.get("timeout_map"), site, "délai dépassé"))
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
    }
    (d / "resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{resume['liens_verifies']} liens vérifiés, {resume['liens_casses']} cassés "
          f"(dont {resume['liens_casses_internes']} internes), {resume['a_verifier_navigateur']} à vérifier dans un navigateur")
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1], sys.argv[2]))
