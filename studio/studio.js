/* MascotForge V2 : Studio. Vanilla JS, aucune dépendance.
   Parle au backend via le contrat /api/* (même origine, page servie à /). */
"use strict";

var ETATS = [
  { cle: "idle",     label: "Repos" },
  { cle: "talking",  label: "Parole" },
  { cle: "thinking", label: "Réflexion" },
  { cle: "clicked",  label: "Clic" },
  { cle: "error",    label: "Erreur" },
  { cle: "sleeping", label: "Sommeil" }
];

var STATUTS_ETAT = {
  queued:  "En attente",
  running: "En cours…",
  done:    "Terminé",
  failed:  "Échec"
};

var characterId = null;
var jobId = null;
var intervallePoll = null;

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
  $("cout-mascottes").textContent =
    (typeof nb === "number" ? nb : "…") + " mascotte(s) terminée(s)";
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
      "Clé FAL non configurée : la génération de vidéos est désactivée " +
      "tant que la clé n'est pas ajoutée côté backend. Le studio reste " +
      "consultable, mais l'étape 2 échouera.",
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

function personnagePret(id, imageUrl, origine) {
  characterId = id;
  var img = $("img-personnage");
  img.src = imageUrl;
  img.alt = "Aperçu du personnage (" + origine + ")";
  $("apercu-personnage").classList.remove("cache");
  $("info-personnage").textContent =
    "Personnage prêt (" + origine + "). Tu peux lancer la génération des états.";
  reinitialiserJob();
  deverrouiller("etape-2");
  $("btn-generer").disabled = false;
  cacherBandeau();
}

function reinitialiserJob() {
  arreterPoll();
  jobId = null;
  $("statut-job").textContent = "";
  $("grille-videos").innerHTML = "";
  construireListeEtats();
  verrouiller("etape-3");
  verrouiller("etape-4");
  var lien = $("lien-telechargement");
  lien.classList.add("cache");
  lien.removeAttribute("href");
}

async function creerDepuisUpload() {
  var input = $("fichier");
  if (!input.files || input.files.length === 0) { return; }
  var bouton = $("btn-upload");
  bouton.disabled = true;
  bouton.textContent = "Envoi en cours…";
  var donnees = new FormData();
  donnees.append("file", input.files[0]);
  var r = await api("/api/character/from-upload", { method: "POST", body: donnees });
  bouton.disabled = false;
  bouton.textContent = "Uploader et créer le personnage";
  if (gererErreurReseau(r, "upload de l'image")) { return; }
  if (r.statut !== 200 && r.statut !== 201) {
    afficherBandeau(
      "L'upload a échoué (erreur " + r.statut + "). Vérifie le format de l'image puis réessaie.",
      "erreur"
    );
    return;
  }
  if (!r.corps || !r.corps.character_id || !r.corps.image_url) {
    afficherBandeau("Réponse inattendue du backend pendant l'upload.", "erreur");
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
  bouton.disabled = true;
  bouton.textContent = "Génération de l'image en cours…";
  var r = await api("/api/character/from-prompt", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ prompt: texte })
  });
  bouton.disabled = false;
  bouton.textContent = "Générer le personnage";
  if (gererErreurReseau(r, "génération du personnage")) { return; }
  if (r.statut === 503) {
    afficherBandeau("Clé FAL non configurée : impossible de générer l'image du personnage.", "erreur");
    return;
  }
  if (r.statut !== 200 && r.statut !== 201) {
    afficherBandeau(
      "La génération du personnage a échoué (erreur " + r.statut + "). Réessaie avec une autre description.",
      "erreur"
    );
    return;
  }
  if (!r.corps || !r.corps.character_id || !r.corps.image_url) {
    afficherBandeau("Réponse inattendue du backend pendant la génération du personnage.", "erreur");
    return;
  }
  personnagePret(r.corps.character_id, r.corps.image_url, "prompt");
}

/* ---------- Étape 2 : génération ---------- */

function construireListeEtats() {
  var liste = $("liste-etats");
  liste.innerHTML = "";
  ETATS.forEach(function (etat) {
    var li = document.createElement("li");
    li.id = "etat-" + etat.cle;
    li.setAttribute("data-statut", "queued");
    var nom = document.createElement("span");
    nom.className = "nom-etat";
    nom.textContent = etat.label;
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
    liste.appendChild(li);
  });
}

function majIndicateur(cle, statut) {
  var li = $("etat-" + cle);
  if (!li) { return; }
  var normalise = STATUTS_ETAT[statut] ? statut : "queued";
  li.setAttribute("data-statut", normalise);
  li.querySelector(".texte-statut").textContent = STATUTS_ETAT[normalise];
}

function arreterPoll() {
  if (intervallePoll) {
    clearInterval(intervallePoll);
    intervallePoll = null;
  }
}

async function lancerGeneration() {
  if (!characterId) { return; }
  var bouton = $("btn-generer");
  bouton.disabled = true;
  bouton.textContent = "Lancement…";
  $("statut-job").textContent = "";
  var r = await api("/api/generate", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ character_id: characterId })
  });
  bouton.disabled = false;
  bouton.textContent = "Générer les 6 états";
  if (gererErreurReseau(r, "lancement de la génération")) { return; }
  if (r.statut === 429) {
    await rafraichirCout();
    afficherBandeau(
      "Plafond mensuel atteint : la génération est bloquée jusqu'au mois prochain. " +
      "Le compteur en haut de page affiche la dépense cumulée.",
      "erreur"
    );
    return;
  }
  if (r.statut === 503) {
    afficherBandeau(
      "Clé FAL non configurée sur le backend : impossible de lancer la génération. " +
      "Ajoute la clé puis recharge la page.",
      "erreur"
    );
    return;
  }
  if ((r.statut !== 200 && r.statut !== 201 && r.statut !== 202) || !r.corps || !r.corps.job_id) {
    afficherBandeau(
      "Le lancement de la génération a échoué (erreur " + r.statut + "). Réessaie dans un moment.",
      "erreur"
    );
    return;
  }
  jobId = r.corps.job_id;
  bouton.disabled = true;
  bouton.textContent = "Génération en cours…";
  demarrerPoll();
}

function demarrerPoll() {
  arreterPoll();
  intervallePoll = setInterval(actualiserJob, 3000);
  actualiserJob();
}

async function actualiserJob() {
  if (!jobId) { return; }
  var r = await api("/api/jobs/" + encodeURIComponent(jobId));
  if (gererErreurReseau(r, "suivi de la génération")) {
    arreterPoll();
    return;
  }
  if (r.statut !== 200 || !r.corps) {
    arreterPoll();
    $("statut-job").textContent = "Suivi interrompu (erreur " + r.statut + ").";
    afficherBandeau("Le suivi de la génération a été interrompu. Recharge la page pour réessayer.", "erreur");
    return;
  }
  var job = r.corps;
  ETATS.forEach(function (etat) {
    var info = job.states && job.states[etat.cle];
    majIndicateur(etat.cle, info && info.status ? info.status : "queued");
  });
  if (job.status === "done") {
    arreterPoll();
    $("statut-job").textContent = "Génération terminée.";
    var bouton = $("btn-generer");
    bouton.disabled = false;
    bouton.textContent = "Régénérer les 6 états";
    afficherApercu(job.states);
    deverrouiller("etape-3");
    deverrouiller("etape-4");
    $("btn-export").disabled = false;
    rafraichirCout();
  } else if (job.status === "failed") {
    arreterPoll();
    $("statut-job").textContent = "La génération a échoué.";
    $("btn-generer").disabled = false;
    $("btn-generer").textContent = "Réessayer la génération";
    afficherBandeau(
      "La génération a échoué côté backend. Vérifie les journaux du backend puis réessaie.",
      "erreur"
    );
  } else if (job.status === "queued") {
    $("statut-job").textContent = "En file d'attente…";
  } else {
    $("statut-job").textContent = "Génération en cours, cela prend quelques minutes…";
  }
}

/* ---------- Étape 3 : aperçu ---------- */

function afficherApercu(states) {
  var grille = $("grille-videos");
  grille.innerHTML = "";
  ETATS.forEach(function (etat) {
    var info = states && states[etat.cle];
    var carte = document.createElement("figure");
    carte.className = "carte-video";
    var legende = document.createElement("figcaption");
    legende.textContent = etat.label;
    carte.appendChild(legende);
    if (info && info.video_url) {
      var video = document.createElement("video");
      video.src = info.video_url;
      video.loop = true;
      video.muted = true;
      video.autoplay = true;
      video.controls = true;
      video.setAttribute("playsinline", "");
      video.setAttribute("title", "État : " + etat.label);
      carte.appendChild(video);
    } else {
      var manque = document.createElement("p");
      manque.className = "muted";
      manque.textContent = "Clip indisponible pour cet état.";
      carte.appendChild(manque);
    }
    grille.appendChild(carte);
  });
}

/* ---------- Étape 4 : export ---------- */

async function exporterDossier() {
  if (!jobId) { return; }
  var bouton = $("btn-export");
  bouton.disabled = true;
  bouton.textContent = "Préparation du zip…";
  var r = await api("/api/export/" + encodeURIComponent(jobId), { method: "POST" });
  bouton.disabled = false;
  bouton.textContent = "Exporter le dossier";
  if (gererErreurReseau(r, "export du dossier")) { return; }
  if (r.statut !== 200 || !r.corps || !r.corps.download_url) {
    afficherBandeau(
      "L'export a échoué (erreur " + r.statut + "). Réessaie dans un moment.",
      "erreur"
    );
    return;
  }
  var lien = $("lien-telechargement");
  lien.href = r.corps.download_url;
  lien.classList.remove("cache");
}

/* ---------- Initialisation ---------- */

function init() {
  construireListeEtats();

  $("onglet-upload").addEventListener("click", function () { basculerOnglet(false); });
  $("onglet-prompt").addEventListener("click", function () { basculerOnglet(true); });

  $("fichier").addEventListener("change", function () {
    var input = $("fichier");
    var zone = $("zone-texte");
    if (input.files && input.files.length > 0) {
      zone.textContent = "Fichier choisi : " + input.files[0].name;
      zone.classList.add("fichier-choisi");
      $("btn-upload").disabled = false;
    } else {
      zone.textContent = "Clique pour choisir une image (PNG, JPEG ou WebP)";
      zone.classList.remove("fichier-choisi");
      $("btn-upload").disabled = true;
    }
  });

  $("btn-upload").addEventListener("click", creerDepuisUpload);
  $("btn-prompt").addEventListener("click", creerDepuisPrompt);
  $("btn-generer").addEventListener("click", lancerGeneration);
  $("btn-export").addEventListener("click", exporterDossier);
  $("bandeau-fermer").addEventListener("click", cacherBandeau);

  verifierSante();
  rafraichirCout();
}

document.addEventListener("DOMContentLoaded", init);
