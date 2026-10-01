# Licences tierces

Le kit est sous licence Apache 2.0 (voir `LICENSE` et `NOTICE`). Il contient un fichier dérivé
d'un logiciel tiers, dont la licence est reproduite ci-dessous.

## SEOnaut — `seonaut/Dockerfile.croise`

Adapté du `Dockerfile` de [SEOnaut](https://github.com/StJudeWasHere/seonaut) (commit `880b312`)
pour la compilation croisée. SEOnaut lui-même n'est pas inclus dans ce dépôt : ses sources sont
clonées au moment de la construction de l'image (`seonaut/construire-image.sh`).

```
MIT License

Copyright (c) 2022 SEOnaut

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Outils utilisés sans être inclus

Les outils appelés par le kit sont installés séparément, chacun sous sa propre licence :
Lighthouse (Apache-2.0), Unlighthouse (MIT), pa11y-ci (LGPL-3.0), lychee (Apache-2.0 ou MIT),
advertools (MIT), MariaDB (GPL-2.0, image Docker officielle). Screaming Frog SEO Spider est un
logiciel propriétaire, utilisé ici dans sa version gratuite.
