#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
# Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
# SPDX-License-Identifier: EUPL-1.2
"""Serveur du site témoin (tests/site-temoin) : fichiers statiques, plus les cas qu'un simple
serveur de fichiers ne sait pas produire (redirections, délai, en-tête X-Robots-Tag, 404).

  python3 tests/serveur_temoin.py [PORT]     (défaut 8765 ; 0 = port libre, affiché au démarrage)

« {{base}} » est remplacé dans les fichiers texte par l'adresse du serveur (http://hôte:port).
"""
import sys
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

RACINE = Path(__file__).resolve().parent / "site-temoin"
REDIRECTIONS = {"/ancienne-page": "/actualites.html", "/Page_Ancienne.html": "/a-propos/"}
DELAIS = {"/lente.html": 2.0}
ENTETES = {"/x-robots.html": {"X-Robots-Tag": "noindex"}}
TYPES = {".html": "text/html; charset=utf-8", ".xml": "application/xml", ".txt": "text/plain; charset=utf-8",
         ".svg": "image/svg+xml", ".pdf": "application/pdf"}


class Gestionnaire(SimpleHTTPRequestHandler):
    def log_message(self, *args):  # silencieux : le kit a ses propres journaux
        pass

    def do_HEAD(self):
        self.repondre(corps=False)

    def do_GET(self):
        self.repondre(corps=True)

    def repondre(self, corps):
        chemin = self.path.split("?", 1)[0].split("#", 1)[0]
        time.sleep(DELAIS.get(chemin, 0))
        if chemin in REDIRECTIONS:
            self.send_response(301)
            self.send_header("Location", REDIRECTIONS[chemin])
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        fichier = (RACINE / chemin.lstrip("/")).resolve()
        if fichier.is_dir():
            fichier = fichier / "index.html"
        if RACINE not in fichier.parents or not fichier.is_file():
            contenu = "<!doctype html><html lang=\"fr\"><title>Erreur 404</title><h1>Page introuvable</h1></html>".encode()
            self.envoyer(404, "text/html; charset=utf-8", contenu, corps)
            return
        contenu = fichier.read_bytes()
        type_ = TYPES.get(fichier.suffix, "application/octet-stream")
        if type_.startswith(("text/", "application/xml")):
            contenu = contenu.replace(b"{{base}}", f"http://{self.headers.get('Host', 'localhost')}".encode())
        self.envoyer(200, type_, contenu, corps, ENTETES.get(chemin, {}))

    def envoyer(self, code, type_, contenu, corps, entetes=None):
        self.send_response(code)
        self.send_header("Content-Type", type_)
        self.send_header("Content-Length", str(len(contenu)))
        self.send_header("X-Content-Type-Options", "nosniff")
        for k, v in (entetes or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if corps:
            self.wfile.write(contenu)


if __name__ == "__main__":
    serveur = ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8765), Gestionnaire)
    print(f"site témoin : http://127.0.0.1:{serveur.server_address[1]}/", flush=True)
    try:
        serveur.serve_forever()
    except KeyboardInterrupt:
        pass
