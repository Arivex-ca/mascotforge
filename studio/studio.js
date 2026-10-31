/* MascotForge : Studio. Vanilla JS, aucune dépendance.
   Parle au backend via le contrat /api/* (même origine, page servie à /). */
"use strict";

var STATUTS_ETAT = {
  queued:  "En attente",
  running: "En cours…",
  done:    "Terminé",
  failed:  "Échec"
};

var NOM_VALIDE = /^[a-z][a-z0-9-]{0,31}$/;

var characterId = null;
var jobId = null;
var intervallePoll = null;
var presets = null;       // réponse de /api/presets
var etatsEdites = [];     // [{ name, prompt, loop }]
var apercuFichierUrl = null; // URL locale de l'image choisie, avant l'envoi

function $(id) { return document.getElementById(id); }

/* ---------- Bandeau d'erreur ---------- */

function afficherBandeau(message, type) {
  var bandeau = $("bandeau-erreur");
  bandeau.classList.remove("avertissement");
  if (type === "avertissement") { bandeau.classList.add("avertissement"); }
  $("bandeau-texte").textContent = message;
  bandeau.classList.remove("cache");
}

function cacherBandeau() { $("bandeau-erreur").classList.add("cache"); }

/* ---------- Boutons occupés (spinner + désactivé) ---------- */

function occuper(bouton, texte) {
  bouton.dataset.texte = bouton.textContent;
  bouton.textContent = texte;
  bouton.disabled = true;
  bouton.classList.add("occupe");
  bouton.setAttribute("aria-busy", "true");
}

function liberer(bouton) {
  if (bouton.dataset.texte) { bouton.textContent = bouton.dataset.texte; }
  bouton.disabled = false;
  bouton.classList.remove("occupe");
  bouton.removeAttribute("aria-busy");
}

/* ---------- Appels API ---------- */

async function api(chemin, options) {
  var reponse;
  try {
    reponse = await fetch(chemin, options);
  } catch (e) {
    return { statut: 0, corps: null, injoignable: true };
  }
  var corps = null;
  try { corps = await reponse.json(); } catch (e) { corps = null; }
  return { statut: reponse.status, corps: corps, injoignable: false };
}

function gererErreurReseau(resultat, action) {
  if (resultat.injoignable) {
    afficherBandeau(
      "Le backend ne répond pas pendant « " + action + " » : " +
      "vérifie qu'il est démarré puis réessaie.",
      "erreur"
    );
    return true;
  }
  return false;
}

/* Le backend écrit des messages en français dans `detail` : on les montre. */
function messageErreur(resultat, parDefaut) {
  var detail = resultat.corps && resultat.corps.detail;
  if (typeof detail === "string" && detail) { return detail; }
  return parDefaut + " (erreur " + resultat.statut + ").";
}

/* ---------- Verrouillage des étapes ---------- */

function deverrouiller(idSection) {
  var section = $(idSection);
  section.classList.remove("verrouillee");
  var boutons = section.querySelectorAll("button");
  for (var i = 0; i < boutons.length; i++) { boutons[i].disabled = false; }
}

function verrouiller(idSection) {
  var section = $(idSection);
  section.classList.add("verrouillee");
  var boutons = section.querySelectorAll("button");
  for (var i = 0; i < boutons.length; i++) { boutons[i].disabled = true; }
}

/* ---------- Compteur de coût ---------- */

function formaterMontant(valeur) {
  if (typeof valeur !== "number" || isNaN(valeur)) { return "…"; }
  return valeur.toLocaleString("fr-FR", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
  }) + " $";
}

async function rafraichirCout() {
  var r = await api("/api/cost");
  if (gererErreurReseau(r, "lecture du coût")) { return; }
  if (r.statut !== 200 || !r.corps) {
    $("cout-depense").textContent = "indisponible";
    $("cout-plafond").textContent = "";
    $("cout-mascottes").textContent = "";
    return;
  }
  $("cout-depense").textContent = formaterMontant(r.corps.spent_usd);
  $("cout-plafond").textContent = formaterMontant(r.corps.cap_usd);
  var nb = r.corps.mascots_completed;
  var reserve = r.corps.reserved_usd > 0 ? " · " + formaterMontant(r.corps.reserved_usd) + " réservés" : "";
  $("cout-mascottes").textContent =
    (typeof nb === "number" ? nb : "…") + " mascotte(s) terminée(s)" + reserve;
}

/* ---------- Santé au chargement ---------- */

async function verifierSante() {
  var r = await api("/api/health");
  if (gererErreurReseau(r, "vérification de santé")) { return; }
  if (r.statut !== 200 || !r.corps || !r.corps.ok) {
    afficherBandeau(
      "Le backend ne répond pas correctement : vérifie qu'il est démarré puis recharge la page.",
      "erreur"
    );
    return;
  }
  if (!r.corps.fal_key_configured) {
    afficherBandeau(
      "Clé FAL non configurée : la génération est désactivée tant que la clé " +
      "n'est pas ajoutée côté backend. Le studio reste consultable.",
      "avertissement"
    );
  } else if (!r.corps.ffmpeg_available) {
    afficherBandeau(
      "ffmpeg est introuvable côté backend : les mascottes garderont leur fond. " +
      "Installe ffmpeg pour obtenir un fond transparent.",
      "avertissement"
    );
  }
}

/* ---------- Étape 1 : onglets ---------- */

function basculerOnglet(versPrompt) {
  $("onglet-upload").classList.toggle("actif", !versPrompt);
  $("onglet-prompt").classList.toggle("actif", versPrompt);
  $("onglet-upload").setAttribute("aria-selected", String(!versPrompt));
  $("onglet-prompt").setAttribute("aria-selected", String(versPrompt));
  $("panneau-upload").classList.toggle("cache", versPrompt);
  $("panneau-prompt").classList.toggle("cache", !versPrompt);
}

/* ---------- Étape 1 : personnage ---------- */

function majApercuFichier(fichier) {
  var img = $("apercu-fichier");
  if (apercuFichierUrl) {
    URL.revokeObjectURL(apercuFichierUrl);
    apercuFichierUrl = null;
  }
  if (!fichier) {
    img.removeAttribute("src");
    img.classList.add("cache");
    return;
  }
  apercuFichierUrl = URL.createObjectURL(fichier);
  img.src = apercuFichierUrl;
  img.alt = "Aperçu de " + fichier.name;
  img.classList.remove("cache");
}

function personnagePret(id, imageUrl, origine) {
  characterId = id;
  var img = $("img-personnage");
  img.src = imageUrl;
  img.alt = "Aperçu du personnage (" + origine + ")";
  $("apercu-personnage").classList.remove("cache");
  $("info-personnage").textContent =
    "Personnage prêt (" + origine + "). Choisis ses états à l'étape 2.";
  reinitialiserJob();
  deverrouiller("etape-2");
  $("btn-relancer").classList.add("cache");
  majEstimation();
  cacherBandeau();
}

function reinitialiserJob() {
  arreterPoll();
  jobId = null;
  history.replaceState(null, "", location.pathname);
  $("statut-job").textContent = "";
  $("liste-etats").innerHTML = "";
  $("scene").innerHTML = "";
  $("controles-etats").innerHTML = "";
  verrouiller("etape-3");
  verrouiller("etape-4");
  var lien = $("lien-telechargement");
  lien.classList.add("cache");
  lien.removeAttribute("href");
}

async function creerDepuisUpload() {
  var input = $("fichier");
  if (!input.files || input.files.length === 0) { return; }
  if (input.files[0].size > 10 * 1024 * 1024) {
    afficherBandeau("Image trop lourde : 10 Mo maximum.", "erreur");
    return;
  }
  var bouton = $("btn-upload");
  occuper(bouton, "Envoi en cours…");
  var donnees = new FormData();
  donnees.append("file", input.files[0]);
  var r = await api("/api/character/from-upload", { method: "POST", body: donnees });
  liberer(bouton);
  if (gererErreurReseau(r, "upload de l'image")) { return; }
  if (r.statut !== 200 || !r.corps || !r.corps.character_id) {
    afficherBandeau(messageErreur(r, "L'upload a échoué"), "erreur");
    return;
  }
  personnagePret(r.corps.character_id, r.corps.image_url, "image uploadée");
}

async function creerDepuisPrompt() {
  var zone = $("prompt");
  var texte = zone.value.trim();
  if (!texte) {
    afficherBandeau("Décris ta mascotte en quelques mots avant de lancer la génération.", "avertissement");
    zone.focus();
    return;
  }
  var bouton = $("btn-prompt");
  occuper(bouton, "Génération de l'image en cours…");
  var r = await api("/api/character/from-prompt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt: texte })
  });
  liberer(bouton);
  if (gererErreurReseau(r, "génération du personnage")) { return; }
  if (r.statut !== 200 || !r.corps || !r.corps.character_id) {
    afficherBandeau(messageErreur(r, "La génération du personnage a échoué"), "erreur");
    return;
  }
  rafraichirCout();
  personnagePret(r.corps.character_id, r.corps.image_url, "prompt");
}

/* ---------- Étape 2 : éditeur d'états ---------- */

async function chargerPresets() {
  var r = await api("/api/presets");
  if (r.statut !== 200 || !r.corps) { return; }
  presets = r.corps;
  var select = $("usage");
  select.innerHTML = "";
  Object.keys(presets.presets).forEach(function (cle) {
    var option = document.createElement("option");
    option.value = cle;
    option.textContent = presets.presets[cle].label;
    select.appendChild(option);
  });
  select.value = presets.default;
  appliquerPreset(presets.default);
}

function appliquerPreset(cle) {
  etatsEdites = presets.presets[cle].states.map(function (s) {
    return { name: s.name, prompt: s.prompt, loop: s.loop };
  });
  construireEditeur();
}

function construireEditeur() {
  var liste = $("editeur-etats");
  liste.innerHTML = "";
  etatsEdites.forEach(function (etat, index) {
    var li = document.createElement("li");

    var nom = document.createElement("input");
    nom.type = "text";
    nom.value = etat.name;
    nom.className = "champ-nom";
    nom.setAttribute("aria-label", "Nom de l'état " + (index + 1));
    nom.placeholder = "nom";
    nom.addEventListener("input", function () {
      etat.name = nom.value.trim().toLowerCase();
      nom.classList.toggle("invalide", !NOM_VALIDE.test(etat.name));
      majEstimation();
    });

    var mouvement = document.createElement("input");
    mouvement.type = "text";
    mouvement.value = etat.prompt;
    mouvement.className = "champ-mouvement";
    mouvement.maxLength = 300;
    mouvement.setAttribute("aria-label", "Mouvement de l'état " + (index + 1));
    mouvement.placeholder = "mouvement, en anglais : waving hello, jumping…";
    mouvement.addEventListener("input", function () {
      etat.prompt = mouvement.value;
      majEstimation();
    });

    var boucle = document.createElement("label");
    boucle.className = "case-boucle";
    var caseBoucle = document.createElement("input");
    caseBoucle.type = "checkbox";
    caseBoucle.checked = etat.loop;
    caseBoucle.addEventListener("change", function () {
      etat.loop = caseBoucle.checked;
      majEstimation();
    });
    boucle.appendChild(caseBoucle);
    boucle.appendChild(document.createTextNode(" Boucle"));

    var retirer = document.createElement("button");
    retirer.type = "button";
    retirer.className = "btn-retirer";
    retirer.textContent = "×";
    retirer.setAttribute("aria-label", "Retirer l'état " + (etat.name || index + 1));
    retirer.addEventListener("click", function () {
      etatsEdites.splice(index, 1);
      construireEditeur();
    });

    li.appendChild(nom);
    li.appendChild(mouvement);
    li.appendChild(boucle);
    li.appendChild(retirer);
    liste.appendChild(li);
  });
  majEstimation();
}

function ajouterEtat() {
  if (presets && etatsEdites.length >= presets.max_states) {
    afficherBandeau("Maximum " + presets.max_states + " états par mascotte.", "avertissement");
    return;
  }
  etatsEdites.push({ name: "", prompt: "", loop: false });
  construireEditeur();
  var champs = $("editeur-etats").querySelectorAll(".champ-nom");
  champs[champs.length - 1].focus();
}

/* Retourne un message d'erreur, ou null si la liste est valide. */
function problemeEtats() {
  if (etatsEdites.length === 0) { return "Ajoute au moins un état."; }
  var vus = {};
  for (var i = 0; i < etatsEdites.length; i++) {
    var e = etatsEdites[i];
    if (!NOM_VALIDE.test(e.name)) { return "Nom invalide : minuscules, chiffres et tirets, en commençant par une lettre."; }
    if (vus[e.name]) { return "L'état « " + e.name + " » apparaît deux fois."; }
    vus[e.name] = true;
    if (!e.prompt.trim()) { return "Décris le mouvement de « " + e.name + " »."; }
  }
  if (!etatsEdites.some(function (e) { return e.loop; })) {
    return "Garde au moins un état en boucle : la mascotte le joue au repos.";
  }
  return null;
}

function majEstimation() {
  var probleme = problemeEtats();
  var cible = $("estimation");
  if (probleme) {
    cible.textContent = probleme;
    cible.classList.add("alerte");
  } else {
    var prix = presets ? etatsEdites.length * presets.cost_per_state_usd : NaN;
    cible.textContent = etatsEdites.length + " état(s), environ " + formaterMontant(prix);
    cible.classList.remove("alerte");
  }
  if (characterId && !$("btn-generer").classList.contains("occupe") && !intervallePoll) {
    $("btn-generer").disabled = !!probleme;
  }
}

/* ---------- Étape 2 : génération et suivi ---------- */

function construireListeEtats(noms) {
  var liste = $("liste-etats");
  liste.innerHTML = "";
  noms.forEach(function (nomEtat) {
    var li = document.createElement("li");
    li.id = "etat-" + nomEtat;
    li.setAttribute("data-statut", "queued");
    var nom = document.createElement("span");
    nom.className = "nom-etat";
    nom.textContent = nomEtat;
    var indicateur = document.createElement("span");
    indicateur.className = "indicateur";
    var puce = document.createElement("span");
    puce.className = "puce";
    var texte = document.createElement("span");
    texte.className = "texte-statut";
    texte.textContent = STATUTS_ETAT.queued;
    indicateur.appendChild(puce);
    indicateur.appendChild(texte);
    li.appendChild(nom);
    li.appendChild(indicateur);
    var regen = document.createElement("button");
    regen.type = "button";
    regen.className = "btn-regenerer cache";
    regen.textContent = "Régénérer";
    regen.setAttribute("aria-label", "Régénérer l'état " + nomEtat);
    regen.title = "Nouveau clip pour cet état, avec sa description actuelle de l'éditeur";
    regen.addEventListener("click", function () { regenererEtat(nomEtat, regen); });
    li.appendChild(regen);
    var erreur = document.createElement("span");
    erreur.className = "erreur-etat";
    li.appendChild(erreur);
    liste.appendChild(li);
  });
}

function majIndicateur(cle, info) {
  var li = document.getElementById("etat-" + cle);
  if (!li) { return; }
  var statut = STATUTS_ETAT[info.status] ? info.status : "queued";
  li.setAttribute("data-statut", statut);
  li.querySelector(".texte-statut").textContent = STATUTS_ETAT[statut];
  li.querySelector(".erreur-etat").textContent = info.error || "";
  li.querySelector(".btn-regenerer").classList.toggle("cache", statut !== "done");
}

function arreterPoll() {
  if (intervallePoll) {
    clearInterval(intervallePoll);
    intervallePoll = null;
  }
}

async function lancerGeneration() {
  if (!characterId) { return; }
  var probleme = problemeEtats();
  if (probleme) {
    afficherBandeau(probleme, "avertissement");
    return;
  }
  var bouton = $("btn-generer");
  occuper(bouton, "Lancement…");
  $("statut-job").textContent = "";
  var r = await api("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ character_id: characterId, states: etatsEdites })
  });
  liberer(bouton);
  if (gererErreurReseau(r, "lancement de la génération")) { return; }
  if (r.statut !== 200 || !r.corps || !r.corps.job_id) {
    if (r.statut === 429) { rafraichirCout(); }
    afficherBandeau(messageErreur(r, "Le lancement de la génération a échoué"), "erreur");
    return;
  }
  cacherBandeau();
  suivreJob(r.corps.job_id);
}

function suivreJob(id) {
  jobId = id;
  history.replaceState(null, "", "#job=" + encodeURIComponent(id));
  $("btn-generer").disabled = true;
  $("btn-relancer").classList.add("cache");
  $("liste-etats").innerHTML = "";
  demarrerPoll();
  rafraichirCout();
}

async function relancerEchecs() {
  if (!jobId) { return; }
  var bouton = $("btn-relancer");
  occuper(bouton, "Relance…");
  var r = await api("/api/jobs/" + encodeURIComponent(jobId) + "/retry", { method: "POST" });
  liberer(bouton);
  if (gererErreurReseau(r, "relance des états")) { return; }
  if (r.statut !== 200) {
    afficherBandeau(messageErreur(r, "La relance a échoué"), "erreur");
    return;
  }
  cacherBandeau();
  suivreJob(jobId);
}

async function regenererEtat(nom, bouton) {
  if (!jobId) { return; }
  var etat = etatsEdites.find(function (e) { return e.name === nom; });
  occuper(bouton, "Envoi…");
  var r = await api(
    "/api/jobs/" + encodeURIComponent(jobId) + "/states/" + encodeURIComponent(nom) + "/regenerate",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(etat ? { prompt: etat.prompt } : {})
    }
  );
  liberer(bouton);
  if (gererErreurReseau(r, "régénération de l'état")) { return; }
  if (r.statut !== 200) {
    if (r.statut === 429) { rafraichirCout(); }
    afficherBandeau(messageErreur(r, "La régénération a échoué"), "erreur");
    return;
  }
  cacherBandeau();
  suivreJob(jobId);
}

function demarrerPoll() {
  arreterPoll();
  intervallePoll = setInterval(actualiserJob, 3000);
  actualiserJob();
}

var pollEnCours = false;

async function actualiserJob() {
  if (!jobId || pollEnCours) { return; }
  pollEnCours = true;
  var r = await api("/api/jobs/" + encodeURIComponent(jobId));
  pollEnCours = false;
  if (gererErreurReseau(r, "suivi de la génération")) {
    arreterPoll();
    return;
  }
  if (r.statut !== 200 || !r.corps) {
    arreterPoll();
    $("statut-job").textContent = "Suivi interrompu.";
    afficherBandeau(messageErreur(r, "Le suivi de la génération a été interrompu"), "erreur");
    return;
  }
  var job = r.corps;
  if (!characterId) { characterId = job.character_id; } // reprise après rechargement
  var noms = Object.keys(job.states);
  if ($("liste-etats").children.length !== noms.length) { construireListeEtats(noms); }
  noms.forEach(function (nom) { majIndicateur(nom, job.states[nom]); });
  $("liste-etats").classList.toggle("job-actif", job.status === "queued" || job.status === "running");

  if (job.status === "done") {
    arreterPoll();
    $("statut-job").textContent = "Génération terminée.";
    $("btn-generer").disabled = !characterId || !!problemeEtats();
    $("btn-generer").textContent = "Générer à nouveau";
    $("btn-relancer").classList.add("cache");
    afficherApercu(job);
    deverrouiller("etape-3");
    deverrouiller("etape-4");
    rafraichirCout();
  } else if (job.status === "failed") {
    arreterPoll();
    $("statut-job").textContent = "Des états ont échoué : le détail s'affiche sous chacun.";
    $("btn-generer").disabled = !characterId || !!problemeEtats();
    $("btn-relancer").classList.remove("cache");
    $("btn-relancer").disabled = false;
    rafraichirCout();
  } else if (job.status === "queued") {
    $("statut-job").textContent = "En file d'attente…";
  } else {
    $("statut-job").textContent = "Génération en cours, cela prend quelques minutes…";
  }
}

/* ---------- Étape 3 : aperçu dans le vrai widget ---------- */

function afficherApercu(job) {
  var scene = $("scene");
  scene.innerHTML = "";
  var avatar = document.createElement("mascot-avatar");
  avatar.setAttribute("manifest", "/api/jobs/" + encodeURIComponent(job.job_id) + "/manifest.json");
  avatar.setAttribute("sleep-after", "0");
  avatar.setAttribute("label", "Aperçu de la mascotte");
  scene.appendChild(avatar);

  var controles = $("controles-etats");
  controles.innerHTML = "";
  Object.keys(job.states).forEach(function (nom) {
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.textContent = nom;
    bouton.setAttribute("aria-pressed", String(nom === job.default_state));
    bouton.addEventListener("click", function () { avatar.play(nom); });
    controles.appendChild(bouton);
  });
  avatar.addEventListener("statechange", function (ev) {
    var boutons = controles.querySelectorAll("button");
    for (var i = 0; i < boutons.length; i++) {
      boutons[i].setAttribute("aria-pressed", String(boutons[i].textContent === ev.detail.to));
    }
  });
}

function changerFond(classe) {
  var scene = $("scene");
  scene.classList.remove("fond-damier", "fond-clair", "fond-sombre");
  scene.classList.add(classe);
}

/* ---------- Étape 4 : export ---------- */

async function exporterDossier() {
  if (!jobId) { return; }
  var bouton = $("btn-export");
  occuper(bouton, "Préparation du zip…");
  var r = await api("/api/export/" + encodeURIComponent(jobId), { method: "POST" });
  liberer(bouton);
  if (gererErreurReseau(r, "export du dossier")) { return; }
  if (r.statut !== 200 || !r.corps || !r.corps.download_url) {
    afficherBandeau(messageErreur(r, "L'export a échoué"), "erreur");
    return;
  }
  var lien = $("lien-telechargement");
  lien.href = r.corps.download_url;
  lien.classList.remove("cache");
}

/* ---------- Reprise d'un job après rechargement ---------- */

function reprendreJobDepuisUrl() {
  var trouve = /job=([a-f0-9]+)/.exec(location.hash);
  if (!trouve) { return; }
  deverrouiller("etape-2");
  $("btn-generer").disabled = true;
  suivreJob(trouve[1]);
}

/* ---------- Initialisation ---------- */

function init() {
  $("onglet-upload").addEventListener("click", function () { basculerOnglet(false); });
  $("onglet-prompt").addEventListener("click", function () { basculerOnglet(true); });

  $("fichier").addEventListener("change", function () {
    var input = $("fichier");
    var zone = $("zone-texte");
    if (input.files && input.files.length > 0) {
      zone.textContent = "Fichier choisi : " + input.files[0].name + " (clique pour en changer)";
      zone.classList.add("fichier-choisi");
      $("btn-upload").disabled = false;
      majApercuFichier(input.files[0]);
    } else {
      zone.textContent = "Clique pour choisir une image (PNG détouré conseillé pour un fond transparent, 10 Mo max)";
      zone.classList.remove("fichier-choisi");
      $("btn-upload").disabled = true;
      majApercuFichier(null);
    }
  });

  $("apercu-fichier").addEventListener("error", function () {
    majApercuFichier(null);
    $("btn-upload").disabled = true;
    afficherBandeau("Ce fichier ne se lit pas comme une image. Choisis un PNG, un JPEG ou un WebP.", "erreur");
  });

  $("btn-upload").addEventListener("click", creerDepuisUpload);
  $("btn-prompt").addEventListener("click", creerDepuisPrompt);
  $("usage").addEventListener("change", function () { appliquerPreset($("usage").value); });
  $("btn-ajouter-etat").addEventListener("click", ajouterEtat);
  $("btn-generer").addEventListener("click", lancerGeneration);
  $("btn-relancer").addEventListener("click", relancerEchecs);
  $("btn-export").addEventListener("click", exporterDossier);
  $("bandeau-fermer").addEventListener("click", cacherBandeau);
  $("controles-fond").addEventListener("click", function (ev) {
    var fond = ev.target.dataset && ev.target.dataset.fond;
    if (fond) { changerFond(fond); }
  });

  verifierSante();
  rafraichirCout();
  chargerPresets().then(reprendreJobDepuisUrl);
}

document.addEventListener("DOMContentLoaded", init);
