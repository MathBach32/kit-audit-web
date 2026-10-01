// Configuration d'Unlighthouse pour bin/unlighthouse (https://unlighthouse.dev/).
// Chrome du système, mesures mobiles avec bridage réseau et processeur (comme PageSpeed Insights),
// aucun échantillonnage des routes dynamiques : toutes les pages de la liste sont mesurées.
export default {
  chrome: { useSystem: true, useDownloadFallback: false },
  puppeteerOptions: {
    executablePath: process.env.CHROME_PATH || '/usr/bin/google-chrome',
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
