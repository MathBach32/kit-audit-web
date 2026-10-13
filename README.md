# Kit d'audit web libre

Une commande par audit, l'adresse du site en paramètre, les résultats rangés par site et par date,
et une synthèse PDF produite automatiquement. Les outils sont libres, à deux exceptions près : le
navigateur Google Chrome (s'il est préféré à Chromium) et le service PageSpeed Insights de Google
(facultatif). Les versions sont figées pour que deux audits soient comparables.

Origine : scripts écrits pour un audit réel de site (octobre 2026), puis généralisés.

## Installation

```bash
./installer.sh              # dépendances Node, Python et lychee (sans sudo) + vérification des prérequis
./installer.sh --verifier   # contrôle seulement
```

Dans une session graphique, l'installation ajoute aussi l'entrée **« Kit d'audit web »** au menu
des applications (catégorie Programmation sous Linux Mint) : c'est le point de départ d'un audit,
voir [Interface graphique](#interface-graphique).

Prérequis du système : Google Chrome ou Chromium (voir [Navigateur](#navigateur)), Node ≥ 22.19,
Python 3 avec `venv`, `curl`, `dig`, `openssl`. Facultatif : `docker buildx` (pour construire
l'image SEOnaut).

Node est celui du `PATH` s'il est assez récent, sinon une version installée par **nvm** (`NVM_DIR`,
sinon `~/.nvm`), la plus récente de la version de `.nvmrc` d'abord (`lib/kit.py`). nvm ne se charge
que dans un terminal : c'est ainsi que le kit lancé depuis le menu des applications, ou par cron,
trouve son Node. `./installer.sh` affiche le Node retenu. Avec un autre gestionnaire de versions
(fnm, Volta…), rendre `node` accessible hors d'un terminal, par exemple par le `PATH` de
`~/.profile`.

La clé PageSpeed Insights se range **hors du dépôt**, dans `~/.config/audit-kit/secrets.env`
(droits 600) : `PSI_API_KEY=…`. Elle est lue sans exécuter le fichier, et transmise dans un en-tête
HTTP : elle n'apparaît ni dans les URL, ni dans la liste des processus, ni dans les journaux.

## Navigateur

Le kit fonctionne avec **Google Chrome ou Chromium**, au choix. Ce sont deux logiciels distincts :
Chrome est construit par Google à partir de Chromium, mais n'installe pas de commande `chromium`.
L'un ou l'autre suffit.

Le navigateur est détecté automatiquement (`lib/kit.py`), dans cet ordre : `google-chrome-stable`,
`google-chrome`, `chromium`, `/snap/bin/chromium`, `chromium-browser`, `/usr/lib/chromium/chromium`,
`/opt/google/chrome/chrome`. Un candidat n'est retenu que s'il répond à `--version` par une version
de Chrome ou de Chromium : sur Ubuntu, `chromium-browser` peut n'être qu'un script qui propose
d'installer le snap, ou qui renvoie vers lui. `./installer.sh` affiche le navigateur retenu, et
`manifeste.json` (clé « Navigateur ») celui de chaque audit ; le Chromium du snap s'y signale par sa
version (« Chromium … snap »).

Pour en imposer un : `CHROME_PATH=/chemin/du/navigateur bin/tout exemple.fr`. Le chemin imposé est
utilisé tel quel : s'il n'est pas exécutable, ou s'il ne répond pas à `--version` comme Google Chrome
ou Chromium, les commandes s'arrêtent au lieu de se rabattre sur un autre navigateur. Pour un autre
navigateur de la famille Chromium (Brave, Microsoft Edge…), non testé avec le kit, ajouter
`KIT_NAVIGATEUR_LIBRE=1` : le chemin imposé est alors accepté sans contrôle de version.

Chromium en **snap** (Ubuntu) est confiné : il ne voit ni les dossiers cachés de `$HOME`, ni le
`/tmp` de l'hôte. Les captures et le PDF de synthèse, écrits par le navigateur lui-même, doivent donc
rester sous `$HOME`, hors dossier caché : c'est le cas par défaut quand le kit y est installé. Ne pas
diriger `KIT_AUDIT_RESULTATS` ni `--dossier` vers `/tmp`.

## Interface graphique

Depuis le menu des applications : entrée **« Kit d'audit web »**. Sinon, en ligne de commande :

```bash
bin/interface                     # ouvre l'interface dans une fenêtre du navigateur du kit
bin/interface --sans-navigateur   # affiche seulement l'adresse, à ouvrir soi-même
outils/lanceur.sh                 # ajoute (ou remet à jour) l'entrée du menu ; --retirer pour l'enlever
```

L'entrée du menu (`~/.local/share/applications/kit-audit-web.desktop`, norme freedesktop, donc aussi
GNOME, KDE…) lance `bin/interface --lanceur`. L'interface s'arrête alors quand on ferme sa dernière
fenêtre ; si un audit tourne, elle attend sa fin et la signale par une notification. Ses messages
vont dans `~/.cache/kit-audit-web/interface.log`, et une notification avertit si elle s'arrête sur une
erreur. L'entrée contient le chemin du kit : après un déplacement du kit, relancer
`outils/lanceur.sh` (ou `./installer.sh`).

Une seule interface tourne par compte : lancée de nouveau, depuis le menu ou un terminal, elle ouvre
une fenêtre de plus dans celle qui tourne déjà (`--sans-navigateur` démarre au contraire une
interface indépendante).

Une page locale pour lancer un audit (adresse, outils à cocher, nombre maximal de pages, domaines
voisins), suivre son avancement en direct (état et durée de chaque outil, journal), l'arrêter,
parcourir les audits passés (voyants de la synthèse, outils réussis ou en échec), ouvrir les
synthèses HTML et PDF, regénérer une synthèse, ouvrir le dossier d'un audit et vérifier l'installation
(navigateur, versions, clé PSI, `./installer.sh --verifier`). Elle fonctionne hors ligne, en clair
ou en sombre selon le réglage du poste, et sur un écran de téléphone.

Le serveur (`lib/interface.py`, Python sans dépendance) écoute sur une adresse de bouclage tirée au
hasard à chaque lancement (`127.x.y.z`, repli sur `127.0.0.1` si le système ne la permet pas),
port 8710 ou le suivant libre (`--port N` pour en choisir un autre). La fenêtre s'ouvre avec
`$CHROME_PATH --app` dans un profil dédié (`~/.cache/kit-audit-web/interface`), sinon avec
`xdg-open`. Lancée d'un terminal, `Ctrl+C`, `kill` ou la fermeture du terminal arrêtent l'interface,
et l'audit en cours s'il y en a un. La liste des outils vient de `bin/tout --liste-outils` ; les voyants, de
`synthese/voyants.json`, écrit par la synthèse.

Un seul audit à la fois par dossier d'audit, qu'il soit lancé depuis l'interface ou en ligne de
commande : `bin/tout` et `bin/synthese` prennent un verrou (`flock` sur `<dossier>/.verrou`), et
l'interface affiche « En cours hors de l'interface » sur la carte d'un audit lancé dans un
terminal. Le statut final tient compte des outils : « Terminé avec N échec(s) », ou « Échec :
synthèse non produite ». Une synthèse n'est remplacée que si le nouveau PDF a été produit.

Sécurité : l'adresse affichée contient un jeton propre à la session, échangé à l'ouverture contre
un cookie de session `HttpOnly` `SameSite=Strict` (valeur distincte). Comme un cookie ne tient pas
compte du port, l'adresse de bouclage dédiée l'empêche de partir vers les autres services de
`127.0.0.1` ou de `localhost`. Est refusée toute requête sans ce cookie, avec un en-tête `Host`
inattendu (contre le *DNS rebinding*), venue d'une autre page (`Origin`, `Sec-Fetch-Site`) ou,
pour une modification, sans l'en-tête `X-Jeton` (troisième valeur, écrite dans la page) et un
corps JSON. Les commandes sont lancées sans shell, avec des arguments validés ; seuls les fichiers
du dossier des résultats sont servis, sans exécuter de script. Ne pas partager l'adresse affichée :
elle donne accès à l'interface jusqu'à son arrêt.

## Utilisation

```bash
bin/tout https://exemple.fr/                       # audit complet + synthèse
bin/tout exemple.fr --sans psi,unlighthouse        # en sautant des étapes
bin/liens exemple.fr --max 200                     # une seule commande
bin/synthese exemple.fr                            # refaire la synthèse du jour (l'ancienne reste si elle échoue)
```

Chaque commande affiche son mode d'emploi avec `--help`. Options communes : `--dossier` (dossier
d'audit imposé), et selon les commandes `--pages FICHIER` (liste d'URL) et `--max N`.

| Commande | Outil | Ce qu'elle produit |
|---|---|---|
| `entetes` | curl, openssl, dig, RDAP | en-têtes de sécurité, redirections, certificat, DNS (SPF, DMARC, DNSSEC, CAA), domaine |
| `seo` | advertools 0.18 | exploration du site (liens, redirections, pages du sitemap qu'aucun lien n'atteint) et une quarantaine de contrôles SEO |
| `inventaire` | Python | contenus (API WordPress si disponible), métadonnées, liens, poids des images, vidéos YouTube |
| `liens` | lychee 0.24.2 | liens cassés ; les services anti-robots sont listés à part, « à vérifier dans un navigateur » |
| `accessibilite` | pa11y-ci 5.0.0 + axe | problèmes WCAG 2.1 AA par page et par règle |
| `lighthouse` | Lighthouse 13.5.0 | mesures locales, mobile et ordinateur, sur 6 pages types |
| `psi` | API PageSpeed Insights | mêmes mesures chez Google, plus les données de vrais visiteurs (CrUX) si elles existent |
| `unlighthouse` | Unlighthouse 0.19.1 | Lighthouse sur toutes les pages, rapport consultable |
| `captures` | navigateur sans interface | captures ordinateur (1366 px) et mobile (390 px) des pages types |
| `synthese` | Python + navigateur | `synthese/synthese.html` et `synthese.pdf` |

Les pages types sont l'accueil, les quatre pages les moins profondes du sitemap et une page
profonde (un article, en général). Les commandes qui parcourent tout le site réutilisent la liste
des pages HTML trouvée par `seo` (`urls_html.txt` : l'accueil d'abord, puis par profondeur, les
pages orphelines à la fin), sinon le sitemap.

## Exploration et contrôles SEO

`bin/seo` explore le site depuis l'accueil en suivant les liens (respect de `robots.txt`, débit
modéré, environ 2 000 adresses par défaut, réglable avec `--max`). Les redirections sont
enregistrées (`seo/redirections.csv`) puis leurs destinations explorées ; les pages du sitemap
qu'aucun lien n'atteint sont téléchargées à leur tour : ce sont les pages orphelines.

Chaque constat porte un code du catalogue [`config/problemes.csv`](config/problemes.csv) : libellé,
catégorie, gravité (haute, moyenne, basse), explication et correction en langage courant. La
synthèse reprend ce catalogue ; le détail page par page est dans `seo/problemes.csv`. Les contrôles
couvrent les codes de réponse et les soft 404, l'indexation (noindex en balise ou en en-tête,
canonique absente, ailleurs ou cassée, meta refresh, sitemap), les title et descriptions (absents,
en double, longueur en caractères et en pixels), les titres H1 et H2, le texte, les contenus
identiques ou presque, les images sans `alt`, les liens (sans texte, nofollow, vers des
redirections, sans protocole), la profondeur, la lenteur du serveur, les en-têtes de sécurité de
chaque page et la lisibilité des adresses.

Le dossier `tests/site-temoin` contient un petit site dont les défauts sont connus : il déclenche
chacun des contrôles du catalogue. `tests/verifier.sh` le sert sur un port libre, lance un audit
complet (sans PageSpeed Insights) et compare les résultats aux défauts attendus
(`tests/attendus.py`). L'audit tourne comme depuis le menu des applications : le `node` du `PATH`
est hors service, et les commandes doivent retrouver le vrai par nvm. Il vérifie aussi la recherche
de Node (`tests/node.sh`) et, sans écran ni vrai navigateur, l'entrée du menu et le mode lanceur de
l'interface (`tests/lanceur.sh`). À lancer après chaque mise à jour du kit ou de ses dépendances.

## Résultats

```
resultats/<domaine>/<AAAA-MM-JJ>/
├── site.txt, urls_sitemap.txt, urls_html.txt, journal.txt, manifeste.json
├── entetes/  seo/  inventaire/  liens/  accessibilite/
├── lighthouse/  psi/  unlighthouse/  captures/
└── synthese/synthese.pdf
```

Le dossier `resultats/` n'est **jamais versionné** (données des sites audités). On peut le placer
ailleurs avec `KIT_AUDIT_RESULTATS=/chemin`. Relancer une commande le même jour remplace son
sous-dossier.

## Réglages

- `config/lychee.toml` : courtoisie (requêtes simultanées, délais) et **faux positifs anti-robots**
  (Facebook, Instagram, LinkedIn, X, HelloAsso, `wordpress.com/log-in`, `?share=`). Ajouter ici les
  nouveaux cas rencontrés.
- `config/exclusions_pages.txt` : adresses qui ne sont pas des pages (administration, flux,
  partage) ; utilisé par `seo`.
- `config/problemes.csv` : catalogue des constats SEO (libellés, gravités, explications).
- `config/pa11y.json` : norme, moteur axe, une page à la fois (plus stable que deux).
- `config/unlighthouse.config.mjs` : mobile avec bridage, aucun échantillonnage des pages.

## Limites connues

- Les tests automatiques d'accessibilité ne trouvent qu'une partie des problèmes.
- Certains hébergeurs protègent leurs sites contre les robots trop rapides : ils répondent alors par
  des redirections sans fin (307), des 429 ou des 503. `bin/liens` limite donc son débit (deux
  requêtes simultanées et au moins 250 ms d'écart par hôte), garde les cookies de ces protections,
  et classe ces refus « à vérifier » plutôt que « cassés ». S'il est interrompu, il réessaie une
  minute plus tard, plus lentement, puis page par page ; les pages refusées sont listées dans
  `liens/pages_non_verifiees.txt`.
- `bin/seo` lit le HTML envoyé par le serveur, sans exécuter le JavaScript : un site entièrement
  construit dans le navigateur doit être audité avec les outils fondés sur Chrome (Lighthouse,
  Unlighthouse, pa11y).
- Ne pas créer ni supprimer de réseaux Docker (`docker compose up/down`) pendant un audit :
  le navigateur interrompt alors ses chargements (`ERR_NETWORK_CHANGED`), ce qui fausse Lighthouse,
  Unlighthouse et pa11y.
- La règle axe `frame-tested` est classée « à vérifier » : elle signale une iframe (vidéo,
  publicité) que le test n'a pas pu analyser, pas un défaut.
- Dépendances : `package.json` force des versions corrigées de `basic-ftp` et `esbuild`, et fait
  utiliser Lighthouse 13 par `@lhci/utils`, qu'Unlighthouse embarque encore avec Lighthouse 12 et
  Puppeteer 24 (`overrides`) ; cela retire `extract-zip`, abandonné et vulnérable. Pour régénérer
  `package-lock.json`, retirer d'abord ses entrées `node_modules/@lhci/utils/node_modules/*`,
  sinon npm n'applique pas ce réglage. Restent deux alertes sans effet sur le kit, vérifiées en
  supprimant les paquets : `node-forge` ne sert qu'au serveur interactif d'Unlighthouse
  (`listhen`, certificats de test), alors que le kit n'utilise que le mode CI ; `sprintf-js`
  n'est chargé que par l'outil en ligne de commande de `js-yaml` 3, jamais appelé.
- Les voyants de la synthèse sont calculés selon des seuils usuels : ils orientent, ils ne
  remplacent pas la lecture des détails.
- Interface graphique : l'adresse passée au navigateur figure dans sa ligne de commande, lisible par
  les autres comptes du poste (`ps`) ; son jeton est à usage unique et ne sert plus une fois la
  fenêtre ouverte. L'interface est prévue pour un poste personnel. Un audit lancé en ligne de
  commande n'apparaît pas dans le suivi en direct, seulement dans les audits passés (« En cours hors
  de l'interface »). Le verrou ne concerne que `bin/tout` et `bin/synthese` : une commande isolée
  (`bin/lighthouse`…) lancée à la main n'en tient pas compte. Si l'interface est tuée net
  (`kill -9`), `bin/tout` s'arrête aussitôt, mais l'outil en cours ne s'arrête qu'à sa prochaine
  écriture. Les rapports Lighthouse et Unlighthouse, qui ont besoin de JavaScript, ne s'ouvrent pas
  depuis l'interface (scripts bloqués dans les fichiers servis) : les ouvrir depuis le dossier de
  l'audit.

## Vérification et mises à jour automatiques

- **Vérification** (`.github/workflows/verification.yml`) : à chaque proposition de modification,
  à chaque mise à jour de `main` et chaque lundi, la CI installe le kit, lance `tests/verifier.sh`
  avec Google Chrome puis avec Chromium, et construit puis démarre l'image SEOnaut. Toute la
  logique est dans les scripts du dépôt : le fichier de CI n'en est qu'une enveloppe, à transposer
  telle quelle vers GitLab CI ou Forgejo Actions.
- **Mises à jour** (`renovate.json`, `.github/workflows/renovate.yml`) : Renovate, logiciel libre
  auto-hébergé dans la CI, propose le 1er de chaque mois les nouvelles versions (outils Node,
  Python, lychee, actions GitHub, images Docker, commit de SEOnaut), une fois qu'elles ont au moins
  7 jours. Les petites mises à jour sont intégrées automatiquement si la vérification passe ; les
  versions majeures, MariaDB, SEOnaut et les changements de version de Python ou de Node attendent
  une relecture. Le même `renovate.json` sert sur GitLab avec le gabarit officiel
  `renovate-runner`. Renovate utilise le secret `RENOVATE_TOKEN` (jeton personnel classique, droits
  `public_repo` et `workflow`).
- **Après une mise à jour du dépôt local** (`git pull`) : relancer `./installer.sh`, puis
  `tests/verifier.sh` pour vérifier le kit avec le navigateur du poste.

## SEOnaut

Le dossier [`seonaut/`](seonaut/README.md) déploie SEOnaut (crawler SEO avec interface web) en
Docker, avec des garde-fous mémoire pour un petit serveur, faciles à lever.

## Licence

Kit d'audit web — Copyright © 2026 **SIM32** — EURL SERVICES INFORMATIQUES MIELAN 32
(SIRET 991 597 311 00018) — <https://sim32.fr>
Sous licence EUPL — dépôt d'origine : <https://github.com/MathBach32/kit-audit-web>

Le kit est distribué sous la **Licence publique de l'Union européenne (EUPL) v. 1.2**. Texte
officiel en français : [`docs/EUPL-1.2-fr.txt`](docs/EUPL-1.2-fr.txt) ; en anglais :
[`LICENSE`](LICENSE). Toutes les versions linguistiques ont la même valeur (article 13).

Vous pouvez l'utiliser, le modifier et le redistribuer, y compris à des fins commerciales, aux
conditions de la licence, notamment :

- **conserver intactes les mentions** du fichier [`NOTICE`](NOTICE) et des en-têtes de fichiers
  (citation de SIM32 et adresse du dépôt d'origine), et les joindre avec la licence à chaque
  copie (article 5, droit d'attribution) ;
- indiquer dans toute œuvre dérivée qu'elle a été modifiée, avec la date de la modification
  (article 5) ;
- distribuer ou communiquer les œuvres dérivées sous la même licence, en fournissant le code
  source (article 5, clause copyleft) ; la mise à disposition en ligne des fonctions du logiciel
  compte comme une communication (article 1).

Le fichier `seonaut/Dockerfile.croise` est adapté de SEOnaut (licence MIT) : voir
[`LICENCES-TIERCES.md`](LICENCES-TIERCES.md), qui liste aussi les licences des outils appelés.
