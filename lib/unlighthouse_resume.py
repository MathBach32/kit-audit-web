# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Résume le rapport jsonExpanded d'Unlighthouse.

  python3 -m unlighthouse_resume DOSSIER
    DOSSIER/rapport/ci-result.json → resume.csv (une ligne par page) et resume.json (moyennes)
    DOSSIER/pages.txt (pages demandées) → non_mesurees.txt : pages qu'Unlighthouse a écartées
    (erreur, page refusée par le serveur ou remplacée par un écran interstitiel)
"""
import csv
import json
import sys
import urllib.parse
from pathlib import Path

from kit import lire_liste


def note(c):
    return round(c["score"] * 100) if c and c.get("score") is not None else ""


def valeur(m, diviseur=1, chiffres=2):
    return round(m["numericValue"] / diviseur, chiffres) if m and m.get("numericValue") is not None else ""


def principal(dossier):
    d = Path(dossier)
    r = json.loads((d / "rapport/ci-result.json").read_text(encoding="utf-8"))
    with open(d / "resume.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["chemin", "global", "perf", "acces", "bonnes_pratiques", "referencement", "lcp_s", "cls", "tbt_ms"])
        for p in r["routes"]:
            c, m = p.get("categories") or {}, p.get("metrics") or {}
            w.writerow([p["path"], note(p), note(c.get("performance")), note(c.get("accessibility")),
                        note(c.get("best-practices")), note(c.get("seo")),
                        valeur(m.get("largest-contentful-paint"), 1000), valeur(m.get("cumulative-layout-shift"), 1, 3),
                        valeur(m.get("total-blocking-time"), 1, 0)])
    mesurees = {p["path"] for p in r["routes"]}
    demandees = lire_liste(d / "pages.txt") if (d / "pages.txt").exists() else []
    chemin = lambda u: (lambda p: (p.path or "/") + ("?" + p.query if p.query else ""))(urllib.parse.urlsplit(u))
    # une seule page demandée : Unlighthouse a exploré le site lui-même, rien à comparer
    non_mesurees = [u for u in demandees if chemin(u) not in mesurees] if len(demandees) > 1 else []
    (d / "non_mesurees.txt").write_text("".join(u + "\n" for u in non_mesurees), encoding="utf-8")
    categories = r["summary"]["categories"]
    lcp = r["summary"]["metrics"].get("largest-contentful-paint", {}).get("averageNumericValue")
    resume = {
        "pages": len(r["routes"]), "pages_demandees": len(demandees) if len(demandees) > 1 else None,
        "non_mesurees": len(non_mesurees),
        "moyennes": {k: round(v["averageScore"] * 100) for k, v in categories.items() if v.get("averageScore") is not None},
        "lcp_moyen_s": round(lcp / 1000, 2) if lcp is not None else None,
    }
    (d / "resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{resume['pages']} page(s) mesurée(s)" + (f" sur {len(demandees)}" if resume["pages_demandees"] else "")
          + f" ; moyennes : {resume['moyennes']} ; LCP moyen : {resume['lcp_moyen_s']} s")
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1] if len(sys.argv) > 1 else "."))
