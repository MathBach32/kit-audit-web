"""Résume des rapports Lighthouse (locaux ou PageSpeed Insights) dans un CSV.

  python3 -m resume_lighthouse DOSSIER   → DOSSIER/resume.csv

Les fichiers attendus sont nommés <page>_<mobile|desktop>.json (format PSI ou Lighthouse brut).
Pour PSI, ajoute les données terrain CrUX quand Google en dispose.
"""
import csv
import json
import sys
from pathlib import Path

CATEGORIES = {"performance": "perf", "accessibility": "acces", "best-practices": "bonnes_pratiques", "seo": "referencement"}
MESURES = {"largest-contentful-paint": "lcp_s", "first-contentful-paint": "fcp_s", "total-blocking-time": "tbt_ms",
           "cumulative-layout-shift": "cls", "speed-index": "si_s"}
TERRAIN = {"LARGEST_CONTENTFUL_PAINT_MS": "terrain_lcp_ms", "INTERACTION_TO_NEXT_PAINT": "terrain_inp_ms",
           "CUMULATIVE_LAYOUT_SHIFT_SCORE": "terrain_cls"}


def resumer(chemin):
    donnees = json.loads(chemin.read_text(encoding="utf-8"))
    lh = donnees.get("lighthouseResult", donnees)
    if "categories" not in lh:
        return None
    page, _, strategie = chemin.stem.rpartition("_")
    ligne = {"page": page, "strategie": strategie, "url": lh.get("finalDisplayedUrl") or lh.get("requestedUrl", "")}
    for cle, nom in CATEGORIES.items():
        score = (lh["categories"].get(cle) or {}).get("score")
        ligne[nom] = round(score * 100) if score is not None else ""
    for cle, nom in MESURES.items():
        v = (lh.get("audits", {}).get(cle) or {}).get("numericValue")
        if v is None:
            ligne[nom] = ""
        elif nom.endswith("_s"):
            ligne[nom] = round(v / 1000, 2)
        elif nom == "cls":
            ligne[nom] = round(v, 3)
        else:
            ligne[nom] = round(v)
    terrain = (donnees.get("loadingExperience") or {}).get("metrics") or {}
    for cle, nom in TERRAIN.items():
        ligne[nom] = (terrain.get(cle) or {}).get("percentile", "")
    ligne["terrain_origine"] = "page" if terrain else ""
    if not terrain and (donnees.get("originLoadingExperience") or {}).get("metrics"):
        ligne["terrain_origine"] = "site"
    return ligne


def principal(dossier):
    dossier = Path(dossier)
    lignes = [l for f in sorted(dossier.glob("*_*.json")) if (l := resumer(f))]
    if not lignes:
        print("aucun rapport exploitable", file=sys.stderr)
        return 1
    with open(dossier / "resume.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(lignes[0].keys()))
        w.writeheader()
        w.writerows(lignes)
    for l in lignes:
        print(f'{l["page"]:<40} {l["strategie"]:<8} perf {l["perf"]:>3}  acc {l["acces"]:>3}  '
              f'bp {l["bonnes_pratiques"]:>3}  réf {l["referencement"]:>3}  LCP {l["lcp_s"]} s')
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1] if len(sys.argv) > 1 else "."))
