# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Interface graphique du kit : petit serveur web local, bibliothèque standard seulement.

  python3 -m interface [--port N] [--sans-navigateur]   (lancé par bin/interface)

Sert la page de interface/ et une API JSON : lancer un audit (bin/tout), suivre son journal en
direct (Server-Sent Events), parcourir les audits passés, regénérer une synthèse (bin/synthese),
voir l'état de l'installation.

Sécurité (une page web malveillante peut viser un serveur local) :
  - écoute sur une adresse de bouclage propre à la session, tirée au hasard dans 127.0.0.0/8 :
    un cookie ne tient pas compte du port, et celui de l'interface ne part donc pas vers les
    autres services de 127.0.0.1 ou de localhost, dont les pages sont « d'un autre site » ;
  - en-tête Host vérifié (contre le DNS rebinding) ;
  - jeton aléatoire transmis dans l'adresse d'ouverture, échangé contre un cookie de session
    HttpOnly SameSite=Strict (valeur distincte), exigé pour tout le reste ;
  - requêtes POST : en-tête X-Jeton (troisième valeur, écrite dans la page) et corps JSON en plus
    (contre le CSRF) ;
  - commandes lancées avec une liste d'arguments validés, jamais par un shell ;
  - fichiers de résultats servis sans jamais sortir de leur racine (liens symboliques compris).
"""
import argparse
import ctypes
import datetime as dt
import errno
import fcntl
import ipaddress
import itertools
import json
import mimetypes
import os
import re
import secrets
import shutil
import signal
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata
from pathlib import Path

from kit import domaine, normaliser_url

RACINE = Path(__file__).resolve().parents[1]
PAGES = RACINE / "interface"
STATIQUES = {"/interface.css": "text/css; charset=utf-8", "/interface.js": "text/javascript; charset=utf-8"}
RESULTATS = Path(os.environ.get("KIT_AUDIT_RESULTATS") or RACINE / "resultats").resolve()
SECRETS = Path(os.environ.get("KIT_AUDIT_SECRETS") or Path.home() / ".config/audit-kit/secrets.env")
CHROME = os.environ.get("CHROME_PATH", "/usr/bin/google-chrome")
PROFIL = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "kit-audit-web/interface"
PORTS_ESSAYES = 20
LIGNES_MAX = 20000          # lignes de journal gardées en mémoire (les plus anciennes sont oubliées)
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
HOTE = re.compile(r"^(?=.{1,253}$)[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)*$", re.I)
JOUR = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ALIAS = {"sf": "sf-crawl"}  # nom d'outil dans manifeste.json → nom de la commande
CSP_PAGE = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
            "base-uri 'none'; form-action 'self'; frame-ancestors 'none'")
CSP_RESULTAT = ("default-src 'none'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
                "media-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'")


class Refus(Exception):
    """Erreur renvoyée au client : code HTTP et message en français."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code, self.message = code, message


def date_fichier(chemin):
    """Date de modification ISO (à la minute) d'un fichier, None s'il n'existe pas."""
    try:
        return dt.datetime.fromtimestamp(Path(chemin).stat().st_mtime).isoformat(timespec="minutes")
    except OSError:
        return None


def lire_json(chemin):
    try:
        return json.loads(Path(chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# --- Validation des entrées --------------------------------------------------------------------
def hote_valide(hote):
    try:
        ipaddress.ip_address(hote)
        return True
    except ValueError:
        return bool(HOTE.match(hote or ""))


def valider_url(adresse):
    """URL normalisée par kit.normaliser_url, refusée si douteuse (espaces, identifiants, hôte, port)."""
    if not isinstance(adresse, str) or not adresse.strip() or len(adresse) > 2000 \
            or re.search(r"[\s\x00-\x1f\x7f]", adresse.strip()):
        raise Refus(400, "Adresse du site invalide.")
    try:
        url = normaliser_url(adresse)
        p = urllib.parse.urlsplit(url)
        p.port  # lève ValueError si le port n'est pas un nombre valide
    except ValueError:
        raise Refus(400, "Adresse du site invalide.") from None
    if p.scheme not in ("http", "https") or "@" in p.netloc or not hote_valide(p.hostname):
        raise Refus(400, "Adresse du site invalide : indiquer par exemple https://exemple.fr/.")
    return url


def valider_max(valeur):
    if valeur in (None, ""):
        return None
    if isinstance(valeur, str) and valeur.strip().isdigit():
        valeur = int(valeur)
    if isinstance(valeur, bool) or not isinstance(valeur, int) or not 1 <= valeur <= 100000:
        raise Refus(400, "Nombre maximal de pages invalide (1 à 100 000).")
    return valeur


def valider_voisins(texte):
    """Noms de domaine séparés par des espaces ou des virgules (passés à dig par bin/entetes)."""
    if texte in (None, ""):
        return ""
    if not isinstance(texte, str) or len(texte) > 2000:
        raise Refus(400, "Domaines voisins invalides.")
    noms = [n for n in re.split(r"[\s,;]+", texte.strip().lower()) if n]
    mauvais = [n for n in noms if not HOTE.match(n)]
    if mauvais or len(noms) > 30:
        raise Refus(400, f"Domaines voisins invalides : {' '.join(mauvais)[:200] or 'trop nombreux'}.")
    return " ".join(noms)


def dossier_audit(nom_domaine, jour):
    """Dossier <résultats>/<domaine>/<AAAA-MM-JJ> existant, sans sortir de la racine des résultats."""
    if not isinstance(nom_domaine, str) or not isinstance(jour, str) or not JOUR.match(jour) \
            or not re.fullmatch(r"[A-Za-z0-9:._-]+", nom_domaine) or nom_domaine.startswith("."):
        raise Refus(400, "Audit inconnu.")
    d = (RESULTATS / nom_domaine / jour).resolve()
    if not d.is_relative_to(RESULTATS) or not d.is_dir():
        raise Refus(404, "Audit introuvable.")
    return d


def dossier_occupe(d):
    """Vrai si un bin/tout ou un bin/synthese tient le verrou du dossier d'audit (flock sur .verrou,
    voir verrouiller_dossier dans lib/commun.sh), qu'il ait été lancé par l'interface ou non."""
    try:
        fd = os.open(d / ".verrou", os.O_RDONLY | os.O_NOFOLLOW)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)   # essai seulement : relâché aussitôt
        return False
    except BlockingIOError:
        return True
    except OSError:
        return False
    finally:
        os.close(fd)


# --- Processus ---------------------------------------------------------------------------------
def processus():
    """{pid: (ppid, date de démarrage)} des processus visibles dans /proc (Linux)."""
    tous = {}
    for p in Path("/proc").iterdir():
        if p.name.isdigit():
            try:
                champs = (p / "stat").read_text().rsplit(")", 1)[1].split()
                tous[int(p.name)] = (int(champs[1]), champs[19])
            except (OSError, IndexError, ValueError):
                continue
    return tous


def descendants(racine):
    """{pid: date de démarrage} de tous les descendants de racine, y compris ceux qui ont changé de
    groupe de processus (Chrome lancé par Lighthouse, par exemple)."""
    tous, enfants = processus(), defaultdict(list)
    for pid, (ppid, _) in tous.items():
        enfants[ppid].append(pid)
    trouves, pile = {}, [racine]
    while pile:
        for e in enfants[pile.pop()]:
            trouves[e] = tous[e][1]
            pile.append(e)
    return trouves


def signaler(pids, sig):
    """Envoie sig aux processus de pids encore vivants, si leur pid n'a pas été réattribué."""
    actuels = processus()
    for pid, debut in pids.items():
        if pid in actuels and actuels[pid][1] == debut:
            try:
                os.kill(pid, sig)
            except (ProcessLookupError, PermissionError):
                pass


try:   # prctl de la libc, préparé ici : le code exécuté entre fork et exec doit rester minimal
    _PRCTL = ctypes.CDLL(None, use_errno=True).prctl
except (OSError, AttributeError):
    _PRCTL = None
_PR_SET_PDEATHSIG, _SIGTERM = 1, int(signal.SIGTERM)


def _terminer_avec_le_parent():
    """preexec_fn : SIGTERM au processus lancé si le fil qui l'a lancé disparaît (interface tuée,
    terminal fermé) ; Linux seulement, sans effet ailleurs."""
    if _PRCTL is not None:
        _PRCTL(_PR_SET_PDEATHSIG, _SIGTERM)


class Travail:
    """Un audit (bin/tout) ou une regénération de synthèse (bin/synthese), en cours ou terminé."""
    numeros = itertools.count(1)

    def __init__(self, genre, site, dossier, outils, libelles, commande):
        self.id = next(Travail.numeros)
        self.genre, self.site, self.dossier, self.libelles = genre, site, Path(dossier), libelles
        self.etats = {nom: {"etat": "attente"} for nom in outils}
        self.lignes, self.decalage, self.version = [], 0, 0
        self.debut, self.fin, self.code, self.statut = time.time(), None, None, "en_cours"
        self.courant, self.arret_demande = None, False
        self.cond = threading.Condition()
        if genre == "pdf":                 # bin/synthese seul : pas de ligne « === »
            self._commencer("synthese")
        # Le processus est lancé par le fil qui l'attend jusqu'au bout : le signal de PR_SET_PDEATHSIG
        # part à la fin du fil qui a lancé le processus, pas seulement à celle de l'interface.
        self.proc, self.erreur, lance = None, None, threading.Event()
        threading.Thread(target=self._surveiller, args=(commande, lance), daemon=True).start()
        lance.wait()
        if self.erreur:
            raise self.erreur

    def en_cours(self):
        return self.statut == "en_cours"

    def _lire(self):
        for brut in self.proc.stdout:
            morceaux = [m for m in brut.decode("utf-8", "replace").rstrip("\n").split("\r") if m.strip()]
            self.ajouter(ANSI.sub("", morceaux[-1]) if morceaux else "")

    def _surveiller(self, commande, lance):
        env = dict(os.environ, PYTHONUNBUFFERED="1", NO_COLOR="1")
        try:
            self.proc = subprocess.Popen(commande, cwd=RACINE, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                         stderr=subprocess.STDOUT, start_new_session=True,  # groupe de processus propre
                                         preexec_fn=_terminer_avec_le_parent)
        except (OSError, subprocess.SubprocessError) as e:
            self.erreur = e
            return
        finally:
            lance.set()
        self.lecteur = threading.Thread(target=self._lire, daemon=True)
        self.lecteur.start()
        code = self.proc.wait()
        self.lecteur.join(timeout=10)      # un petit-enfant peut garder le tube ouvert : ne pas l'attendre
        with self.cond:
            self._lire_etats()
            if self.courant:
                fin_normale = code == 0 and not self.arret_demande
                self._terminer_courant("interrompu" if self.arret_demande else "reussi" if fin_normale else "echec")
            self.code, self.fin = code, time.time()
            self.statut = "arrete" if self.arret_demande else self._statut_final(code)
            self.version += 1
            self.cond.notify_all()

    def _statut_final(self, code):
        """bin/tout finit toujours par « journal | tee » (code 0) : le bilan vient des états des outils.
        Échec si la synthèse n'a pas produit son PDF ; « termine_echecs » si un outil a échoué."""
        if code != 0 or self.etats.get("synthese", {}).get("etat") != "reussi" \
                or not (self.dossier / "synthese/synthese.pdf").is_file():
            return "echec"
        return "termine_echecs" if any(e["etat"] == "echec" for e in self.etats.values()) else "termine"

    def ajouter(self, ligne):
        with self.cond:
            self._analyser(ligne)
            self.lignes.append(ligne)
            if len(self.lignes) > LIGNES_MAX:
                del self.lignes[:LIGNES_MAX // 4]
                self.decalage += LIGNES_MAX // 4
            self.cond.notify_all()

    # États des outils : lignes « === outil » et « outil a échoué (code N) » du journal de bin/tout,
    # complétées par .etats.tsv (code et durée de chaque outil terminé ; supprimé en fin d'audit).
    def _analyser(self, ligne):
        m = re.match(r"^\[\d\d:\d\d:\d\d\] === (\S+)$", ligne)
        if m and m.group(1) in self.etats:
            self._lire_etats()
            if self.courant:
                self._terminer_courant("reussi")
            self._commencer(m.group(1))
            return
        m = re.match(r"^\[\d\d:\d\d:\d\d\] (\S+) a échoué \(code (\d+)\)", ligne)
        if m and m.group(1) in self.etats:
            self.etats[m.group(1)].update(etat="echec", code=int(m.group(2)))
            self.version += 1

    def _commencer(self, nom):
        self.courant = nom
        self.etats[nom].update(etat="en_cours", debut=time.time())
        self.version += 1

    def _terminer_courant(self, etat):
        e = self.etats[self.courant]
        if e["etat"] == "en_cours":
            e.update(etat=etat, duree=round(time.time() - e["debut"]))
        self.courant = None
        self.version += 1

    def _lire_etats(self):
        try:
            lignes = (self.dossier / ".etats.tsv").read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for ligne in lignes:
            try:
                nom, code, duree = ligne.split("\t")
                code, duree = int(code), int(duree)
            except ValueError:
                continue
            if nom in self.etats:
                self.etats[nom].update(etat="reussi" if code == 0 else "echec", code=code, duree=duree)
                if nom == self.courant:
                    self.courant = None
                self.version += 1

    def arreter(self, attendre=False):
        """SIGTERM au groupe de processus et à tous les descendants, puis SIGKILL après 5 s."""
        with self.cond:
            if not self.en_cours():
                return False
            self.arret_demande = True
        self.ajouter("[interface] arrêt demandé : signal envoyé à l'audit et à ses processus")
        pids = descendants(self.proc.pid)
        try:
            os.killpg(self.proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        signaler(pids, signal.SIGTERM)

        def achever():
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.5)
            try:
                os.killpg(self.proc.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            signaler(pids, signal.SIGKILL)
            if self.genre == "audit":       # bin/tout, arrêté net, n'a rien pu écrire dans son journal
                try:
                    with (self.dossier / "journal.txt").open("a", encoding="utf-8") as j:
                        j.write(f"[{time.strftime('%H:%M:%S')}] audit arrêté depuis l'interface graphique\n")
                except OSError:
                    pass
        if attendre:
            achever()
        else:
            threading.Thread(target=achever, daemon=True).start()
        return True

    def resume(self):
        with self.cond:
            try:
                chemin = self.dossier.relative_to(RESULTATS).as_posix()
            except ValueError:
                chemin = None
            synthese = self.dossier / "synthese"
            produite = self.etats.get("synthese", {}).get("etat") == "reussi"
            return {
                "id": self.id, "genre": self.genre, "site": self.site, "dossier": str(self.dossier), "chemin": chemin,
                "statut": self.statut, "code": self.code, "debut": self.debut, "fin": self.fin, "lignes": self.decalage + len(self.lignes),
                "outils": [{"nom": n, "libelle": self.libelles.get(n, n), **e} for n, e in self.etats.items()],
                "echecs": [self.libelles.get(n, n) for n, e in self.etats.items() if e["etat"] == "echec" and n != "synthese"],
                "synthese": (synthese / "synthese.html").is_file(), "pdf": (synthese / "synthese.pdf").is_file(),
                # synthèse produite par ce travail, ou laissée par un passage précédent (arrêt, échec)
                "produite": produite, "synthese_date": date_fichier(synthese / "synthese.html"),
            }


# --- Données servies ---------------------------------------------------------------------------
def liste_outils():
    """Commandes de bin/tout --liste-outils : [{nom, libelle, description}], dans l'ordre de l'audit."""
    sortie = subprocess.run([str(RACINE / "bin/tout"), "--liste-outils"], capture_output=True, text=True, timeout=30, check=True).stdout
    outils = []
    for ligne in sortie.splitlines():
        nom, libelle, description = (ligne.split("\t") + ["", ""])[:3]
        if nom:
            outils.append({"nom": nom, "libelle": libelle or nom, "description": description})
    return outils


def cle_psi_configuree():
    """Vrai si PSI_API_KEY est renseignée (environnement ou fichier des secrets) ; la valeur n'est jamais renvoyée."""
    if os.environ.get("PSI_API_KEY", "").strip():
        return True
    try:
        texte = SECRETS.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    valeurs = re.findall(r"^[ \t]*(?:export[ \t]+)?PSI_API_KEY=(.*)$", texte, re.M)
    return bool(valeurs) and bool(re.sub(r"[\"'\s]", "", valeurs[-1]))


def decrire_audit(d, libelles, travail):
    m = lire_json(d / "manifeste.json") or {}
    v = lire_json(d / "synthese/voyants.json") or {}
    outils = [o for o in m.get("outils", []) if isinstance(o, dict) and "outil" in o]
    nommer = lambda o: {"nom": o["outil"], "libelle": libelles.get(ALIAS.get(o["outil"], o["outil"]), o["outil"])}  # noqa: E731
    pdf, page, manifeste = d / "synthese/synthese.pdf", d / "synthese/synthese.html", d / "manifeste.json"
    try:
        site = (d / "site.txt").read_text(encoding="utf-8").strip()
    except OSError:
        site = ""
    en_cours, occupe = bool(travail and travail.en_cours() and travail.dossier == d), dossier_occupe(d)
    return {
        "domaine": d.parent.name, "date": d.name, "chemin": f"{d.parent.name}/{d.name}", "site": site,
        "reussis": [nommer(o) for o in outils if o.get("code") == 0], "echecs": [nommer(o) for o in outils if o.get("code") != 0],
        "voyants": v.get("voyants", []), "chiffres": v.get("chiffres", []),
        "synthese": (d / "synthese/synthese.html").is_file(), "pdf": pdf.is_file(),
        "pdf_date": date_fichier(pdf),
        "en_cours": en_cours,
        "occupe": occupe,     # audit en cours, y compris lancé en ligne de commande
        # bin/tout supprime .etats.tsv en fin normale : s'il reste sans audit en cours, le dernier
        # passage a été interrompu, et bilan et voyants viennent d'un passage précédent
        "interrompu": (d / ".etats.tsv").exists() and not occupe and not en_cours,
        # synthèse plus ancienne que le dernier manifeste : sa production a échoué au dernier passage
        "synthese_perimee": page.is_file() and manifeste.is_file() and page.stat().st_mtime < manifeste.stat().st_mtime,
    }


def lister_audits(libelles, travail):
    audits = []
    if not RESULTATS.is_dir():
        return audits
    for dom in RESULTATS.iterdir():
        if dom.name.startswith(".") or dom.is_symlink() or not dom.is_dir():
            continue
        for d in dom.iterdir():
            if JOUR.match(d.name) and not d.is_symlink() and d.is_dir():
                try:
                    audits.append(decrire_audit(d, libelles, travail))
                except (OSError, ValueError, TypeError, AttributeError) as e:
                    print(f"audit illisible {d} : {e!r}", file=sys.stderr)
    return sorted(sorted(audits, key=lambda a: a["domaine"]), key=lambda a: a["date"], reverse=True)  # récents d'abord


def version(*commande):
    try:
        r = subprocess.run(commande, capture_output=True, text=True, timeout=30)
        return ((r.stdout or r.stderr).strip().splitlines() or [""])[0]
    except (OSError, subprocess.SubprocessError):
        return ""


def etat_installation():
    def paquet(nom):
        try:
            return metadata.version(nom)
        except metadata.PackageNotFoundError:
            return ""
    commandes = {
        "Navigateur": (CHROME, "--version"), "Node": ("node", "--version"), "Lighthouse": ("lighthouse", "--version"),
        "Unlighthouse": ("unlighthouse-ci", "--version"), "pa11y-ci": ("pa11y-ci", "--version"), "lychee": ("lychee", "--version"),
    }
    with ThreadPoolExecutor(len(commandes) + 1) as ex:
        verification = ex.submit(subprocess.run, [str(RACINE / "installer.sh"), "--verifier"], cwd=RACINE,
                                 capture_output=True, text=True, timeout=180)
        versions = {nom: ex.submit(version, *cmd) for nom, cmd in commandes.items()}
        versions = {nom: f.result() for nom, f in versions.items()}
        try:
            v = verification.result()
            verification = {"code": v.returncode, "sortie": ANSI.sub("", v.stdout + v.stderr).strip()}
        except (OSError, subprocess.SubprocessError) as e:
            verification = {"code": -1, "sortie": f"Vérification impossible : {e}"}
    versions["Unlighthouse"] = (versions["Unlighthouse"].split("/")[-1].split() or [""])[0]
    versions["lychee"] = versions["lychee"].replace("lychee ", "")
    versions["Node"] = versions["Node"].lstrip("v")
    versions.update({"Python": sys.version.split()[0], "advertools": paquet("advertools")})
    return {
        "navigateur": {"chemin": CHROME, "version": versions.pop("Navigateur"), "executable": os.access(CHROME, os.X_OK)},
        "versions": [{"outil": k, "version": v} for k, v in versions.items()],
        "psi_cle": cle_psi_configuree(), "secrets": str(SECRETS), "resultats": str(RESULTATS), "kit": str(RACINE),
        "verification": verification,
    }


# --- Serveur HTTP ------------------------------------------------------------------------------
def adresse_dediee():
    """Adresse de bouclage tirée au hasard dans 127.1.0.1 – 127.254.255.254 (Linux route tout
    127.0.0.0/8 vers l'interface lo) : les cookies de l'interface y restent attachés."""
    return f"127.{secrets.randbelow(254) + 1}.{secrets.randbelow(256)}.{secrets.randbelow(254) + 1}"


class Serveur(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, adresse, port):
        super().__init__((adresse, port), Gestionnaire)
        self.adresse, self.port = adresse, port
        self.jeton = secrets.token_urlsafe(32)      # adresse d'ouverture affichée dans le terminal
        self.session = secrets.token_urlsafe(32)    # valeur du cookie, jamais affichée
        self.csrf = secrets.token_urlsafe(32)       # en-tête X-Jeton des POST, écrit dans la page
        self.cookie = f"kit_audit_session_{port}"   # les cookies ne distinguent pas les ports
        self.hotes = {f"{adresse}:{port}"}
        self.jetons_uniques, self.verrou_jetons = set(), threading.Lock()
        self.outils = liste_outils()
        self.libelles = {o["nom"]: o["libelle"] for o in self.outils} | {"synthese": "Synthèse"}
        self.travail = None
        self.verrou = threading.Lock()
        self.verrou_etat = threading.Lock()
        self.installation = None

    def adresse_ouverture(self, unique=False):
        """Adresse à jeton. unique=True : jeton à usage unique, pour la fenêtre du navigateur, dont la
        ligne de commande est lisible par tous les comptes (ps) ; il ne sert plus une fois la session
        ouverte, alors que l'adresse affichée dans le terminal reste valable jusqu'à l'arrêt."""
        jeton = self.jeton
        if unique:
            jeton = secrets.token_urlsafe(32)
            with self.verrou_jetons:
                self.jetons_uniques.add(jeton)
        return f"http://{self.adresse}:{self.port}/?jeton={jeton}"

    def jeton_valide(self, jeton):
        if secrets.compare_digest(jeton.encode(), self.jeton.encode()):
            return True
        with self.verrou_jetons:
            trouve = next((j for j in self.jetons_uniques if secrets.compare_digest(jeton.encode(), j.encode())), None)
            self.jetons_uniques.discard(trouve)
        return trouve is not None

    def demarrer(self, genre, site, dossier, outils, commande):
        with self.verrou:
            if self.travail and self.travail.en_cours():
                raise Refus(409, "Un audit est déjà en cours : attendre sa fin ou l'arrêter.")
            self.travail = Travail(genre, site, dossier, outils, self.libelles, commande)
            return self.travail.resume()


class Gestionnaire(BaseHTTPRequestHandler):
    server_version = "kit-audit-web"
    sys_version = ""

    def log_message(self, format, *args):  # noqa: A002 — pas de journal des requêtes : l'adresse d'ouverture contient le jeton
        pass

    def do_GET(self):  # noqa: N802
        self._traiter("GET")

    def do_POST(self):  # noqa: N802
        self._traiter("POST")

    def _traiter(self, methode):
        chemin, _, requete = self.path.partition("?")
        api = chemin.startswith("/api/")
        try:
            if (self.headers.get("Host") or "").lower() not in self.server.hotes:
                raise Refus(403, "Hôte refusé.")
            if not chemin.startswith("/"):
                raise Refus(400, "Requête invalide.")
            params = urllib.parse.parse_qs(requete)
            if methode == "GET" and chemin == "/" and "jeton" in params:
                return self._ouvrir_session(params["jeton"][0])
            if not self._cookie_valide():
                raise Refus(403, "Accès refusé : ouvrir l'interface avec bin/interface (l'adresse affichée contient le jeton).")
            if methode == "POST":
                self._verifier_post()
                route = {"/api/audits": self._lancer_audit, "/api/arreter": self._arreter, "/api/pdf": self._regenerer_pdf,
                         "/api/ouvrir-dossier": self._ouvrir_dossier}.get(chemin)
                if not route:
                    raise Refus(404, "Adresse inconnue.")
                return self._json(200, route(self._corps_json()))
            if chemin == "/":
                page = (PAGES / "index.html").read_text(encoding="utf-8").replace("__JETON__", self.server.csrf)
                return self._envoyer(200, page.encode(), "text/html; charset=utf-8", page_interface=True)
            if chemin in STATIQUES:
                return self._envoyer(200, (PAGES / chemin[1:]).read_bytes(), STATIQUES[chemin], page_interface=True)
            if chemin.startswith("/resultats/"):
                return self._fichier_resultat(chemin[len("/resultats/"):])
            travail = self.server.travail
            if chemin == "/api/flux":
                return self._flux(params)
            reponses = {
                "/api/outils": lambda: {"outils": self.server.outils, "psi_cle": cle_psi_configuree(), "resultats": str(RESULTATS)},
                "/api/statut": lambda: {"travail": travail.resume() if travail else None},
                "/api/audits": lambda: {"audits": lister_audits(self.server.libelles, travail), "resultats": str(RESULTATS)},
                "/api/etat": lambda: self._etat("rafraichir" in params),
            }
            if chemin not in reponses:
                raise Refus(404, "Adresse inconnue.")
            return self._json(200, reponses[chemin]())
        except Refus as e:
            if api:
                self._json(e.code, {"erreur": e.message})
            else:
                corps = f'<!doctype html><html lang="fr"><meta charset="utf-8"><title>Kit d\'audit web</title><p>{e.message}</p>'
                self._envoyer(e.code, corps.encode(), "text/html; charset=utf-8")
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:  # noqa: BLE001 — une erreur imprévue ne doit pas arrêter le serveur
            traceback.print_exc()
            try:
                self._json(500, {"erreur": "Erreur interne du serveur (voir le terminal)."})
            except OSError:
                pass

    # --- Contrôles d'accès ---
    def _ouvrir_session(self, jeton):
        valide = self.server.jeton_valide(jeton)
        if not valide and not self._cookie_valide():   # jeton déjà utilisé, mais session ouverte : on y retourne
            raise Refus(403, "Jeton invalide ou déjà utilisé : ouvrir l'adresse affichée par bin/interface.")
        self.send_response(303)
        self.send_header("Location", "/")      # retire le jeton de la barre d'adresse et de l'historique
        if valide:
            self.send_header("Set-Cookie", f"{self.server.cookie}={self.server.session}; Path=/; HttpOnly; SameSite=Strict")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _cookie_valide(self):
        for morceau in (self.headers.get("Cookie") or "").split(";"):
            nom, _, valeur = morceau.strip().partition("=")
            if nom == self.server.cookie and secrets.compare_digest(valeur.encode(), self.server.session.encode()):
                return True
        return False

    def _verifier_post(self):
        if not secrets.compare_digest((self.headers.get("X-Jeton") or "").encode(), self.server.csrf.encode()):
            raise Refus(403, "En-tête X-Jeton absent ou invalide.")
        origine = self.headers.get("Origin")
        if origine and origine.lower() not in {f"http://{h}" for h in self.server.hotes}:
            raise Refus(403, "Origine refusée.")
        if self.headers.get("Sec-Fetch-Site", "same-origin") not in ("same-origin", "none"):
            raise Refus(403, "Requête d'un autre site refusée.")

    def _corps_json(self):
        if self.headers.get_content_type() != "application/json":
            raise Refus(415, "Corps JSON attendu (Content-Type: application/json).")
        try:
            taille = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            raise Refus(400, "Longueur invalide.") from None
        if not 0 < taille <= 65536:
            raise Refus(400 if taille <= 0 else 413, "Corps JSON absent ou trop volumineux.")
        try:
            donnees = json.loads(self.rfile.read(taille))
        except (ValueError, UnicodeDecodeError):
            raise Refus(400, "JSON invalide.") from None
        if not isinstance(donnees, dict):
            raise Refus(400, "Objet JSON attendu.")
        return donnees

    # --- Réponses ---
    def _envoyer(self, code, corps, type_contenu, page_interface=False):
        self.send_response(code)
        self.send_header("Content-Type", type_contenu)
        self.send_header("Content-Length", str(len(corps)))
        self._entetes_communs(page_interface)
        self.end_headers()
        self.wfile.write(corps)

    def _entetes_communs(self, page_interface=False):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        if page_interface:
            self.send_header("Content-Security-Policy", CSP_PAGE)
            self.send_header("X-Frame-Options", "DENY")

    def _json(self, code, donnees):
        self._envoyer(code, json.dumps(donnees, ensure_ascii=False).encode(), "application/json; charset=utf-8")

    def _fichier_resultat(self, relatif):
        """Fichier sous la racine des résultats : chemin décodé, résolu (liens symboliques suivis),
        puis refusé s'il sort de la racine ; fichiers et dossiers cachés exclus."""
        relatif = urllib.parse.unquote(relatif)
        if not relatif or "\x00" in relatif:
            raise Refus(404, "Fichier introuvable.")
        cible = (RESULTATS / relatif).resolve()
        if not cible.is_relative_to(RESULTATS) or cible == RESULTATS:
            raise Refus(403, "Chemin refusé.")
        if any(p.startswith(".") for p in cible.relative_to(RESULTATS).parts) or not cible.is_file():
            raise Refus(404, "Fichier introuvable.")
        type_contenu = mimetypes.guess_type(cible.name)[0] or "application/octet-stream"
        if type_contenu.startswith("text/") or type_contenu in ("application/json", "image/svg+xml"):
            type_contenu += "; charset=utf-8"
        with cible.open("rb") as f:
            self.send_response(200)
            self.send_header("Content-Type", type_contenu)
            self.send_header("Content-Length", str(os.fstat(f.fileno()).st_size))
            self._entetes_communs()
            if not type_contenu.startswith("application/pdf"):   # le lecteur PDF de Chrome supporte mal une CSP stricte
                self.send_header("Content-Security-Policy", CSP_RESULTAT)  # aucun script dans les rapports servis
            self.end_headers()
            shutil.copyfileobj(f, self.wfile)

    def _flux(self, params):
        """Journal et états du travail courant en Server-Sent Events, jusqu'à sa fin."""
        travail = self.server.travail
        if travail is None:
            raise Refus(404, "Aucun audit lancé depuis l'ouverture de l'interface.")
        depuis = 0
        dernier = re.fullmatch(r"(\d+):(\d+)", self.headers.get("Last-Event-ID", ""))
        if dernier and int(dernier.group(1)) == travail.id:   # reconnexion automatique du navigateur
            depuis = int(dernier.group(2)) + 1
        elif params.get("depuis", [""])[0].isdigit():
            depuis = int(params["depuis"][0])
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self._entetes_communs()
        self.end_headers()
        version_envoyee = -1
        while True:
            with travail.cond:
                if depuis >= travail.decalage + len(travail.lignes) and travail.version == version_envoyee and travail.en_cours():
                    travail.cond.wait(timeout=15)
                debut = max(depuis, travail.decalage)
                lignes = travail.lignes[debut - travail.decalage:]
                depuis = debut + len(lignes)
                version, resume, fini = travail.version, travail.resume(), not travail.en_cours()
            morceaux = [f"id: {travail.id}:{debut + i}\nevent: journal\ndata: {json.dumps({'n': debut + i, 'texte': l}, ensure_ascii=False)}\n\n"
                        for i, l in enumerate(lignes)]
            if version != version_envoyee:
                morceaux.append(f"event: etat\ndata: {json.dumps(resume, ensure_ascii=False)}\n\n")
                version_envoyee = version
            if fini:
                morceaux.append(f"event: fin\ndata: {json.dumps(resume, ensure_ascii=False)}\n\n")
            self.wfile.write(("".join(morceaux) or ": attente\n\n").encode())
            if fini:
                return

    def _etat(self, rafraichir):
        with self.server.verrou_etat:
            if self.server.installation is None or rafraichir:
                self.server.installation = etat_installation()
            return self.server.installation

    # --- Actions (POST) ---
    def _lancer_audit(self, donnees):
        url = valider_url(donnees.get("url"))
        noms = [o["nom"] for o in self.server.outils]
        choisis = donnees.get("outils")
        if not isinstance(choisis, list) or not choisis or not all(isinstance(o, str) for o in choisis):
            raise Refus(400, "Choisir au moins un outil.")
        inconnus = [o for o in choisis if o not in noms]
        if inconnus:
            raise Refus(400, f"Outil inconnu : {', '.join(inconnus)[:200]}.")
        maxi, voisins = valider_max(donnees.get("max")), valider_voisins(donnees.get("voisins"))
        dossier = RESULTATS / domaine(url) / dt.date.today().isoformat()
        if dossier_occupe(dossier):
            raise Refus(409, "Un audit de ce site est déjà en cours aujourd'hui, lancé hors de l'interface : attendre sa fin.")
        commande = [str(RACINE / "bin/tout"), url, "--dossier", str(dossier)]
        sans = [n for n in noms if n not in choisis]
        if sans:
            commande += ["--sans", ",".join(sans)]
        if maxi:
            commande += ["--max", str(maxi)]
        if voisins:
            commande += ["--voisins", voisins]
        return self.server.demarrer("audit", url, dossier, [n for n in noms if n in choisis] + ["synthese"], commande)

    def _arreter(self, _donnees):
        travail = self.server.travail
        if not travail or not travail.arreter():
            raise Refus(409, "Aucun audit en cours.")
        return travail.resume()

    def _regenerer_pdf(self, donnees):
        d = dossier_audit(donnees.get("domaine"), donnees.get("date"))
        if dossier_occupe(d):
            raise Refus(409, "Un audit est en cours dans ce dossier : attendre sa fin avant de regénérer la synthèse.")
        try:
            url = valider_url((d / "site.txt").read_text(encoding="utf-8").strip())
        except OSError:
            raise Refus(404, "site.txt absent : adresse du site inconnue pour cet audit.") from None
        return self.server.demarrer("pdf", url, d, ["synthese"], [str(RACINE / "bin/synthese"), url, "--dossier", str(d)])

    def _ouvrir_dossier(self, donnees):
        d = dossier_audit(donnees.get("domaine"), donnees.get("date"))
        if not shutil.which("xdg-open"):
            raise Refus(501, "xdg-open introuvable : ouvrir le dossier à la main.")
        subprocess.Popen(["xdg-open", str(d)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
        return {"dossier": str(d)}


# --- Lancement ---------------------------------------------------------------------------------
def ouvrir_serveur(premier):
    adresse, port = adresse_dediee(), premier
    while port < min(premier + PORTS_ESSAYES, 65536):
        try:
            return Serveur(adresse, port)
        except OSError as e:
            if e.errno == errno.EADDRNOTAVAIL and adresse != "127.0.0.1":
                adresse = "127.0.0.1"      # système qui ne route pas tout 127.0.0.0/8 : repli, même port
                continue
            if e.errno != errno.EADDRINUSE:
                raise
            port += 1                      # port occupé : on essaie le suivant
    sys.exit(f"Aucun port libre entre {premier} et {premier + PORTS_ESSAYES - 1}.")


def ouvrir_navigateur(url):
    """Fenêtre d'application du navigateur du kit (profil dédié), sinon navigateur par défaut."""
    if os.access(CHROME, os.X_OK):
        PROFIL.mkdir(parents=True, exist_ok=True)
        commande = [CHROME, f"--app={url}", f"--user-data-dir={PROFIL}", "--no-first-run", "--no-default-browser-check"]
    elif shutil.which("xdg-open"):
        commande = ["xdg-open", url]
    else:
        print("Aucun navigateur trouvé : ouvrir l'adresse ci-dessus.", flush=True)
        return None
    return subprocess.Popen(commande, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                            start_new_session=True)


def principal(argv):
    p = argparse.ArgumentParser(prog="bin/interface", description="Interface graphique du kit d'audit web.")
    p.add_argument("--port", type=int, default=8710)
    p.add_argument("--sans-navigateur", action="store_true")
    args = p.parse_args(argv)
    serveur = ouvrir_serveur(args.port)
    print(f"Interface du kit d'audit web : {serveur.adresse_ouverture()}\nRésultats : {RESULTATS}\nCtrl+C pour arrêter.", flush=True)
    navigateur = None if args.sans_navigateur else ouvrir_navigateur(serveur.adresse_ouverture(unique=True))
    for sig in (signal.SIGTERM, signal.SIGHUP):   # kill PID, terminal fermé : même arrêt propre que Ctrl+C
        signal.signal(sig, lambda *_: sys.exit(0))
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        # l'audit d'abord : après SIGHUP, écrire dans le terminal disparu peut lever une erreur
        arrete = bool(serveur.travail and serveur.travail.arreter(attendre=True))
        serveur.server_close()
        try:
            print("\nArrêt de l'interface." + ("\nAudit en cours arrêté." if arrete else ""), flush=True)
        except OSError:
            pass
        if navigateur and navigateur.args[0] == CHROME and navigateur.poll() is None:
            navigateur.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(principal(sys.argv[1:]))
