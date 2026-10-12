// SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
// Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
// SPDX-License-Identifier: EUPL-1.2
//
// Configuration d'Unlighthouse pour bin/unlighthouse (https://unlighthouse.dev/).
// Navigateur du poste : CHROME_PATH, défini par lib/commun.sh (Google Chrome ou Chromium), sinon la
// détection de chrome-launcher, sans téléchargement. Mesures mobiles avec bridage réseau et processeur
// (comme PageSpeed Insights), aucun échantillonnage des routes dynamiques : toutes les pages de la
// liste sont mesurées.
export default {
  chrome: { useSystem: true, useDownloadFallback: false },
  puppeteerOptions: {
    executablePath: process.env.CHROME_PATH || undefined,
    args: ['--no-sandbox'],
  },
  puppeteerClusterOptions: { maxConcurrency: 4 },
  lighthouseOptions: { locale: 'fr' },
  scanner: {
    device: 'mobile',
    throttle: true,
    samples: 1,
    dynamicSampling: false,
    maxRoutes: Number(process.env.UNLIGHTHOUSE_MAX_ROUTES || 500),
  },
  ci: { buildStatic: true, reporter: 'jsonExpanded' },
}
