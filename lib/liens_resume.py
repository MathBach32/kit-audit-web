"""Résume le rapport JSON de lychee.

  python3 -m liens_resume DOSSIER URL
    DOSSIER/lychee.json → liens_casses.csv, a_verifier.csv, resume.json
"""
import csv
import json
import sys
from pathlib import Path

from kit import meme_site


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
                   "nature": nature}


def ecrire(chemin, donnees):
    champs = ["page", "lien", "interne", "code", "detail", "nature"]
    with open(chemin, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=champs)
        w.writeheader()
        w.writerows(donnees)


def principal(dossier, site):
    d = Path(dossier)
    r = json.loads((d / "lychee.json").read_text(encoding="utf-8"))
    casses = list(lignes(r.get("error_map"), site, "erreur"))
    a_verifier = list(lignes(r.get("excluded_map"), site, "anti-robots")) + list(lignes(r.get("timeout_map"), site, "délai dépassé"))
    ecrire(d / "liens_casses.csv", casses)
    ecrire(d / "a_verifier.csv", a_verifier)
    resume = {
        "pages_analysees": len({*r.get("success_map", {}), *r.get("error_map", {}), *r.get("excluded_map", {})}),
        "liens_verifies": r.get("total", 0), "liens_uniques": r.get("unique", 0),
        "liens_casses": len({c["lien"] for c in casses}),
        "liens_casses_internes": len({c["lien"] for c in casses if c["interne"]}),
        "occurrences_cassees": len(casses),
        "a_verifier_navigateur": len({c["lien"] for c in a_verifier}),
        "redirections": r.get("redirects", 0),
    }
    (d / "resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{resume['liens_verifies']} liens vérifiés, {resume['liens_casses']} cassés "
          f"(dont {resume['liens_casses_internes']} internes), {resume['a_verifier_navigateur']} à vérifier dans un navigateur")
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1], sys.argv[2]))
