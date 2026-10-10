// SPDX-FileCopyrightText: 2026 SIM32 (EURL SERVICES INFORMATIQUES MIELAN 32) <https://sim32.fr>
// Sous licence EUPL v. 1.2 — dépôt d'origine : https://github.com/MathBach32/kit-audit-web
// SPDX-License-Identifier: EUPL-1.2
//
// Interface graphique du kit : onglets, formulaire d'audit, suivi en direct (Server-Sent Events),
// audits passés et état de l'installation. Aucune bibliothèque ; les données reçues sont insérées
// avec textContent, jamais comme du HTML.
"use strict";

const JETON = document.querySelector('meta[name="kit-jeton"]').content;
const ONGLETS = ["nouvel", "suivi", "audits", "installation"];
const ETATS = {   // état d'un outil → [libellé, couleur de pastille]
  attente: ["En attente", "gris"], en_cours: ["En cours", "bleu"], reussi: ["Réussi", "vert"],
  echec: ["Échec", "rouge"], interrompu: ["Interrompu", "orange"],
};
const STATUTS = { en_cours: ["En cours", "bleu"], termine: ["Terminé", "vert"], echec: ["Échec", "rouge"], arrete: ["Arrêté", "orange"] };
const COULEURS = ["vert", "orange", "rouge", "gris"];   // voyants de la synthèse
const $ = (selecteur) => document.querySelector(selecteur);
const journal = $("#journal");
let travail = null, flux = null, enDirect = false, audits = [], installationChargee = false, lignesEnAttente = [];

// --- Outils généraux ---------------------------------------------------------------------------
function el(balise, attributs = {}, ...enfants) {
  const e = document.createElement(balise);
  for (const [nom, valeur] of Object.entries(attributs)) {
    if (valeur === false || valeur === null || valeur === undefined) continue;
    if (nom === "classe") e.className = valeur;
    else if (nom.startsWith("on")) e.addEventListener(nom.slice(2), valeur);
    else e.setAttribute(nom, valeur === true ? "" : valeur);
  }
  for (const enfant of enfants.flat()) if (enfant !== null && enfant !== undefined && enfant !== false) e.append(enfant);
  return e;
}

const pastille = (texte, couleur) => el("span", { classe: `pastille ${couleur}` }, texte);
const cheminUrl = (chemin) => chemin.split("/").map(encodeURIComponent).join("/");
const formatJour = new Intl.DateTimeFormat("fr-FR", { day: "numeric", month: "long", year: "numeric" });
const formatHeure = new Intl.DateTimeFormat("fr-FR", { hour: "2-digit", minute: "2-digit" });

function dateFr(iso) {
  const d = new Date(`${iso}T12:00:00`);
  return Number.isNaN(d.getTime()) ? iso : formatJour.format(d);
}

function duree(secondes) {
  if (secondes === null || secondes === undefined) return "";
  const s = Math.max(0, Math.round(secondes));
  return s < 60 ? `${s}\u00a0s` : `${Math.floor(s / 60)}\u00a0min ${String(s % 60).padStart(2, "0")}\u00a0s`;
}

async function api(chemin, corps) {
  const options = { credentials: "same-origin", cache: "no-store" };
  if (corps !== undefined) {   // modification : jeton dans un en-tête et corps JSON (exigés par le serveur)
    Object.assign(options, { method: "POST", headers: { "Content-Type": "application/json", "X-Jeton": JETON }, body: JSON.stringify(corps) });
  }
  const reponse = await fetch(chemin, options);
  const donnees = await reponse.json().catch(() => ({}));
  if (!reponse.ok) throw new Error(donnees.erreur || `Erreur ${reponse.status}`);
  return donnees;
}

let minuterieAnnonce;
function annoncer(texte) {
  const zone = $("#annonce");
  zone.textContent = texte;
  zone.classList.add("visible");
  clearTimeout(minuterieAnnonce);
  minuterieAnnonce = setTimeout(() => zone.classList.remove("visible"), 4500);
}

// --- Onglets (motif ARIA « tabs » : flèches, Début, Fin) ---------------------------------------
function afficherOnglet(nom, { focus = false } = {}) {
  if (!ONGLETS.includes(nom)) nom = "nouvel";
  for (const n of ONGLETS) {
    const onglet = $(`#onglet-${n}`), actif = n === nom;
    onglet.setAttribute("aria-selected", String(actif));
    onglet.tabIndex = actif ? 0 : -1;
    $(`#panneau-${n}`).hidden = !actif;
  }
  if (focus) $(`#onglet-${nom}`).focus();
  if (location.hash !== `#${nom}`) history.replaceState(null, "", `#${nom}`);
  if (nom === "audits") chargerAudits();
  if (nom === "installation" && !installationChargee) chargerInstallation();
}

function clavierOnglets(evenement) {
  const i = ONGLETS.indexOf(document.activeElement.id.replace("onglet-", ""));
  const cible = { ArrowRight: i + 1, ArrowLeft: i - 1, Home: 0, End: ONGLETS.length - 1 }[evenement.key];
  if (i < 0 || cible === undefined) return;
  evenement.preventDefault();
  afficherOnglet(ONGLETS[(cible + ONGLETS.length) % ONGLETS.length], { focus: true });
}

// --- Nouvel audit ------------------------------------------------------------------------------
async function chargerOutils() {
  const zone = $("#liste-outils");
  try {
    const d = await api("/api/outils");
    zone.replaceChildren(...d.outils.map((o) => {
      const sansCle = o.nom === "psi" && !d.psi_cle;
      return el("label", { classe: "outil" },
        el("input", { type: "checkbox", name: "outils", value: o.nom, checked: !sansCle, "aria-describedby": `desc-${o.nom}` }),
        el("span", {},
          el("span", { classe: "nom" }, o.libelle),
          el("span", { classe: "desc", id: `desc-${o.nom}` }, o.description,
            sansCle ? el("span", { classe: "note" }, "Clé API non configurée (voir l'onglet Installation).") : null)));
    }));
    compterOutils();
  } catch (e) {
    zone.replaceChildren(el("p", { classe: "message erreur" }, `Liste des outils indisponible : ${e.message}`));
  }
}

function casesOutils() {
  return [...document.querySelectorAll('input[name="outils"]')];
}

function compterOutils() {
  const cases = casesOutils();
  $("#compte-outils").textContent = `${cases.filter((c) => c.checked).length} sur ${cases.length} cochés`;
}

async function lancerAudit(evenement) {
  evenement.preventDefault();
  const erreur = $("#erreur-formulaire"), url = $("#url"), bouton = $("#lancer");
  const choisis = casesOutils().filter((c) => c.checked).map((c) => c.value);
  erreur.hidden = true;
  url.removeAttribute("aria-invalid");
  const signaler = (message, champ) => {
    erreur.textContent = message;
    erreur.hidden = false;
    if (champ === url) url.setAttribute("aria-invalid", "true");
    if (champ) champ.focus();
  };
  if (!url.value.trim()) return signaler("Indiquer l'adresse du site.", url);
  if (!choisis.length) return signaler("Cocher au moins un outil.", $("#tout-cocher"));
  bouton.disabled = true;
  try {
    const t = await api("/api/audits", { url: url.value.trim(), outils: choisis, max: $("#max").value, voisins: $("#voisins").value });
    suivre(t);
    afficherOnglet("suivi");
    annoncer("Audit lancé.");
  } catch (e) {
    signaler(e.message, /adresse/i.test(e.message) ? url : null);
  } finally {
    bouton.disabled = false;
  }
}

// --- Suivi en direct ---------------------------------------------------------------------------
function suivre(t) {   // nouveau travail : journal vidé, flux ouvert depuis le début
  journal.replaceChildren();
  lignesEnAttente = [];
  afficherTravail(t);
  ouvrirFlux();
}

function ouvrirFlux() {
  fermerFlux();
  flux = new EventSource("/api/flux");
  flux.addEventListener("etat", (e) => afficherTravail(JSON.parse(e.data)));
  flux.addEventListener("journal", (e) => ajouterLigne(JSON.parse(e.data).texte));
  flux.addEventListener("fin", (e) => {
    fermerFlux();
    const t = JSON.parse(e.data);
    afficherTravail(t);
    if (enDirect) terminer(t);
    enDirect = false;
  });
  flux.onerror = () => {
    if (flux && flux.readyState === EventSource.CONNECTING) $("#indicateur-texte").textContent = "Connexion perdue, nouvelle tentative…";
  };
}

function fermerFlux() {
  if (flux) flux.close();
  flux = null;
}

function terminer(t) {
  const quoi = t.genre === "pdf" ? "Synthèse regénérée" : "Audit terminé";
  annoncer({ termine: `${quoi}.`, arrete: "Audit arrêté.", echec: `${quoi} avec une erreur (code ${t.code}).` }[t.statut] || quoi);
  audits = [];
  if (!$("#panneau-audits").hidden) chargerAudits();
}

function afficherTravail(t) {
  travail = t;
  if (t.statut === "en_cours") enDirect = true;
  const maintenant = Date.now() / 1000, actif = t.statut === "en_cours";
  $("#suivi-vide").hidden = true;
  $("#suivi").hidden = false;
  $("#suivi-genre").textContent = t.genre === "pdf" ? "Regénération de la synthèse" : "Audit complet";
  $("#suivi-site").textContent = t.site;
  const temps = actif ? `en cours depuis ${duree(maintenant - t.debut)}`
    : `terminé à ${formatHeure.format(new Date(t.fin * 1000))}, durée ${duree(t.fin - t.debut)}`;
  $("#suivi-meta").textContent = `Commencé à ${formatHeure.format(new Date(t.debut * 1000))}, ${temps}. Dossier : ${t.dossier}`;
  const [libelle, couleur] = STATUTS[t.statut] || [t.statut, "gris"];
  $("#suivi-statut").replaceWith(el("span", { id: "suivi-statut", classe: `pastille ${couleur}` }, libelle));
  $("#suivi-outils").replaceChildren(...t.outils.map((o) => {
    const [lib, coul] = !actif && o.etat === "attente" ? ["Non lancé", "gris"] : ETATS[o.etat] || [o.etat, "gris"];
    return el("li", { classe: `etape ${o.etat}` },
      el("span", { classe: "nom" }, o.libelle),
      el("span", { classe: "droite" },
        el("span", { classe: "duree" }, o.etat === "en_cours" ? duree(maintenant - o.debut) : duree(o.duree)),
        pastille(lib, coul)));
  }));
  $("#arreter").hidden = !actif;
  const base = t.chemin ? `/resultats/${cheminUrl(t.chemin)}/synthese/` : null;
  for (const [id, fichier, present] of [["#suivi-synthese", "synthese.html", t.synthese], ["#suivi-pdf", "synthese.pdf", t.pdf]]) {
    const lien = $(id);
    lien.hidden = actif || !base || !present;
    if (base) lien.href = `${base}${fichier}?v=${Math.round(t.fin || 0)}`;
  }
  const hote = (() => { try { return new URL(t.site).host; } catch { return t.site; } })();
  $("#indicateur").hidden = !actif;
  $("#indicateur-texte").textContent = t.genre === "pdf" ? `Synthèse en cours : ${hote}` : `Audit en cours : ${hote}`;
  document.title = actif ? `● ${hote} — Kit d'audit web` : "Kit d'audit web";
}

function ajouterLigne(texte) {
  lignesEnAttente.push(texte);
  if (lignesEnAttente.length === 1) requestAnimationFrame(viderLignes);
}

function viderLignes() {   // ajout groupé : un seul calcul de mise en page par image
  const morceau = document.createDocumentFragment();
  for (const texte of lignesEnAttente) {
    const classe = /^\[\d\d:\d\d:\d\d\] === /.test(texte) ? "l-etape"
      : /ERREUR|a échoué/.test(texte) ? "l-erreur" : texte.startsWith("[interface]") ? "l-interface" : null;
    morceau.append(classe ? el("span", { classe }, `${texte}\n`) : document.createTextNode(`${texte}\n`));
  }
  lignesEnAttente = [];
  journal.append(morceau);
  while (journal.childNodes.length > 5000) journal.firstChild.remove();
  if ($("#suivre-fin").checked) journal.scrollTop = journal.scrollHeight;
}

async function arreter() {
  if (!window.confirm("Arrêter l'audit en cours ? Les outils déjà terminés gardent leurs résultats.")) return;
  try {
    afficherTravail(await api("/api/arreter", {}));
    annoncer("Arrêt demandé.");
  } catch (e) {
    annoncer(e.message);
  }
}

// --- Audits passés -----------------------------------------------------------------------------
async function chargerAudits() {
  const zone = $("#liste-audits");
  if (!audits.length) zone.replaceChildren(el("p", { classe: "chargement" }, "Chargement des audits…"));
  try {
    const d = await api("/api/audits");
    audits = d.audits;
    $("#audits-racine").textContent = `Dossier des résultats : ${d.resultats}`;
    rendreAudits();
  } catch (e) {
    zone.replaceChildren(el("p", { classe: "message erreur" }, e.message));
  }
}

function rendreAudits() {
  const zone = $("#liste-audits"), filtre = $("#filtre").value.trim().toLowerCase();
  const liste = audits.filter((a) => !filtre || a.domaine.toLowerCase().includes(filtre) || a.site.toLowerCase().includes(filtre));
  if (!liste.length) {
    zone.replaceChildren(el("div", { classe: "carte vide" }, audits.length ? "Aucun audit ne correspond au filtre."
      : "Aucun audit pour l'instant : lancez-en un depuis l'onglet « Nouvel audit »."));
    return;
  }
  zone.replaceChildren(...liste.map(carteAudit));
}

function resumeOutils(a) {
  const n = a.reussis.length;
  if (!n && !a.echecs.length) return "Manifeste absent : audit incomplet ou lancé commande par commande.";
  return [`${n} outil${n > 1 ? "s" : ""} réussi${n > 1 ? "s" : ""}`,
    a.echecs.length ? el("span", { classe: "echecs" }, ` · échec : ${a.echecs.map((o) => o.libelle).join(", ")}`) : null];
}

function carteAudit(a, rang) {
  const base = `/resultats/${cheminUrl(a.chemin)}/synthese/`, titre = `audit-${rang}`;
  const de = `de ${a.domaine} du ${dateFr(a.date)}`, occupe = Boolean(travail && travail.statut === "en_cours");
  return el("article", { classe: "carte audit", "aria-labelledby": titre },
    el("div", { classe: "audit-tete" },
      el("div", {}, el("h3", { id: titre }, a.domaine), el("time", { datetime: a.date }, dateFr(a.date))),
      a.en_cours ? pastille("En cours", "bleu") : null),
    a.site ? el("p", { classe: "site" }, a.site) : null,
    a.voyants.length
      ? el("dl", { classe: "voyants" }, a.voyants.flatMap((v) => [
        el("dt", {}, v.domaine), el("dd", {}, pastille(v.etat, COULEURS.includes(v.couleur) ? v.couleur : "gris"))]))
      : el("p", { classe: "aide" }, "Voyants indisponibles : regénérer le PDF pour les calculer."),
    a.chiffres.length ? el("div", { classe: "chiffres" }, a.chiffres.slice(0, 4).map((c) =>
      el("div", { classe: "chiffre" }, el("div", { classe: "val" }, c.valeur), el("div", { classe: "lib" }, c.libelle)))) : null,
    el("p", { classe: "resultat-outils" }, resumeOutils(a)),
    el("div", { classe: "pied actions" },
      a.synthese ? el("a", { classe: "bouton petit", href: `${base}synthese.html`, target: "_blank", rel: "noopener", "aria-label": `Ouvrir la synthèse ${de}` }, "Ouvrir la synthèse") : null,
      a.pdf ? el("a", { classe: "bouton petit", href: `${base}synthese.pdf?v=${encodeURIComponent(a.pdf_date || "")}`, target: "_blank", rel: "noopener", "aria-label": `Ouvrir le PDF ${de}` }, "Ouvrir le PDF") : null,
      el("button", { type: "button", classe: "bouton petit", disabled: occupe, "aria-label": `Regénérer le PDF ${de}`, onclick: () => regenerer(a) }, "Regénérer le PDF"),
      el("button", { type: "button", classe: "bouton petit", "aria-label": `Ouvrir le dossier ${de}`, onclick: () => ouvrirDossier(a) }, "Ouvrir le dossier")));
}

async function regenerer(a) {
  try {
    suivre(await api("/api/pdf", { domaine: a.domaine, date: a.date }));
    afficherOnglet("suivi");
    annoncer("Regénération de la synthèse lancée.");
  } catch (e) {
    annoncer(e.message);
  }
}

async function ouvrirDossier(a) {
  try {
    const d = await api("/api/ouvrir-dossier", { domaine: a.domaine, date: a.date });
    annoncer(`Dossier ouvert : ${d.dossier}`);
  } catch (e) {
    annoncer(e.message);
  }
}

// --- Installation ------------------------------------------------------------------------------
function carte(titre, classe, ...contenu) {
  return el("section", { classe: `carte ${classe}` }, el("h3", {}, titre), ...contenu);
}

async function chargerInstallation(rafraichir = false) {
  const zone = $("#installation"), bouton = $("#actualiser-installation");
  installationChargee = true;
  zone.setAttribute("aria-busy", "true");
  bouton.disabled = true;
  zone.replaceChildren(el("div", { classe: "carte triple chargement" }, "Vérification de l'installation en cours (quelques secondes)…"));
  try {
    const d = await api(`/api/etat${rafraichir ? "?rafraichir=1" : ""}`), nav = d.navigateur, ok = d.verification.code === 0;
    zone.replaceChildren(
      carte("Navigateur", "", pastille(nav.executable ? "Trouvé" : "Introuvable", nav.executable ? "vert" : "rouge"),
        el("p", { classe: "valeur" }, nav.version || "version inconnue"), el("p", { classe: "chemin" }, nav.chemin)),
      carte("Clé PageSpeed Insights", "", pastille(d.psi_cle ? "Configurée" : "Non configurée", d.psi_cle ? "vert" : "orange"),
        el("p", { classe: "valeur" }, d.psi_cle ? "PageSpeed Insights disponible" : "PageSpeed Insights indisponible"),
        el("p", { classe: "chemin" }, d.secrets)),
      carte("Dossier des résultats", "", el("p", { classe: "chemin" }, d.resultats),
        el("p", { classe: "aide" }, "Modifiable avec la variable d'environnement KIT_AUDIT_RESULTATS.")),
      carte("Versions des outils", "",
        el("table", { classe: "tableau" },
          el("thead", {}, el("tr", {}, el("th", { scope: "col" }, "Outil"), el("th", { scope: "col" }, "Version"))),
          el("tbody", {}, d.versions.map((v) => el("tr", {}, el("td", {}, v.outil), el("td", {}, v.version || "absent")))))),
      el("section", { classe: "carte double" },
        el("div", { classe: "titre-carte" }, el("h3", {}, "Vérification de l'installation"),
          pastille(ok ? "Tout est prêt" : "Prérequis manquants", ok ? "vert" : "rouge")),
        el("pre", { classe: "sortie", tabindex: "0", "aria-label": "Résultat de installer.sh --verifier" }, d.verification.sortie),
        el("p", { classe: "aide" }, "Résultat de « ./installer.sh --verifier ». Pour installer ce qui manque : « ./installer.sh » dans un terminal.")));
  } catch (e) {
    zone.replaceChildren(el("p", { classe: "message erreur" }, e.message));
  } finally {
    zone.setAttribute("aria-busy", "false");
    bouton.disabled = false;
  }
}

// --- Démarrage ---------------------------------------------------------------------------------
async function demarrer() {
  for (const n of ONGLETS) $(`#onglet-${n}`).addEventListener("click", () => afficherOnglet(n));
  $(".onglets").addEventListener("keydown", clavierOnglets);
  window.addEventListener("hashchange", () => {
    const nom = location.hash.slice(1);
    if (ONGLETS.includes(nom)) afficherOnglet(nom);
  });
  $("#formulaire").addEventListener("submit", lancerAudit);
  $("#liste-outils").addEventListener("change", compterOutils);
  for (const [id, coche] of [["#tout-cocher", true], ["#tout-decocher", false]]) {
    $(id).addEventListener("click", () => { casesOutils().forEach((c) => { c.checked = coche; }); compterOutils(); });
  }
  $("#arreter").addEventListener("click", arreter);
  journal.addEventListener("scroll", () => {
    $("#suivre-fin").checked = journal.scrollHeight - journal.scrollTop - journal.clientHeight < 40;
  });
  $("#filtre").addEventListener("input", rendreAudits);
  $("#actualiser-audits").addEventListener("click", chargerAudits);
  $("#actualiser-installation").addEventListener("click", () => chargerInstallation(true));

  chargerOutils();
  let t = null;
  try {
    t = (await api("/api/statut")).travail;
  } catch (e) {
    annoncer(e.message);
  }
  if (t) {   // travail en cours ou dernier travail terminé : journal relu depuis le début
    afficherTravail(t);
    ouvrirFlux();
  }
  const demande = location.hash.slice(1);
  afficherOnglet(ONGLETS.includes(demande) ? demande : t && t.statut === "en_cours" ? "suivi" : "nouvel");
  setInterval(() => { if (travail && travail.statut === "en_cours") afficherTravail(travail); }, 1000);
}

demarrer();
