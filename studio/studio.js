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
var moteurs = null;
var styleActuel = "video";
var moteurActuel = null;
var configurationsCode = {};
var avatarCodeActuel = null;
var delaiApercuCode = null;
var sourcePersonnage3d = "galerie";
var personnageGalerie3d = null;
var apercuFichier3dUrl = null;
var spec3dTerminee = null;
var spec3dSuivieId = null;
var intervallePoll3d = null;
var poll3dEnCours = false;
var usageActuel = "agent";
var sante = null;
var codeIntegrationActuel = "";
var clesNavigateur = { fal: "", openrouter: "" };
var fournisseurVision = "fal";
var elementAvantReglages = null;
var CLE_STOCKAGE_REGLAGES = "mascotforge.reglages.v1";

var LIBELLES_REGLAGES = {
  shape: "Forme",
  material: "Matière",
  color: "Couleur",
  eyes: "Yeux",
  cheeks: "Joues",
  character: "Personnage"
};

var LIBELLES_ETATS = {
  idle: "Au repos",
  listening: "Écoute",
  thinking: "Réfléchit",
  talking: "Parle",
  speaking: "Parle",
  working: "Travaille",
  happy: "Content",
  celebrating: "Célèbre",
  done: "Terminé",
  error: "Erreur",
  clicked: "Réagit",
  surprised: "Surpris",
  sleeping: "Dort",
  sad: "Triste"
};

var LIBELLES_VALEURS = {
  mochi: "Mochi",
  bean: "Haricot",
  pebble: "Galet",
  squircle: "Carré doux",
  pill: "Capsule",
  drop: "Goutte",
  kitty: "Chat",
  cloud: "Nuage",
  soft: "Doux",
  matte: "Mat",
  jelly: "Gelée",
  glass: "Verre",
  clay: "Argile",
  velvet: "Velours",
  lilac: "Lilas",
  milk: "Lait",
  peach: "Pêche",
  butter: "Beurre",
  matcha: "Matcha",
  mint: "Menthe",
  sky: "Ciel",
  bubblegum: "Rose bonbon",
  tangerine: "Mandarine",
  cocoa: "Cacao",
  ink: "Encre",
  capsule: "Capsules",
  dot: "Points"
};

function $(id) { return document.getElementById(id); }

/* ---------- Réglages et stockage local des clés ---------- */

function lireReglagesLocaux() {
  try {
    var local = window.localStorage.getItem(CLE_STOCKAGE_REGLAGES);
    if (local) { return { donnees: JSON.parse(local), souvenir: true }; }
  } catch (e) {
    // Le navigateur peut refuser le stockage. La clé reste alors en mémoire.
  }
  try {
    var session = window.sessionStorage.getItem(CLE_STOCKAGE_REGLAGES);
    if (session) { return { donnees: JSON.parse(session), souvenir: false }; }
  } catch (e) {
    // Même repli en mémoire si le stockage de session est bloqué.
  }
  return { donnees: {}, souvenir: false };
}

function retirerReglagesLocaux() {
  var ok = true;
  try { window.localStorage.removeItem(CLE_STOCKAGE_REGLAGES); } catch (e) { ok = false; }
  try { window.sessionStorage.removeItem(CLE_STOCKAGE_REGLAGES); } catch (e) { ok = false; }
  return ok;
}

function enregistrerReglages() {
  var donnees = JSON.stringify({
    fal: clesNavigateur.fal,
    openrouter: clesNavigateur.openrouter,
    fournisseur: fournisseurVision
  });
  var souvenir = $("se-souvenir").checked;
  var ok = true;
  if (souvenir) {
    try { window.localStorage.setItem(CLE_STOCKAGE_REGLAGES, donnees); } catch (e) { ok = false; }
    try { window.sessionStorage.removeItem(CLE_STOCKAGE_REGLAGES); } catch (e) { ok = false; }
  } else {
    try { window.sessionStorage.setItem(CLE_STOCKAGE_REGLAGES, donnees); } catch (e) { ok = false; }
    try { window.localStorage.removeItem(CLE_STOCKAGE_REGLAGES); } catch (e) { ok = false; }
  }
  $("statut-stockage").textContent = ok
    ? (souvenir ? "Enregistré sur cet appareil." : "Conservé pour cet onglet seulement.")
    : "Stockage bloqué par le navigateur. Les clés restent en mémoire jusqu'à la fermeture.";
}

function chargerReglages() {
  var sauvegarde = lireReglagesLocaux();
  var donnees = sauvegarde.donnees || {};
  clesNavigateur.fal = typeof donnees.fal === "string" ? donnees.fal.trim() : "";
  clesNavigateur.openrouter = typeof donnees.openrouter === "string" ? donnees.openrouter.trim() : "";
  fournisseurVision = donnees.fournisseur === "openrouter" ? "openrouter" : "fal";
  $("cle-fal").value = clesNavigateur.fal;
  $("cle-openrouter").value = clesNavigateur.openrouter;
  $("fournisseur-vision").value = fournisseurVision;
  $("se-souvenir").checked = sauvegarde.souvenir;
  $("statut-stockage").textContent = sauvegarde.souvenir
    ? "Enregistré sur cet appareil."
    : "Conservé pour cet onglet seulement.";
  actualiserEtatCles();
}

function lireChampsReglages() {
  clesNavigateur.fal = $("cle-fal").value.trim();
  clesNavigateur.openrouter = $("cle-openrouter").value.trim();
  fournisseurVision = $("fournisseur-vision").value === "openrouter" ? "openrouter" : "fal";
  enregistrerReglages();
  actualiserEtatCles();
}

function actualiserEtatCles() {
  if (!$("etat-cle-fal")) { return; }
  $("etat-cle-fal").textContent = clesNavigateur.fal
    ? "Dans ce navigateur"
    : (sante && sante.fal_key_configured ? "Clé du serveur disponible" : "Aucune clé");
  $("etat-cle-openrouter").textContent = clesNavigateur.openrouter
    ? "Dans ce navigateur"
    : "Aucune clé";
  actualiserCapacites();
}

function ouvrirReglages() {
  elementAvantReglages = document.activeElement;
  $("voile-agents").classList.add("cache");
  $("panneau-agents").classList.add("cache");
  $("btn-agents").setAttribute("aria-expanded", "false");
  $("voile-reglages").classList.remove("cache");
  $("panneau-reglages").classList.remove("cache");
  $("btn-reglages").setAttribute("aria-expanded", "true");
  document.body.classList.add("reglages-ouverts");
  window.setTimeout(function () { $("cle-fal").focus(); }, 0);
}

function fermerReglages() {
  $("voile-reglages").classList.add("cache");
  $("panneau-reglages").classList.add("cache");
  $("btn-reglages").setAttribute("aria-expanded", "false");
  document.body.classList.remove("reglages-ouverts");
  if (elementAvantReglages && elementAvantReglages.focus) { elementAvantReglages.focus(); }
}

function ouvrirAgents() {
  elementAvantReglages = document.activeElement;
  $("voile-reglages").classList.add("cache");
  $("panneau-reglages").classList.add("cache");
  $("btn-reglages").setAttribute("aria-expanded", "false");
  $("voile-agents").classList.remove("cache");
  $("panneau-agents").classList.remove("cache");
  $("btn-agents").setAttribute("aria-expanded", "true");
  document.body.classList.add("reglages-ouverts");
  window.setTimeout(function () { $("fermer-agents").focus(); }, 0);
}

function fermerAgents() {
  $("voile-agents").classList.add("cache");
  $("panneau-agents").classList.add("cache");
  $("btn-agents").setAttribute("aria-expanded", "false");
  document.body.classList.remove("reglages-ouverts");
  if (elementAvantReglages && elementAvantReglages.focus) { elementAvantReglages.focus(); }
}

async function copierBlocAgent(bouton) {
  var cible = $(bouton.dataset.cible);
  var statut = $("statut-copie-agents");
  var texteInitial = bouton.textContent;
  var zone = null;
  if (!cible) { return; }
  occuper(bouton, "Copie…");
  statut.textContent = "";
  statut.classList.remove("succes", "echec");
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(cible.textContent.trim());
    } else {
      zone = document.createElement("textarea");
      zone.value = cible.textContent.trim();
      zone.setAttribute("readonly", "");
      zone.style.position = "fixed";
      zone.style.opacity = "0";
      document.body.appendChild(zone);
      zone.select();
      if (!document.execCommand("copy")) { throw new Error("copie refusée"); }
      document.body.removeChild(zone);
    }
    liberer(bouton);
    bouton.textContent = "Copié ✓";
    statut.textContent = "Le bloc est dans ton presse-papiers.";
    statut.classList.add("succes");
    window.setTimeout(function () { bouton.textContent = texteInitial; }, 1800);
  } catch (e) {
    if (zone && zone.parentNode) { zone.parentNode.removeChild(zone); }
    liberer(bouton);
    statut.textContent = "La copie a échoué. Sélectionne le bloc et copie-le manuellement.";
    statut.classList.add("echec");
  }
}

function definirStatutCle(provider, message, succes) {
  var statut = $("statut-cle-" + provider);
  statut.textContent = message;
  statut.classList.toggle("succes", succes === true);
  statut.classList.toggle("echec", succes === false);
}

async function testerCle(provider) {
  lireChampsReglages();
  var cle = clesNavigateur[provider];
  var bouton = $("tester-cle-" + provider);
  if (!cle) {
    definirStatutCle(provider, "Colle d'abord une clé.", false);
    return;
  }
  occuper(bouton, "Test en cours…");
  definirStatutCle(provider, "Vérification…", null);
  var r = await api(
    "/api/keys/test",
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ provider: provider }) },
    provider
  );
  liberer(bouton);
  if (r.injoignable) {
    definirStatutCle(provider, "Serveur MascotForge injoignable.", false);
    return;
  }
  var message = r.corps && r.corps.message ? r.corps.message : "Le test a échoué.";
  definirStatutCle(provider, message, r.statut === 200 && r.corps && r.corps.ok === true);
}

function effacerCle(provider) {
  clesNavigateur[provider] = "";
  $("cle-" + provider).value = "";
  enregistrerReglages();
  definirStatutCle(provider, "Clé effacée de ce navigateur.", true);
  actualiserEtatCles();
}

function basculerVisibiliteCle(bouton) {
  var champ = $(bouton.dataset.cible);
  var visible = champ.type === "text";
  champ.type = visible ? "password" : "text";
  bouton.setAttribute("aria-label", (visible ? "Afficher" : "Masquer") + " la " + champ.getAttribute("aria-label").toLowerCase());
}

function libelleEtat(nom) {
  if (LIBELLES_ETATS[nom]) { return LIBELLES_ETATS[nom]; }
  if (!nom) { return "Nouvel état"; }
  return nom.charAt(0).toUpperCase() + nom.slice(1).replace(/-/g, " ");
}

/* ---------- Navigation de l'assistant ---------- */

function afficherEcran(id) {
  var ecrans = document.querySelectorAll(".ecran-assistant");
  for (var i = 0; i < ecrans.length; i++) {
    ecrans[i].classList.toggle("cache", ecrans[i].id !== id);
  }
  var accueil = id === "ecran-accueil";
  $("progression").classList.toggle("cache", accueil);
  $("btn-recommencer").classList.toggle("cache", accueil);
  var etapes = $("progression").querySelectorAll("span[data-ecran]");
  for (var j = 0; j < etapes.length; j++) {
    etapes[j].classList.toggle("actif", etapes[j].dataset.ecran === id);
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function actualiserUsageInterface() {
  var estAgent = usageActuel === "agent";
  $("pastille-usage").textContent = estAgent ? "Agent IA" : "Site Web";
  $("resume-usage").textContent = estAgent
    ? "Elle saura écouter, réfléchir, parler et signaler une erreur."
    : "Elle saura accueillir, travailler, célébrer et signaler une erreur.";
  if (presets && presets.presets[usageActuel]) {
    $("usage").value = usageActuel;
  }
}

function choisirUsage(usage) {
  usageActuel = usage === "site" ? "site" : "agent";
  if (presets && presets.presets[usageActuel]) {
    appliquerPreset(usageActuel);
  }
  actualiserUsageInterface();
  afficherEcran("ecran-creation");
}

function choisirMethode(methode) {
  $("compteur-cout").classList.toggle(
    "cache",
    methode !== "video" && methode !== "image3d"
  );

  if (methode === "blob") {
    $("sur-titre-personnalisation").textContent = "Sans clé API et instantané";
    $("titre-personnalisation").textContent = "Crée un blob à ton image.";
    $("description-style").textContent = "Choisis sa forme, sa couleur et son expression. Il réagit en direct.";
    basculerStyle("blob");
  } else if (methode === "3d") {
    sourcePersonnage3d = "galerie";
    $("sur-titre-personnalisation").textContent = "Sans clé API et instantané";
    $("titre-personnalisation").textContent = "Choisis ton personnage.";
    $("description-style").textContent = "Essaie ses réactions avant de l'intégrer à ton projet.";
    basculerStyle("3d");
    basculerSourcePersonnage3d("galerie");
  } else if (methode === "image3d") {
    sourcePersonnage3d = "image";
    $("sur-titre-personnalisation").textContent = "À partir de ton image";
    $("titre-personnalisation").textContent = "Transforme-la en personnage 3D.";
    $("description-style").textContent = "Le modèle dessine une interprétation animée dans le style Wobnimo.";
    basculerStyle("3d");
    basculerSourcePersonnage3d("image");
  } else {
    $("sur-titre-personnalisation").textContent = "Vidéo IA";
    $("titre-personnalisation").textContent = "Anime ton personnage.";
    $("description-style").textContent = "Pars d'une image ou d'une description. Les réactions utiles sont déjà choisies.";
    basculerStyle("video");
    $("etape-1").classList.remove("cache");
    $("etape-2").classList.toggle("cache", !characterId && !jobId);
    if (presets && presets.presets[usageActuel]) {
      $("usage").value = usageActuel;
      appliquerPreset(usageActuel);
    }
    actualiserUsageInterface();
  }

  if (methode === "video" || methode === "image3d") { rafraichirCout(); }
  afficherEcran("ecran-personnalisation");
}

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

async function api(chemin, options, clesRequises) {
  var reponse;
  var requete = Object.assign({}, options || {});
  if (clesRequises) {
    var cible = new URL(chemin, window.location.href);
    if (cible.origin === window.location.origin) {
      var entetes = new Headers(requete.headers || {});
      if ((clesRequises === "fal" ||
          (clesRequises === "vision" && fournisseurVision === "fal")) &&
          clesNavigateur.fal) {
        entetes.set("X-Fal-Key", clesNavigateur.fal);
      }
      if ((clesRequises === "openrouter" ||
          (clesRequises === "vision" && fournisseurVision === "openrouter")) &&
          clesNavigateur.openrouter) {
        entetes.set("X-OpenRouter-Key", clesNavigateur.openrouter);
      }
      if (clesRequises === "vision") {
        entetes.set("X-Vision-Provider", fournisseurVision);
      }
      requete.headers = entetes;
    }
  }
  try {
    reponse = await fetch(chemin, requete);
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

/* ---------- Choix du style et moteurs en code ---------- */

function basculerStyle(style) {
  var estCode = style !== "video";
  styleActuel = style;
  moteurActuel = estCode ? style : null;
  $("parcours-video").classList.toggle("cache", estCode);
  $("code").classList.toggle("cache", !estCode);
  actualiserDescriptionStyle();

  if (!estCode) {
    clearTimeout(delaiApercuCode);
    return;
  }
  if (moteurs) { construireFormulaireCode(style); }
}

function actualiserDescriptionStyle() {
  if (styleActuel === "video") {
    $("description-style").textContent =
      "Pars d'une image ou d'une description. Les réactions utiles sont déjà choisies.";
  } else if (styleActuel === "3d" && sourcePersonnage3d === "image") {
    $("description-style").textContent =
      "Le modèle dessine une interprétation animée dans le style Wobnimo.";
  } else if (styleActuel === "3d") {
    $("description-style").textContent =
      "Essaie ses réactions avant de l'intégrer à ton projet.";
  } else {
    $("description-style").textContent =
      "Choisis sa forme, sa couleur et son expression. Il réagit en direct.";
  }
}

async function chargerMoteurs() {
  var r = await api("/api/engines");
  if (gererErreurReseau(r, "chargement des styles en code")) { return; }
  if (r.statut !== 200 || !r.corps) {
    afficherBandeau(messageErreur(r, "Le chargement des styles en code a échoué"), "erreur");
    return;
  }
  moteurs = r.corps;
  if (styleActuel !== "video") { construireFormulaireCode(styleActuel); }
}

function obtenirConfigurationCode(cle) {
  if (!configurationsCode[cle]) {
    var config = {};
    Object.keys(moteurs[cle].options).forEach(function (nom) {
      config[nom] = String(moteurs[cle].options[nom][0]);
    });
    configurationsCode[cle] = config;
  }
  return configurationsCode[cle];
}

function libelleValeurCode(nom, valeur) {
  if (String(valeur) === "true") { return "oui"; }
  if (String(valeur) === "false") { return "non"; }
  if (LIBELLES_VALEURS[String(valeur)]) { return LIBELLES_VALEURS[String(valeur)]; }
  if (nom === "character") {
    return String(valeur).charAt(0).toUpperCase() + String(valeur).slice(1);
  }
  return String(valeur);
}

function reinitialiserExportCode() {
  var lien = $("lien-telechargement-code");
  lien.classList.add("cache");
  lien.removeAttribute("href");
}

function actualiserDisponibiliteExportCode() {
  var bouton = $("btn-export-code");
  if (bouton.classList.contains("occupe")) { return; }
  var indisponible = moteurActuel === "3d" &&
    sourcePersonnage3d === "image" && !spec3dTerminee;
  bouton.disabled = indisponible;
  $("btn-terminer-code").disabled = indisponible;
}

function construireFormulaireCode(cle) {
  var spec = moteurs && moteurs[cle];
  if (!spec) {
    afficherBandeau("Ce style de mascotte est indisponible.", "erreur");
    return;
  }
  moteurActuel = cle;
  var config = obtenirConfigurationCode(cle);
  var reglages = $("reglages-code");
  reglages.innerHTML = "";

  Object.keys(spec.options).forEach(function (nom) {
    var groupe = document.createElement("div");
    groupe.className = "champ-code";
    var id = "code-" + cle + "-" + nom;
    var label = document.createElement("label");
    label.className = "etiquette";
    label.htmlFor = id;
    label.textContent = LIBELLES_REGLAGES[nom] || nom;
    var select = document.createElement("select");
    select.id = id;
    var couleurPerso = null;

    spec.options[nom].forEach(function (valeur) {
      var option = document.createElement("option");
      option.value = String(valeur);
      option.textContent = libelleValeurCode(nom, valeur);
      select.appendChild(option);
    });
    if (spec.free_color === nom && /^#[0-9a-f]{6}$/i.test(config[nom])) {
      var optionInitiale = document.createElement("option");
      optionInitiale.value = config[nom];
      optionInitiale.textContent = config[nom];
      optionInitiale.dataset.couleurPerso = "true";
      select.appendChild(optionInitiale);
    }
    var valeurSelectionnee = config[nom];
    if (cle === "3d" && nom === "character") {
      if (!personnageGalerie3d) {
        personnageGalerie3d = valeurSelectionnee || String(spec.options[nom][0]);
      }
      valeurSelectionnee = personnageGalerie3d;
    }
    select.value = valeurSelectionnee;
    if (select.value !== valeurSelectionnee) { select.selectedIndex = -1; }
    select.addEventListener("change", function () {
      if (cle === "3d" && nom === "character") {
        personnageGalerie3d = select.value;
        if (sourcePersonnage3d !== "galerie") { return; }
      }
      config[nom] = select.value;
      if (couleurPerso && /^#[0-9a-f]{6}$/i.test(select.value)) {
        couleurPerso.value = select.value;
      }
      reinitialiserExportCode();
      programmerApercuCode();
    });

    groupe.appendChild(label);
    groupe.appendChild(select);
    reglages.appendChild(groupe);

    if (spec.free_color === nom) {
      var groupeCouleur = document.createElement("div");
      groupeCouleur.className = "champ-code";
      var idCouleur = id + "-perso";
      var labelCouleur = document.createElement("label");
      labelCouleur.className = "etiquette";
      labelCouleur.htmlFor = idCouleur;
      labelCouleur.textContent = "Couleur perso";
      couleurPerso = document.createElement("input");
      couleurPerso.type = "color";
      couleurPerso.id = idCouleur;
      couleurPerso.value = /^#[0-9a-f]{6}$/i.test(config[nom]) ? config[nom] : "#7c3aed";
      couleurPerso.addEventListener("input", function () {
        config[nom] = couleurPerso.value;
        var optionPerso = select.querySelector("option[data-couleur-perso]");
        if (!optionPerso) {
          optionPerso = document.createElement("option");
          optionPerso.dataset.couleurPerso = "true";
          select.appendChild(optionPerso);
        }
        optionPerso.value = config[nom];
        optionPerso.textContent = config[nom];
        select.value = config[nom];
        reinitialiserExportCode();
        programmerApercuCode();
      });
      groupeCouleur.appendChild(labelCouleur);
      groupeCouleur.appendChild(couleurPerso);
      reglages.appendChild(groupeCouleur);
    }
  });

  actualiserInterfaceSource3d(cle);
  construireControlesEtatsCode(spec.states);
  construireCreditCode(spec);
  reinitialiserExportCode();
  actualiserDisponibiliteExportCode();
  programmerApercuCode();
}

function remplacerConfiguration3d(nom, valeur) {
  var config = obtenirConfigurationCode("3d");
  Object.keys(config).forEach(function (cle) { delete config[cle]; });
  config[nom] = valeur;
}

function obtenirPersonnageGalerie3d() {
  var select = $("code-3d-character");
  if (select && select.value) { personnageGalerie3d = select.value; }
  if (!personnageGalerie3d && moteurs && moteurs["3d"] && moteurs["3d"].options.character) {
    personnageGalerie3d = String(moteurs["3d"].options.character[0]);
  }
  return personnageGalerie3d;
}

function actualiserInterfaceSource3d(cle) {
  var est3d = cle === "3d";
  var depuisImage = est3d && sourcePersonnage3d === "image";
  var reglages = $("reglages-code");
  $("choix-source-3d").classList.toggle("cache", !est3d);
  reglages.classList.toggle("cache", depuisImage);
  $("panneau-3d-image").classList.toggle("cache", !depuisImage);

  $("onglet-3d-galerie").classList.toggle("actif", !depuisImage);
  $("onglet-3d-image").classList.toggle("actif", depuisImage);
  $("onglet-3d-galerie").setAttribute("aria-selected", String(!depuisImage));
  $("onglet-3d-image").setAttribute("aria-selected", String(depuisImage));

  if (est3d) {
    reglages.setAttribute("role", "tabpanel");
    reglages.setAttribute("aria-labelledby", "onglet-3d-galerie");
  } else {
    reglages.removeAttribute("role");
    reglages.removeAttribute("aria-labelledby");
  }
}

function basculerSourcePersonnage3d(source) {
  if (source !== "galerie" && source !== "image") { return; }
  sourcePersonnage3d = source;
  $("compteur-cout").classList.toggle("cache", source !== "image");
  if (source === "image") {
    $("sur-titre-personnalisation").textContent = "À partir de ton image";
    $("titre-personnalisation").textContent = "Transforme-la en personnage 3D.";
    rafraichirCout();
  } else {
    $("sur-titre-personnalisation").textContent = "Sans clé API et instantané";
    $("titre-personnalisation").textContent = "Choisis ton personnage.";
  }
  if (source === "galerie") {
    var personnage = obtenirPersonnageGalerie3d();
    if (personnage) { remplacerConfiguration3d("character", personnage); }
  } else if (spec3dTerminee) {
    remplacerConfiguration3d("spec", spec3dTerminee.spec_id);
  }
  actualiserInterfaceSource3d("3d");
  actualiserDescriptionStyle();
  reinitialiserExportCode();
  actualiserDisponibiliteExportCode();
  programmerApercuCode();
}

function majApercuFichier3d(fichier) {
  var img = $("apercu-fichier-3d");
  if (apercuFichier3dUrl) {
    URL.revokeObjectURL(apercuFichier3dUrl);
    apercuFichier3dUrl = null;
  }
  if (!fichier) {
    img.removeAttribute("src");
    img.classList.add("cache");
    return;
  }
  apercuFichier3dUrl = URL.createObjectURL(fichier);
  img.src = apercuFichier3dUrl;
  img.alt = "Aperçu de " + fichier.name;
  img.classList.remove("cache");
}

function majFichierPersonnage3d() {
  var input = $("fichier-3d");
  var zone = $("zone-texte-3d");
  var bouton = $("btn-creer-3d");
  var fichier = input.files && input.files.length > 0 ? input.files[0] : null;
  if (fichier && fichier.size > 10 * 1024 * 1024) {
    input.value = "";
    zone.textContent = "Clique pour choisir une image (PNG, JPEG ou WebP, 10 Mo max)";
    zone.classList.remove("fichier-choisi");
    bouton.disabled = true;
    majApercuFichier3d(null);
    afficherBandeau("Image trop lourde : 10 Mo maximum.", "erreur");
    return;
  }
  if (fichier) {
    zone.textContent = "Fichier choisi : " + fichier.name + " (clique pour en changer)";
    zone.classList.add("fichier-choisi");
    if (!bouton.classList.contains("occupe")) { bouton.disabled = !visionEstDisponible(); }
    majApercuFichier3d(fichier);
  } else {
    zone.textContent = "Clique pour choisir une image (PNG, JPEG ou WebP, 10 Mo max)";
    zone.classList.remove("fichier-choisi");
    bouton.disabled = true;
    majApercuFichier3d(null);
  }
}

function effacerResultatPersonnage3d() {
  $("info-personnage-3d").textContent = "";
  $("info-personnage-3d").classList.add("cache");
  $("avertissements-personnage-3d").textContent = "";
  $("avertissements-personnage-3d").classList.add("cache");
}

function afficherResultatPersonnage3d(job) {
  var passes = typeof job.rounds === "number" ? job.rounds : 0;
  var info = $("info-personnage-3d");
  var comparaisons = typeof job.visual_rounds === "number" ? job.visual_rounds : 0;
  var coutReel = !job.cost_estimated && typeof job.cost_usd === "number"
    ? ", coût réel : " + formaterMontant(job.cost_usd)
    : "";
  info.textContent = (job.name || "Personnage 3D") + " est prêt. " + passes +
    " passe" + (passes > 1 ? "s" : "") + " d'écriture, " + comparaisons + " comparaison" +
    (comparaisons > 1 ? "s" : "") + " avec ton image" + coutReel + ".";
  info.classList.remove("cache");

  var nombreAvertissements = typeof job.warnings === "number" ? job.warnings : 0;
  var avertissements = $("avertissements-personnage-3d");
  if (nombreAvertissements > 0) {
    avertissements.textContent = "Wobnimo signale encore " + nombreAvertissements +
      " avertissement" + (nombreAvertissements > 1 ? "s" : "") + ".";
    avertissements.classList.remove("cache");
  } else {
    avertissements.textContent = "";
    avertissements.classList.add("cache");
  }
}

function arreterSuiviPersonnage3d() {
  if (intervallePoll3d) {
    clearInterval(intervallePoll3d);
    intervallePoll3d = null;
  }
}

function libererBoutonPersonnage3d() {
  var bouton = $("btn-creer-3d");
  if (bouton.classList.contains("occupe")) { liberer(bouton); }
  var input = $("fichier-3d");
  bouton.disabled = !(input.files && input.files.length > 0) || !visionEstDisponible();
}

function suivrePersonnage3d(id) {
  arreterSuiviPersonnage3d();
  spec3dSuivieId = id;
  intervallePoll3d = setInterval(actualiserPersonnage3d, 3000);
  actualiserPersonnage3d();
}

async function creerPersonnage3d() {
  var input = $("fichier-3d");
  if (!input.files || input.files.length === 0) { return; }
  if (input.files[0].size > 10 * 1024 * 1024) {
    afficherBandeau("Image trop lourde : 10 Mo maximum.", "erreur");
    return;
  }

  arreterSuiviPersonnage3d();
  spec3dSuivieId = null;
  spec3dTerminee = null;
  effacerResultatPersonnage3d();
  reinitialiserExportCode();
  actualiserDisponibiliteExportCode();
  var bouton = $("btn-creer-3d");
  occuper(bouton, "Envoi de l'image…");
  $("statut-creation-3d").textContent = "Envoi de l'image…";
  var donnees = new FormData();
  donnees.append("file", input.files[0]);
  var r = await api("/api/engines/3d/from-image", { method: "POST", body: donnees }, "vision");
  if (gererErreurReseau(r, "création du personnage 3D")) {
    libererBoutonPersonnage3d();
    $("statut-creation-3d").textContent = "Création interrompue.";
    return;
  }
  if (r.statut !== 200 || !r.corps || !r.corps.spec_id) {
    libererBoutonPersonnage3d();
    $("statut-creation-3d").textContent = "Création interrompue.";
    if (r.statut === 429) { rafraichirCout(); }
    afficherBandeau(messageErreur(r, "La création du personnage 3D a échoué"), "erreur");
    return;
  }
  cacherBandeau();
  $("statut-creation-3d").textContent = "Image reçue. Préparation du personnage…";
  suivrePersonnage3d(r.corps.spec_id);
}

async function actualiserPersonnage3d() {
  if (!spec3dSuivieId || poll3dEnCours) { return; }
  var id = spec3dSuivieId;
  poll3dEnCours = true;
  var r = await api("/api/engines/3d/specs/" + encodeURIComponent(id));
  poll3dEnCours = false;
  if (id !== spec3dSuivieId) { return; }

  if (gererErreurReseau(r, "suivi du personnage 3D")) {
    arreterSuiviPersonnage3d();
    spec3dSuivieId = null;
    libererBoutonPersonnage3d();
    $("statut-creation-3d").textContent = "Suivi interrompu.";
    return;
  }
  if (r.statut !== 200 || !r.corps) {
    arreterSuiviPersonnage3d();
    spec3dSuivieId = null;
    libererBoutonPersonnage3d();
    $("statut-creation-3d").textContent = "Suivi interrompu.";
    if (r.statut === 429) { rafraichirCout(); }
    afficherBandeau(messageErreur(r, "Le suivi du personnage 3D a été interrompu"), "erreur");
    return;
  }

  var job = r.corps;
  if (job.status === "done") {
    arreterSuiviPersonnage3d();
    spec3dSuivieId = null;
    spec3dTerminee = job;
    libererBoutonPersonnage3d();
    actualiserDisponibiliteExportCode();
    $("statut-creation-3d").textContent = "Personnage 3D terminé.";
    afficherResultatPersonnage3d(job);
    if (sourcePersonnage3d === "image") {
      remplacerConfiguration3d("spec", job.spec_id);
      if (styleActuel === "3d" && moteurActuel === "3d") {
        reinitialiserExportCode();
        programmerApercuCode();
      }
    }
    cacherBandeau();
    rafraichirCout();
  } else if (job.status === "failed") {
    arreterSuiviPersonnage3d();
    spec3dSuivieId = null;
    libererBoutonPersonnage3d();
    $("statut-creation-3d").textContent = "La création a échoué.";
    afficherBandeau(job.error || "La création du personnage 3D a échoué.", "erreur");
    rafraichirCout();
  } else if (job.status === "queued") {
    $("statut-creation-3d").textContent = "Personnage en file d'attente…";
  } else {
    $("statut-creation-3d").textContent =
      "Le modèle dessine le personnage et Wobnimo le vérifie…";
  }
}

function construireControlesEtatsCode(etats) {
  var controles = $("controles-etats-code");
  controles.innerHTML = "";
  var initial = etats.indexOf("idle") !== -1 ? "idle" : etats[0];
  etats.forEach(function (etat) {
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.textContent = libelleEtat(etat);
    bouton.dataset.etat = etat;
    bouton.setAttribute("aria-pressed", String(etat === initial));
    bouton.addEventListener("click", function () {
      if (avatarCodeActuel) { avatarCodeActuel.play(etat); }
    });
    controles.appendChild(bouton);
  });
}

function selectionnerEtatCode(etat) {
  var boutons = $("controles-etats-code").querySelectorAll("button");
  for (var i = 0; i < boutons.length; i++) {
    boutons[i].setAttribute("aria-pressed", String(boutons[i].dataset.etat === etat));
  }
}

function construireCreditCode(spec) {
  var credit = $("credit-code");
  credit.textContent = "Moteur : " + spec.credit + " ";
  var source = document.createElement("a");
  source.href = spec.source;
  source.target = "_blank";
  source.rel = "noopener";
  source.textContent = "Source";
  credit.appendChild(source);
}

function programmerApercuCode() {
  clearTimeout(delaiApercuCode);
  delaiApercuCode = setTimeout(afficherApercuCode, 250);
}

function obtenirManifestCode() {
  if (!moteurActuel || !moteurs) { return ""; }
  var config = obtenirConfigurationCode(moteurActuel);
  var params = new URLSearchParams();
  Object.keys(config).forEach(function (nom) { params.append(nom, config[nom]); });
  return "/api/engines/" + encodeURIComponent(moteurActuel) +
    "/manifest.json?" + params.toString();
}

function afficherApercuCode() {
  if (styleActuel === "video" || !moteurActuel || !moteurs) { return; }
  var manifest = obtenirManifestCode();
  var scene = $("scene-code");
  scene.innerHTML = "";
  var avatar = document.createElement("mascot-avatar");
  avatar.setAttribute("manifest", manifest);
  avatar.setAttribute("sleep-after", "0");
  avatar.setAttribute("label", "Aperçu de la mascotte en code");
  avatar.addEventListener("statechange", function (ev) {
    selectionnerEtatCode(ev.detail.to);
  });
  avatarCodeActuel = avatar;
  scene.appendChild(avatar);
}

function definirCodeIntegration(manifest) {
  codeIntegrationActuel =
    "<mascot-avatar id=\"ma-mascotte\" manifest=\"" + manifest +
    "\" label=\"Mon assistant\"></mascot-avatar>\n" +
    "<script src=\"./mascot/mascot.js\"></" + "script>";
  $("code-integration").textContent = codeIntegrationActuel;
  $("retour-copie").textContent = "";
}

function afficherFinalCode() {
  var manifest = obtenirManifestCode();
  if (!manifest || !moteurActuel || !moteurs) { return; }
  var scene = $("scene");
  scene.innerHTML = "";
  var avatar = document.createElement("mascot-avatar");
  avatar.setAttribute("manifest", manifest);
  avatar.setAttribute("sleep-after", "0");
  avatar.setAttribute("label", "Mascotte prête à intégrer");
  scene.appendChild(avatar);

  var etats = moteurs[moteurActuel].states;
  var initial = etats.indexOf("idle") !== -1 ? "idle" : etats[0];
  var controles = $("controles-etats");
  controles.innerHTML = "";
  etats.forEach(function (etat) {
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.textContent = libelleEtat(etat);
    bouton.dataset.etat = etat;
    bouton.setAttribute("aria-pressed", String(etat === initial));
    bouton.addEventListener("click", function () { avatar.play(etat); });
    controles.appendChild(bouton);
  });
  avatar.addEventListener("statechange", function (ev) {
    var boutons = controles.querySelectorAll("button");
    for (var i = 0; i < boutons.length; i++) {
      boutons[i].setAttribute("aria-pressed", String(boutons[i].dataset.etat === ev.detail.to));
    }
  });

  $("bloc-suivi").classList.add("cache");
  $("bloc-export-video").classList.add("cache");
  $("bloc-export-code").classList.remove("cache");
  $("titre-final").textContent = "Présente-la à ton public.";
  $("sous-titre-final").textContent = "Teste ses réactions, puis copie le code dans ton projet.";
  definirCodeIntegration("./mascot/manifest.json");
  afficherEcran("ecran-final");
}

function terminerMascotteCode() {
  if (moteurActuel === "3d" && sourcePersonnage3d === "image" && !spec3dTerminee) {
    afficherBandeau("Crée d'abord le personnage 3D à partir de ton image.", "avertissement");
    return;
  }
  afficherFinalCode();
}

async function copierCodeIntegration() {
  if (!codeIntegrationActuel) { return; }
  var bouton = $("btn-copier-code");
  var texteInitial = bouton.textContent;
  var zone = null;
  occuper(bouton, "Copie…");
  try {
    if (navigator.clipboard && navigator.clipboard.writeText) {
      await navigator.clipboard.writeText(codeIntegrationActuel);
    } else {
      zone = document.createElement("textarea");
      zone.value = codeIntegrationActuel;
      zone.setAttribute("readonly", "");
      zone.style.position = "fixed";
      zone.style.opacity = "0";
      document.body.appendChild(zone);
      zone.select();
      if (!document.execCommand("copy")) { throw new Error("copie refusée"); }
      document.body.removeChild(zone);
    }
    liberer(bouton);
    bouton.textContent = "Copié ✓";
    $("retour-copie").textContent = "Le code est dans ton presse-papiers.";
    setTimeout(function () { bouton.textContent = texteInitial; }, 1800);
  } catch (e) {
    if (zone && zone.parentNode) { zone.parentNode.removeChild(zone); }
    liberer(bouton);
    $("retour-copie").textContent = "La copie a échoué. Sélectionne le code manuellement.";
    afficherBandeau("La copie a échoué. Sélectionne le code, puis copie-le manuellement.", "erreur");
  }
}

async function exporterDossierCode() {
  if (!moteurActuel || !moteurs) { return; }
  var moteurExporte = moteurActuel;
  var configExportee = Object.assign({}, obtenirConfigurationCode(moteurExporte));
  var bouton = $("btn-export-code");
  occuper(bouton, "Préparation du zip…");
  var r = await api("/api/engines/" + encodeURIComponent(moteurExporte) + "/export", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ config: configExportee })
  });
  liberer(bouton);
  actualiserDisponibiliteExportCode();
  if (gererErreurReseau(r, "export de la mascotte en code")) { return; }
  if (r.statut !== 200 || !r.corps || !r.corps.download_url) {
    afficherBandeau(messageErreur(r, "L'export a échoué"), "erreur");
    return;
  }
  if (moteurActuel !== moteurExporte ||
      JSON.stringify(obtenirConfigurationCode(moteurExporte)) !== JSON.stringify(configExportee)) {
    return;
  }
  cacherBandeau();
  var lien = $("lien-telechargement-code");
  lien.href = r.corps.download_url;
  lien.classList.remove("cache");
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

function falEstDisponible() {
  return !!clesNavigateur.fal || !sante || sante.fal_key_configured === true;
}

function visionEstDisponible() {
  if (fournisseurVision === "openrouter") { return !!clesNavigateur.openrouter; }
  return falEstDisponible();
}

function actualiserCapacites() {
  if (!sante) { return; }
  var message = $("message-capacite-fal");
  var falDisponible = falEstDisponible();
  var visionDisponible = visionEstDisponible();
  var explications = [];
  if (!falDisponible) { explications.push("Pour la vidéo IA, colle ta clé fal.ai dans Réglages."); }
  if (!visionDisponible) {
    explications.push(
      "Pour la version 3D, colle ta clé " +
      (fournisseurVision === "openrouter" ? "OpenRouter" : "fal.ai") + " dans Réglages."
    );
  }
  if (explications.length) {
    $("texte-capacite-fal").textContent = explications.join(" ");
    message.classList.remove("cache");
  } else {
    $("texte-capacite-fal").textContent = "";
    message.classList.add("cache");
  }

  if (visionDisponible) {
    $("info-capacite-3d").textContent =
      "Lecture par " +
      (fournisseurVision === "openrouter" ? "OpenRouter direct" : "fal.ai") +
      ". Node 18 ou plus est aussi requis.";
  } else {
    $("info-capacite-3d").textContent =
      "Indisponible : colle ta clé " +
      (fournisseurVision === "openrouter" ? "OpenRouter" : "fal.ai") +
      " dans Réglages. Node 18 ou plus est aussi requis.";
  }
  $("ouvrir-reglages-3d").classList.toggle("cache", visionDisponible);
  $("btn-prompt").disabled = !falDisponible;
  var fichierVideo = $("fichier").files && $("fichier").files.length > 0;
  $("btn-upload").disabled = !falDisponible || !fichierVideo;
  majFichierPersonnage3d();
  majEstimation();

  if (!falDisponible && !jobId) {
    $("statut-job").textContent = "Colle ta clé fal.ai dans Réglages pour lancer la vidéo IA.";
  } else if (!sante.ffmpeg_available && !jobId) {
    $("statut-job").textContent =
      "Installe ffmpeg sur le serveur pour obtenir un fond transparent. La génération reste disponible.";
  }
}

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
  sante = r.corps;
  actualiserEtatCles();
}

/* ---------- Étape 1 : onglets ---------- */

function basculerOnglet(versPrompt) {
  $("onglet-upload").classList.toggle("actif", !versPrompt);
  $("onglet-prompt").classList.toggle("actif", versPrompt);
  $("onglet-upload").setAttribute("aria-selected", String(!versPrompt));
  $("onglet-prompt").setAttribute("aria-selected", String(versPrompt));
  $("panneau-upload").classList.toggle("cache", versPrompt);
  $("panneau-prompt").classList.toggle("cache", !versPrompt);
  majEstimation();
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
  $("info-personnage").textContent = "Ton personnage est prêt. Tu peux maintenant lui donner vie.";
  reinitialiserJob();
  $("etape-2").classList.remove("cache");
  $("btn-relancer").classList.add("cache");
  majEstimation();
  cacherBandeau();
  $("etape-2").scrollIntoView({ behavior: "smooth", block: "start" });
}

function reinitialiserJob() {
  arreterPoll();
  jobId = null;
  history.replaceState(null, "", location.pathname);
  $("statut-job").textContent = "";
  $("liste-etats").innerHTML = "";
  $("scene").innerHTML = "";
  $("controles-etats").innerHTML = "";
  $("bloc-suivi").classList.add("cache");
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
  var r = await api("/api/character/from-upload", { method: "POST", body: donnees }, "fal");
  liberer(bouton);
  if (gererErreurReseau(r, "envoi de l'image")) { return; }
  if (r.statut !== 200 || !r.corps || !r.corps.character_id) {
    afficherBandeau(messageErreur(r, "L'envoi de l'image a échoué"), "erreur");
    return;
  }
  personnagePret(r.corps.character_id, r.corps.image_url, "image choisie");
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
  }, "fal");
  liberer(bouton);
  if (gererErreurReseau(r, "génération du personnage")) { return; }
  if (r.statut !== 200 || !r.corps || !r.corps.character_id) {
    afficherBandeau(messageErreur(r, "La génération du personnage a échoué"), "erreur");
    return;
  }
  rafraichirCout();
  personnagePret(r.corps.character_id, r.corps.image_url, "description");
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
  var selection = presets.presets[usageActuel] ? usageActuel : presets.default;
  usageActuel = selection;
  select.value = selection;
  appliquerPreset(selection);
  actualiserUsageInterface();
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
    var nom;
    if (LIBELLES_ETATS[etat.name]) {
      nom = document.createElement("span");
      nom.className = "nom-etat-fr";
      nom.textContent = libelleEtat(etat.name);
    } else {
      nom = document.createElement("input");
      nom.type = "text";
      nom.value = etat.name;
      nom.className = "champ-nom";
      nom.setAttribute("aria-label", "Nom du nouvel état " + (index + 1));
      nom.placeholder = "Nom du nouvel état";
      nom.addEventListener("input", function () {
        etat.name = nom.value.trim().toLowerCase();
        nom.classList.toggle("invalide", !NOM_VALIDE.test(etat.name));
        majEstimation();
      });
    }

    var mouvement = document.createElement("input");
    mouvement.type = "text";
    mouvement.value = etat.prompt;
    mouvement.className = "champ-mouvement";
    mouvement.maxLength = 300;
    mouvement.setAttribute("aria-label", "Description du mouvement pour " + libelleEtat(etat.name));
    mouvement.placeholder = "Décris son mouvement";
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
    boucle.appendChild(document.createTextNode(" En boucle"));

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
    if (!NOM_VALIDE.test(e.name)) { return "Donne un nom simple au nouvel état : lettres, chiffres et tirets."; }
    if (vus[e.name]) { return "L'état « " + libelleEtat(e.name) + " » apparaît deux fois."; }
    vus[e.name] = true;
    if (!e.prompt.trim()) { return "Décris le mouvement de « " + libelleEtat(e.name) + " »."; }
  }
  if (!etatsEdites.some(function (e) { return e.loop; })) {
    return "Garde au moins un état en boucle : la mascotte le joue au repos.";
  }
  return null;
}

function majEstimation() {
  var probleme = problemeEtats();
  var cible = $("estimation");
  var prix = presets ? etatsEdites.length * presets.cost_per_state_usd : NaN;
  if (probleme) {
    cible.textContent = probleme;
    cible.classList.add("alerte");
  } else {
    cible.textContent = etatsEdites.length + " réaction" + (etatsEdites.length > 1 ? "s" : "") + " choisie" +
      (etatsEdites.length > 1 ? "s" : "") + ".";
    cible.classList.remove("alerte");
  }
  if (!$("btn-generer").classList.contains("occupe") && !isNaN(prix)) {
    $("btn-generer").textContent = etatsEdites.length === 1
      ? "Générer 1 état, environ " + formaterMontant(prix)
      : "Générer les " + etatsEdites.length + " états, environ " + formaterMontant(prix);
  }
  if (characterId && !$("btn-generer").classList.contains("occupe") && !intervallePoll) {
    $("btn-generer").disabled = !!probleme || !falEstDisponible();
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
    nom.textContent = libelleEtat(nomEtat);
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
  }, "fal");
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
  var r = await api(
    "/api/jobs/" + encodeURIComponent(jobId) + "/retry",
    { method: "POST" },
    "fal"
  );
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
    },
    "fal"
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
    majEstimation();
    $("btn-relancer").classList.add("cache");
    afficherApercu(job);
    afficherEcran("ecran-final");
    rafraichirCout();
  } else if (job.status === "failed") {
    arreterPoll();
    $("statut-job").textContent = "Des états ont échoué : le détail s'affiche sous chacun.";
    majEstimation();
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

  var suivi = job.states.look && job.states.look.kind === "look" ? job.states.look : null;
  var prixSuivi = presets ? ", environ " + formaterMontant(presets.look_cost_usd) : "";
  $("btn-suivi").textContent =
    (suivi && suivi.status === "done" ? "Refaire le suivi du curseur" : "Ajouter le suivi du curseur") + prixSuivi;
  $("suivi-texte").textContent = suivi && suivi.status === "done"
    ? "Suivi du curseur actif : bouge la souris autour de la page, la tête la suit au repos."
    : "Suivi du curseur : au repos, la tête regarde vers la souris (clip de 8 secondes).";
  $("bloc-suivi").classList.remove("cache");
  $("bloc-export-video").classList.remove("cache");
  $("bloc-export-code").classList.add("cache");
  $("titre-final").textContent = "Présente-la à ton public.";
  $("sous-titre-final").textContent = "Teste ses réactions, puis copie le code dans ton projet.";
  definirCodeIntegration("./mascot/manifest.json");

  var controles = $("controles-etats");
  controles.innerHTML = "";
  Object.keys(job.states).forEach(function (nom) {
    if (job.states[nom].kind === "look") { return; } // pas un état jouable
    var bouton = document.createElement("button");
    bouton.type = "button";
    bouton.textContent = libelleEtat(nom);
    bouton.dataset.etat = nom;
    bouton.setAttribute("aria-pressed", String(nom === job.default_state));
    bouton.addEventListener("click", function () { avatar.play(nom); });
    controles.appendChild(bouton);
  });
  avatar.addEventListener("statechange", function (ev) {
    var boutons = controles.querySelectorAll("button");
    for (var i = 0; i < boutons.length; i++) {
      boutons[i].setAttribute("aria-pressed", String(boutons[i].dataset.etat === ev.detail.to));
    }
  });
}

async function ajouterSuivi() {
  if (!jobId) { return; }
  var bouton = $("btn-suivi");
  occuper(bouton, "Envoi…");
  var r = await api("/api/jobs/" + encodeURIComponent(jobId) + "/look", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: "{}"
  }, "fal");
  liberer(bouton);
  if (gererErreurReseau(r, "ajout du suivi du curseur")) { return; }
  if (r.statut !== 200) {
    if (r.statut === 429) { rafraichirCout(); }
    afficherBandeau(messageErreur(r, "L'ajout du suivi du curseur a échoué"), "erreur");
    return;
  }
  cacherBandeau();
  suivreJob(jobId);
}

function changerFond(classe, idScene) {
  var scene = $(idScene || "scene");
  scene.classList.remove("fond-creme", "fond-damier", "fond-clair", "fond-sombre");
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
  $("compteur-cout").classList.remove("cache");
  basculerStyle("video");
  $("sur-titre-personnalisation").textContent = "Vidéo IA";
  $("titre-personnalisation").textContent = "Ta mascotte prend vie.";
  $("description-style").textContent = "Tu peux fermer cette page et revenir avec la même adresse.";
  $("etape-1").classList.add("cache");
  $("etape-2").classList.remove("cache");
  $("statut-job").textContent = "Reprise du suivi…";
  $("btn-generer").disabled = true;
  afficherEcran("ecran-personnalisation");
  suivreJob(trouve[1]);
}

/* ---------- Initialisation ---------- */

function init() {
  chargerReglages();
  $("btn-agents").addEventListener("click", ouvrirAgents);
  $("fermer-agents").addEventListener("click", fermerAgents);
  $("voile-agents").addEventListener("click", fermerAgents);
  document.querySelectorAll(".bouton-copie-agent").forEach(function (bouton) {
    bouton.addEventListener("click", function () { copierBlocAgent(bouton); });
  });
  $("btn-reglages").addEventListener("click", ouvrirReglages);
  $("fermer-reglages").addEventListener("click", fermerReglages);
  $("voile-reglages").addEventListener("click", fermerReglages);
  $("ouvrir-reglages-capacite").addEventListener("click", ouvrirReglages);
  $("ouvrir-reglages-3d").addEventListener("click", ouvrirReglages);
  $("cle-fal").addEventListener("input", lireChampsReglages);
  $("cle-openrouter").addEventListener("input", lireChampsReglages);
  $("fournisseur-vision").addEventListener("change", lireChampsReglages);
  $("se-souvenir").addEventListener("change", enregistrerReglages);
  $("tester-cle-fal").addEventListener("click", function () { testerCle("fal"); });
  $("tester-cle-openrouter").addEventListener("click", function () { testerCle("openrouter"); });
  $("effacer-cle-fal").addEventListener("click", function () { effacerCle("fal"); });
  $("effacer-cle-openrouter").addEventListener("click", function () { effacerCle("openrouter"); });
  document.querySelectorAll(".afficher-secret").forEach(function (bouton) {
    bouton.addEventListener("click", function () { basculerVisibiliteCle(bouton); });
  });
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "Escape" && !$("panneau-agents").classList.contains("cache")) {
      fermerAgents();
    } else if (ev.key === "Escape" && !$("panneau-reglages").classList.contains("cache")) {
      fermerReglages();
    }
  });

  $("choix-agent").addEventListener("click", function () { choisirUsage("agent"); });
  $("choix-site").addEventListener("click", function () { choisirUsage("site"); });
  $("btn-methode-3d").addEventListener("click", function () { choisirMethode("3d"); });
  $("btn-methode-blob").addEventListener("click", function () { choisirMethode("blob"); });
  $("btn-methode-video").addEventListener("click", function () {
    if (!falEstDisponible()) { ouvrirReglages(); return; }
    choisirMethode("video");
  });
  $("btn-methode-image3d").addEventListener("click", function () {
    if (!visionEstDisponible()) { ouvrirReglages(); return; }
    choisirMethode("image3d");
  });
  $("btn-accueil").addEventListener("click", function () { afficherEcran("ecran-accueil"); });
  $("btn-recommencer").addEventListener("click", function () { afficherEcran("ecran-accueil"); });
  $("retour-accueil").addEventListener("click", function () { afficherEcran("ecran-accueil"); });
  $("retour-creation").addEventListener("click", function () { afficherEcran("ecran-creation"); });
  $("retour-personnalisation").addEventListener("click", function () {
    afficherEcran("ecran-personnalisation");
  });
  $("onglet-3d-galerie").addEventListener("click", function () {
    basculerSourcePersonnage3d("galerie");
  });
  $("onglet-3d-image").addEventListener("click", function () {
    basculerSourcePersonnage3d("image");
  });
  $("onglet-upload").addEventListener("click", function () { basculerOnglet(false); });
  $("onglet-prompt").addEventListener("click", function () { basculerOnglet(true); });

  $("fichier-3d").addEventListener("change", majFichierPersonnage3d);
  $("apercu-fichier-3d").addEventListener("error", function () {
    $("fichier-3d").value = "";
    majFichierPersonnage3d();
    afficherBandeau(
      "Ce fichier ne se lit pas comme une image. Choisis un PNG, un JPEG ou un WebP.",
      "erreur"
    );
  });
  $("btn-creer-3d").addEventListener("click", creerPersonnage3d);

  $("fichier").addEventListener("change", function () {
    var input = $("fichier");
    var zone = $("zone-texte");
    if (input.files && input.files.length > 0) {
      zone.textContent = "Fichier choisi : " + input.files[0].name + " (clique pour en changer)";
      zone.classList.add("fichier-choisi");
      $("btn-upload").disabled = !falEstDisponible();
      majApercuFichier(input.files[0]);
    } else {
      zone.textContent = "Choisis ton image · PNG détouré conseillé · 10 Mo max";
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
  $("usage").addEventListener("change", function () {
    usageActuel = $("usage").value;
    appliquerPreset(usageActuel);
    actualiserUsageInterface();
  });
  $("btn-ajouter-etat").addEventListener("click", ajouterEtat);
  $("btn-generer").addEventListener("click", lancerGeneration);
  $("btn-relancer").addEventListener("click", relancerEchecs);
  $("btn-terminer-code").addEventListener("click", terminerMascotteCode);
  $("btn-copier-code").addEventListener("click", copierCodeIntegration);
  $("btn-export").addEventListener("click", exporterDossier);
  $("btn-export-code").addEventListener("click", exporterDossierCode);
  $("btn-suivi").addEventListener("click", ajouterSuivi);
  $("bandeau-fermer").addEventListener("click", cacherBandeau);
  $("controles-fond").addEventListener("click", function (ev) {
    var fond = ev.target.dataset && ev.target.dataset.fond;
    if (fond) { changerFond(fond); }
  });

  afficherEcran("ecran-accueil");
  verifierSante();
  chargerMoteurs();
  chargerPresets().then(reprendreJobDepuisUrl);
}

document.addEventListener("DOMContentLoaded", init);
