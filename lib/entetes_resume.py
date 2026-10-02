# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Résume les relevés de bin/entetes dans resume.json.

  python3 -m entetes_resume DOSSIER URL
"""
import datetime as dt
import json
import re
import sys
from pathlib import Path

SECURITE = {  # en-tête → rôle, en langage courant
    "strict-transport-security": "impose HTTPS au navigateur (HSTS)",
    "content-security-policy": "limite les scripts et contenus autorisés (CSP)",
    "x-content-type-options": "empêche le navigateur de deviner le type des fichiers",
    "x-frame-options": "empêche l'affichage du site dans un cadre d'un autre site",
    "referrer-policy": "limite l'adresse transmise aux sites liés",
    "permissions-policy": "restreint caméra, micro, géolocalisation…",
}
DIVULGATION = ("server", "x-powered-by", "x-generator", "x-aspnet-version")


def dernier_bloc_entetes(texte):
    """Dernier bloc d'en-têtes (après les redirections suivies par curl -L)."""
    blocs = [b for b in re.split(r"\r?\n\r?\n", texte) if b.strip().upper().startswith("HTTP/")]
    entetes = {}
    if not blocs:
        return "", entetes
    lignes = blocs[-1].strip().splitlines()
    for l in lignes[1:]:
        if ":" in l:
            k, v = l.split(":", 1)
            entetes[k.strip().lower()] = v.strip()
    return lignes[0].strip(), entetes


def dns(texte):
    sections, cle = {}, None
    for l in texte.splitlines():
        if l.startswith("== "):
            cle = l[3:].strip()
            sections[cle] = []
        elif cle and l.strip():
            sections[cle].append(l.strip())
    return sections


def date_cert(texte, cle):
    m = re.search(rf"{cle}=(.+)", texte)
    if not m:
        return None
    return dt.datetime.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z").replace(tzinfo=dt.timezone.utc)


def principal(dossier, url):
    d = Path(dossier)
    lire = lambda n: (d / n).read_text(encoding="utf-8", errors="replace") if (d / n).exists() else ""
    statut, h = dernier_bloc_entetes(lire("entetes_accueil.txt"))
    resume = {"url": url, "statut_accueil": statut}
    resume["securite"] = {k: {"present": k in h, "valeur": h.get(k, ""), "role": r} for k, r in SECURITE.items()}
    resume["divulgation"] = {k: h[k] for k in DIVULGATION if k in h}

    # Redirections : chaque variante doit aboutir en HTTPS sur l'adresse canonique
    variantes = {}
    for bloc in lire("redirections.txt").split("== ")[1:]:
        lignes = bloc.strip().splitlines()
        m = re.match(r"(\d{3}) (\d+) redirection\(s\) -> (\S+)", lignes[1]) if len(lignes) > 1 else None
        variantes[lignes[0].strip()] = {"code": m.group(1), "redirections": int(m.group(2)), "finale": m.group(3)} if m else {"code": "000"}
    resume["variantes"] = variantes

    cert = lire("certificat.txt")
    fin = date_cert(cert, "notAfter")
    resume["certificat"] = {
        "emetteur": (re.search(r"issuer=(.+)", cert) or [None, ""])[1].strip(),
        "expire_le": fin.date().isoformat() if fin else "",
        "jours_restants": (fin - dt.datetime.now(dt.timezone.utc)).days if fin else None,
    }
    resume["tls"] = dict(l.split() for l in lire("tls.txt").splitlines() if len(l.split()) == 2)

    racine = url.split("/")[2].removeprefix("www.")
    z = dns(lire("dns.txt"))
    txt = " ".join(z.get(f"TXT {racine}", []))
    resume["dns"] = {
        "a": z.get(f"A {racine}", []), "aaaa": z.get(f"AAAA {racine}", []), "ns": z.get(f"NS {racine}", []),
        "mx": z.get(f"MX {racine}", []), "caa": z.get(f"CAA {racine}", []),
        "dnssec": bool(z.get(f"DS {racine}")),
        # seuls les enregistrements v=spf1 et v=DMARC1 comptent (dig +short affiche aussi les cibles CNAME)
        "spf": next((t.replace('" "', "").strip('"') for t in z.get(f"TXT {racine}", []) if "v=spf1" in t), ""),
        "dmarc": next((t.replace('" "', "").strip('"') for t in z.get(f"TXT _dmarc.{racine}", []) if "v=DMARC1" in t), ""),
        "dkim_selecteurs_trouves": [k.split()[1].split(".")[0] for k in z if "._domainkey." in k],
        "verification_google": "google-site-verification" in txt,
    }

    try:
        rdap = json.loads(lire("rdap.json") or "{}")
    except json.JSONDecodeError:
        rdap = {}
    evenements = {e.get("eventAction"): e.get("eventDate", "")[:10] for e in rdap.get("events", [])}
    registrar = ""
    for ent in rdap.get("entities", []):
        if "registrar" in ent.get("roles", []):
            vcard = ent.get("vcardArray", [None, []])[1]
            registrar = next((v[3] for v in vcard if v[0] == "fn"), "")
    resume["domaine"] = {"bureau_enregistrement": registrar, "cree_le": evenements.get("registration", ""),
                         "expire_le": evenements.get("expiration", ""), "statuts": rdap.get("status", [])}
    if resume["domaine"]["expire_le"]:
        resume["domaine"]["jours_restants"] = (dt.date.fromisoformat(resume["domaine"]["expire_le"]) - dt.date.today()).days

    fichiers = {}
    for l in lire("fichiers_publics.txt").splitlines():
        code, _, nom = l.partition(" ")
        fichiers[nom] = code
    resume["fichiers_publics"] = fichiers
    resume["sitemaps"] = [l for l in lire("sitemaps.txt").splitlines() if l.strip()]

    (d / "resume.json").write_text(json.dumps(resume, ensure_ascii=False, indent=1), encoding="utf-8")
    absents = [k for k, v in resume["securite"].items() if not v["present"]]
    print(f"accueil : {statut} ; en-têtes de sécurité absents : {', '.join(absents) or 'aucun'}")
    print(f"certificat : expire le {resume['certificat']['expire_le']} ; domaine : expire le {resume['domaine']['expire_le'] or '?'}")
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1], sys.argv[2]))
