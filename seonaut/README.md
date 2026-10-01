# SEOnaut avec garde-fous

[SEOnaut](https://github.com/StJudeWasHere/seonaut) (licence MIT) est un crawler SEO avec interface
web (Go + base MySQL). Ce dossier le déploie **en Docker**, avec **MariaDB 11.4** à la place de
MySQL 8.4 (beaucoup plus léger), sur un petit serveur : aujourd'hui un Raspberry Pi 3 (1 Go de
RAM partagé avec d'autres services), demain une machine plus puissante.

## Principe

| Fichier | Rôle |
|---|---|
| `compose.yaml` | base sans contrainte, valable partout |
| `compose.garde-fous.yaml` | contraintes du Pi : mémoire plafonnée sans swap, priorité processeur basse, SEOnaut sacrifié en premier en cas de manque de mémoire, MariaDB réglé au minimum (`mariadb/garde-fous.cnf`) |
| `.env` | `COMPOSE_FILE=compose.yaml:compose.garde-fous.yaml` active les garde-fous ; **`COMPOSE_FILE=compose.yaml` les lève** |

Garde-fous en vigueur : base 192 Mo, application 256 Mo (`GOMEMLIMIT=200MiB`), `cpu_shares` 256,
`oom_score_adj` 800 et 900, `restart: "no"` (démarrage à la demande). Le port 9100 n'écoute que sur
127.0.0.1 : on y accède par tunnel SSH.

L'image est construite **sur le poste**, jamais sur le Pi, pour amd64 et arm64, par compilation
croisée (`Dockerfile.croise`) : aucune émulation n'est nécessaire. SEOnaut n'ayant pas de version
publiée, le commit `880b312` est épinglé et sert d'étiquette (`seonaut-kit:880b312`).

## Mise en place (depuis le poste)

```bash
sudo apt install docker-buildx          # une fois
seonaut/construire-image.sh             # image amd64 + arm64
seonaut/deployer.sh                     # fichiers + image vers l'hôte « server » (SEONAUT_HOTE=…)
seonaut/distant.sh initialiser          # crée .env sur l'hôte (mots de passe aléatoires, droits 600)
```

## Utilisation

```bash
seonaut/distant.sh demarrer     # contrôles mémoire avant/après, arrêt de sécurité si besoin
seonaut/distant.sh tunnel       # puis http://localhost:9100 (créer un compte au premier accès)
seonaut/distant.sh arreter      # conteneurs supprimés, données conservées
seonaut/distant.sh etat         # mémoire, conteneurs, garde-fous, taille des volumes
```

Sur l'hôte, les mêmes scripts se lancent directement : `cd ~/seonaut && ./demarrer.sh`.

`demarrer.sh`, quand les garde-fous sont actifs, **refuse de démarrer** si la mémoire disponible
est sous `SEUIL_DEMARRAGE_MO` (350 Mo), puis **arrête SEOnaut de lui-même** si elle passe sous
`SEUIL_ALERTE_MO` (100 Mo) ou si un autre conteneur s'est arrêté ou est devenu « unhealthy ».

Sur le Pi, SEOnaut convient aux **petits sites** (quelques centaines de pages). Pour un gros site,
lancer la même configuration sur le poste, sans garde-fous :

```bash
cd seonaut && ./initialiser.sh --sans-garde-fous && ./demarrer.sh
```

## Sauvegarde et migration

```bash
seonaut/distant.sh sauvegarder   # mariadb-dump compressé dans ~/seonaut/sauvegardes/ sur l'hôte
seonaut/distant.sh rapatrier     # copie les sauvegardes sur le poste (seonaut/sauvegardes/, non versionné)
```

La sauvegarde est logique (SQL) : elle ne dépend ni de l'architecture ni de la version de MariaDB.
Pour passer sur la nouvelle machine :

1. `SEONAUT_HOTE=nouvelle seonaut/deployer.sh`, puis `initialiser.sh --sans-garde-fous` sur la
   nouvelle machine (ou, si l'on reprend l'ancien `.env`, y mettre `COMPOSE_FILE=compose.yaml`) ;
2. `./demarrer.sh`, puis `./restaurer.sh sauvegardes/seonaut_….sql.gz` ;
3. arrêter SEOnaut sur le Pi ; les volumes `seonaut_db` et `seonaut_archives` peuvent y être
   supprimés une fois la migration vérifiée (`docker volume rm`).
