"""Prépare la configuration de pa11y-ci et résume ses résultats (moteur axe).

  python3 -m a11y_resume config PAGES.txt SORTIE.json   → configuration (défauts de config/pa11y.json + pages)
  python3 -m a11y_resume echecs DOSSIER                 → pages non testées (erreur d'exécution) de pa11y.json
  python3 -m a11y_resume fusionner DOSSIER              → remplace dans pa11y.json les résultats de pa11y-relance.json
  python3 -m a11y_resume resume DOSSIER                 → problemes.csv, regles.csv, resume.json
"""
import csv
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

from kit import lire_liste

RACINE = Path(__file__).resolve().parents[1]
IMPACTS = ["critical", "serious", "moderate", "minor", ""]
IMPACTS_FR = {"critical": "critique", "serious": "grave", "moderate": "modéré", "minor": "mineur", "": "non précisé"}


def configuration(pages, sortie):
    conf = json.loads((RACINE / "config/pa11y.json").read_text(encoding="utf-8"))
    conf["defaults"]["chromeLaunchConfig"]["executablePath"] = os.environ.get("CHROME_PATH", "/usr/bin/google-chrome")
    conf["urls"] = lire_liste(pages)
    Path(sortie).write_text(json.dumps(conf, ensure_ascii=False, indent=1), encoding="utf-8")


def pages_en_echec(dossier):
    r = json.loads((Path(dossier) / "pa11y.json").read_text(encoding="utf-8"))
    return [page for page, res in (r.get("results") or {}).items() if any("code" not in i for i in res)]


def fusionner(dossier):
    d = Path(dossier)
    r = json.loads((d / "pa11y.json").read_text(encoding="utf-8"))
    relance = json.loads((d / "pa11y-relance.json").read_text(encoding="utf-8"))
    r["results"].update(relance.get("results") or {})
    (d / "pa11y.json").write_text(json.dumps(r, ensure_ascii=False), encoding="utf-8")


def resume(dossier):
    d = Path(dossier)
    r = json.loads((d / "pa11y.json").read_text(encoding="utf-8"))
    problemes, echecs = [], []
    for page, resultats in (r.get("results") or {}).items():
        for i in resultats:
            if "code" not in i:  # erreur d'exécution (délai, page inaccessible)
                echecs.append({"page": page, "message": i.get("message", str(i))})
                continue
            extra = i.get("runnerExtras") or {}
            problemes.append({"page": page, "regle": i["code"], "impact": extra.get("impact") or "",
                              "description": extra.get("help") or extra.get("description") or i.get("message", ""),
                              "selecteur": i.get("selector", ""), "extrait": (i.get("context") or "")[:300],
                              "aide": extra.get("helpUrl", "")})
    champs = ["page", "regle", "impact", "description", "selecteur", "extrait", "aide"]
    with open(d / "problemes.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=champs)
        w.writeheader()
        w.writerows(problemes)

    regles = defaultdict(lambda: {"pages": set(), "occurrences": 0})
    for p in problemes:
        g = regles[p["regle"]]
        g.update(impact=p["impact"], description=p["description"], aide=p["aide"])
        g["pages"].add(p["page"])
        g["occurrences"] += 1
    tri = sorted(regles.items(), key=lambda kv: (IMPACTS.index(kv[1]["impact"]) if kv[1]["impact"] in IMPACTS else 9, -len(kv[1]["pages"])))
    with open(d / "regles.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["regle", "impact", "pages", "occurrences", "description", "aide"])
        for code, g in tri:
            w.writerow([code, IMPACTS_FR.get(g["impact"], g["impact"]), len(g["pages"]), g["occurrences"], g["description"], g["aide"]])

    pages = set((r.get("results") or {}).keys())
    synthese = {
        "pages_testees": len(pages), "pages_en_echec": len({e["page"] for e in echecs}),
        "pages_sans_probleme": len(pages - {p["page"] for p in problemes} - {e["page"] for e in echecs}),
        "problemes": len(problemes), "regles": len(regles),
        "par_impact": {IMPACTS_FR[k]: sum(1 for p in problemes if p["impact"] == k) for k in IMPACTS},
        "echecs": echecs,
    }
    (d / "resume.json").write_text(json.dumps(synthese, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{synthese['pages_testees']} page(s), {synthese['problemes']} problème(s) sur {synthese['regles']} règle(s) ; "
          f"par gravité : {synthese['par_impact']} ; {synthese['pages_en_echec']} page(s) non testée(s)")
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 3 and sys.argv[1] == "config":
        configuration(sys.argv[2], sys.argv[3])
    elif len(sys.argv) >= 3 and sys.argv[1] == "echecs":
        for page in pages_en_echec(sys.argv[2]):
            print(page)
    elif len(sys.argv) >= 3 and sys.argv[1] == "fusionner":
        fusionner(sys.argv[2])
    elif len(sys.argv) >= 3 and sys.argv[1] == "resume":
        sys.exit(resume(sys.argv[2]))
    else:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
