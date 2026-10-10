# Kit d'audit web libre

Une commande par audit, l'adresse du site en paramètre, les résultats rangés par site et par date,
et une synthèse PDF produite automatiquement. Les outils sont libres ou gratuits ; les versions
sont figées pour que deux audits soient comparables.

Origine : scripts écrits pour un audit réel de site (octobre 2026), puis généralisés.

## Installation

```bash
./installer.sh              # dépendances Node, Python et lychee (sans sudo) + vérification des prérequis
./installer.sh --verifier   # contrôle seulement
```

Prérequis du système : Google Chrome, Node ≥ 22.19, Python 3 avec `venv`, `curl`, `dig`, `openssl`.
Facultatifs : Screaming Frog SEO Spider (pour `bin/sf-crawl`) et `docker buildx` (pour construire
l'image SEOnaut).

La clé PageSpeed Insights se range **hors du dépôt**, dans `~/.config/audit-kit/secrets.env`
(droits 600) : `PSI_API_KEY=…`. Elle est lue sans exécuter le fichier, et transmise dans un en-tête
HTTP : elle n'apparaît ni dans les URL, ni dans la liste des processus, ni dans les journaux.

## Utilisation

```bash
bin/tout https://exemple.fr/                       # audit complet + synthèse
bin/tout exemple.fr --sans psi,unlighthouse        # en sautant des étapes
bin/liens exemple.fr --max 200                     # une seule commande
bin/synthese exemple.fr                            # refaire la synthèse du jour
```

Chaque commande affiche son mode d'emploi avec `--help`. Options communes : `--dossier` (dossier
d'audit imposé), et selon les commandes `--pages FICHIER` (liste d'URL) et `--max N`.

| Commande | Outil | Ce qu'elle produit |
|---|---|---|
| `entetes` | curl, openssl, dig, RDAP | en-têtes de sécurité, redirections, certificat, DNS (SPF, DMARC, DNSSEC, CAA), domaine |
| `sf-crawl` | Screaming Frog 24.3 (gratuit) | 3 passes pour contourner le plafond de 500 URL : crawl, sitemap, toutes les pages HTML connues (par lots) |
| `seo` | advertools 0.18 | crawl complet sans plafond et contrôles : title, description, H1, texte, canonique, doublons, orphelines |
| `inventaire` | Python | contenus (API WordPress si disponible), métadonnées, liens, poids des images, vidéos YouTube |
| `liens` | lychee 0.24.2 | liens cassés ; les services anti-robots sont listés à part, « à vérifier dans un navigateur » |
| `accessibilite` | pa11y-ci 5.0.0 + axe | problèmes WCAG 2.1 AA par page et par règle |
| `lighthouse` | Lighthouse 13.5.0 | mesures locales, mobile et ordinateur, sur 6 pages types |
| `psi` | API PageSpeed Insights | mêmes mesures chez Google, plus les données de vrais visiteurs (CrUX) si elles existent |
| `unlighthouse` | Unlighthouse 0.19.1 | Lighthouse sur toutes les pages, rapport consultable |
| `captures` | Chrome headless | captures ordinateur (1366 px) et mobile (390 px) des pages types |
| `synthese` | Python + Chrome | `synthese/synthese.html` et `synthese.pdf` |

Les pages types sont l'accueil, les quatre pages les moins profondes du sitemap et une page
profonde (un article, en général). Les commandes qui parcourent tout le site réutilisent la liste
des pages HTML trouvée par `sf-crawl` (`urls_html.txt`), sinon celle de `seo`, sinon le sitemap.

## Résultats

```
resultats/<domaine>/<AAAA-MM-JJ>/
├── site.txt, urls_sitemap.txt, urls_html.txt, journal.txt, manifeste.json
├── entetes/  sf/  seo/  inventaire/  liens/  accessibilite/
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
  partage) ; utilisé par `sf-crawl` et `seo`.
- `config/pa11y.json` : norme, moteur axe, une page à la fois (plus stable que deux).
- `config/unlighthouse.config.mjs` : mobile avec bridage, aucun échantillonnage des pages.

## Limites connues

- Screaming Frog gratuit : 500 URL par crawl, **liens externes et ressources compris** ; le mode
  liste contourne ce plafond pour les pages, par lots de 400. Les exports sont nommés dans la
  langue de l'interface (le kit lit le français et l'anglais).
- Les tests automatiques d'accessibilité ne trouvent qu'une partie des problèmes.
- advertools ne distingue pas un `alt` absent d'un `alt=""` décoratif ; axe, si.
- Ne pas créer ni supprimer de réseaux Docker (`docker compose up/down`) pendant un audit :
  Chrome interrompt alors ses chargements (`ERR_NETWORK_CHANGED`), ce qui fausse Lighthouse,
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
