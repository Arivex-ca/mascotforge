---
name: mascotforge
description: Créer, exporter et intégrer une mascotte ou un avatar animé avec MascotForge. Utiliser quand l'utilisateur demande une « mascotte », un « avatar animé », « donner un visage à mon agent », un personnage réactif pour un agent IA ou un site, ou l'intégration des états idle, thinking, talking et error. Interroge l'utilisateur sur le personnage et la réaction de chaque état avant d'écrire les prompts, et sait générer l'image de base avec l'outil d'image de l'agent, sans clé fal.
---

# MascotForge

Créer une mascotte, choisir le parcours le moins coûteux, l'exporter, puis brancher ses états sur le projet.

## Préparer MascotForge

1. Lancer le serveur depuis le dépôt :

   ```bash
   python -m uvicorn backend.main:app --port 8766 --env-file .env
   ```

2. Définir `MASCOTFORGE_URL`, par défaut `http://localhost:8766`.
3. Pour le studio, coller les clés dans Réglages. Pour la CLI ou le MCP, définir `MASCOTFORGE_FAL_KEY` et, si nécessaire, `MASCOTFORGE_OPENROUTER_KEY` dans le processus de l'agent.
4. Lister les choix et les estimations :

   ```bash
   python -m mascotforge styles
   ```

   Équivalent MCP : `mascotforge_styles`.

## Interroger l'utilisateur avant d'écrire un prompt

Ne jamais inventer seul le prompt du personnage ni ceux des états. Avant toute
génération, mener un interrogatoire jusqu'à pouvoir écrire chaque prompt sans
deviner. Si le skill `interrogatoire` de
[superSkill](https://github.com/TokDar2410621/superSkill) est disponible
(`superskill:interrogatoire` dans Claude Code), l'utiliser pour la forme des
questions. Sinon, appliquer la méthode ci-dessous, qui suffit. On peut
signaler à l'utilisateur qu'il peut installer superSkill
(`claude plugin marketplace add TokDar2410621/superSkill` puis
`claude plugin install superskill@superskill`, ou
`npx skills@latest add TokDar2410621/superSkill`), mais ne jamais l'installer
sans son accord.

### Méthode

- Avant le premier tour, lire le projet (README, page d'accueil, nom de
  l'agent) pour proposer des réponses concrètes. Chercher les faits soi-même,
  ne poser à l'utilisateur que les décisions.
- Procéder par tours. Un tour = un appel à l'outil de questions du harnais
  (`AskUserQuestion` dans Claude Code, `request_user_input` dans Codex en mode
  Plan, `ask_user` dans Gemini CLI), au plus 4 questions et 2 à 4 options par
  question.
- Première option = la réponse recommandée, libellé terminé par
  « (Recommandé) », avec la raison dans la description. L'utilisateur peut
  toujours répondre en texte libre.
- Ne poser une question que si les réponses dont elle dépend sont connues. Une
  question qui dépend d'une autre question du même tour attend le tour suivant.
- Sans outil de questions, poser le tour en texte : questions numérotées, la
  recommandation sous chacune, formulées pour que « oui » accepte la
  recommandation.

### Tours

1. **Contexte** : à quoi sert la mascotte (agent IA, site web, les deux) ; ce
   que fait le produit et pour qui ; la personnalité (calme et rassurante,
   joueuse, experte sérieuse, espiègle) ; le point de départ (image existante,
   image générée par l'agent, mascotte en code gratuite).
2. **Personnage**, si l'image est à générer : espèce ou objet, couleur
   dominante, accessoire, style (peluche kawaii, vinyle lisse, dessin plat).
   Proposer des options qui découlent du produit et de la personnalité.
3. **États** (choix multiple) : partir du preset qui correspond à l'usage
   (`agent` : idle, thinking, talking, error ; `site` : idle, clicked,
   sleeping), puis proposer les états utiles à ce projet : `listening`,
   `working`, `done`, `happy`, `waiting`. Rappeler le prix par état
   (`mascotforge styles`). Douze états au maximum.
4. **Réaction de chaque état**, jusqu'à 4 états par tour : « Dans l'état
   `thinking`, que fait <nom> ? », avec 3 réactions concrètes qui respectent la
   personnalité choisie. L'agent décide lui-même si l'état boucle (états
   continus : idle, thinking, talking, working) ou joue une fois (événements :
   error, done, clicked), et ne pose la question qu'en cas de doute.
5. **Récapitulatif** : montrer le prompt de l'image, puis un tableau
   nom / boucle / prompt anglais pour chaque état, et le prix total. Ne rien
   générer avant que l'utilisateur confirme ce récapitulatif.

### Écrire le prompt d'un état

- En anglais, 300 caractères au maximum, une seule action principale.
- Décrire d'abord le changement du visage (yeux, bouche), puis le geste du
  corps. Kling garde le visage de l'image si le prompt ne le nomme pas.
- Pour un état en boucle, des mouvements petits et réguliers. Pour un
  événement, un geste net qui revient à la pose de départ.
- Pas de caméra, de décor, de texte ni d'objet qui apparaît (pas d'ordinateur
  ni de tasse) : MascotForge les interdit déjà, et ils cassent le détourage.
  Seul un accessoire visible sur l'image de base peut bouger.
- Ne pas répéter ce que MascotForge ajoute déjà : même personnage, caméra
  fixe, retour à la pose de départ, fond vert.
- Nom de l'état : minuscules, chiffres et tirets, commence par une lettre,
  32 caractères au maximum. `look` est réservé. Au moins un état boucle.

Enregistrer les états validés dans un fichier JSON :

```json
[
  {"name": "idle", "prompt": "calm face, slow blinking, gentle breathing sway", "loop": true},
  {"name": "thinking", "prompt": "eyes look up and to the side, small mouth pout, slow head tilt", "loop": true},
  {"name": "done", "prompt": "eyes close into happy arcs, big smile, proud little hop", "loop": false}
]
```

## Choisir le parcours

### Blob gratuit

Utiliser un blob pour une mascotte légère et personnalisable.

```bash
python -m mascotforge code --engine blob --set shape=cloud --out ./mascotte
```

MCP : `mascotforge_code(engine="blob", config={"shape":"cloud"}, out="./mascotte")`.

### Blob gratuit dessiné par l'agent

Utiliser ce parcours pour une silhouette absente des huit formes, par exemple
des cornes, des oreilles, une étoile ou un haricot tordu. La fiche ne contient
que des données JSON. Répéter le check et la preview après chaque correction.

```bash
python -m mascotforge blob guide --out ./guide-blob.md
python -m mascotforge blob check ./blob.json
python -m mascotforge blob preview ./blob.json --out ./planche.png
python -m mascotforge blob export ./blob.json --out ./mascotte
```

MCP : appeler dans cet ordre `mascotforge_blob_guide`,
`mascotforge_blob_check`, `mascotforge_blob_preview`, puis
`mascotforge_blob_export`.

### Personnage 3D gratuit de la galerie

Choisir un personnage Wobnimo existant.

```bash
python -m mascotforge code --engine 3d --set character=volt --out ./mascotte
```

MCP : `mascotforge_code(engine="3d", config={"character":"volt"}, out="./mascotte")`.

### Personnage 3D gratuit dessiné par l'agent

Utiliser ce parcours si l'agent peut lire l'image de référence. Ne lancer aucun modèle payant.

1. Lire le guide et l'image.
2. Écrire la fiche JSON Wobnimo.
3. Vérifier la fiche.
4. Générer la planche, comparer sa vue de face à l'image, puis corriger.
5. Répéter le check et la preview jusqu'à obtenir une fiche juste.
6. Exporter.

```bash
python -m mascotforge spec guide --out ./guide-wobnimo.md
python -m mascotforge spec check ./personnage.json
python -m mascotforge spec preview ./personnage.json --out ./planche.png
python -m mascotforge spec export ./personnage.json --out ./mascotte
```

MCP : appeler dans cet ordre `mascotforge_spec_guide`, `mascotforge_spec_check`, `mascotforge_spec_preview`, comparer l'image rendue, corriger la fiche, puis appeler `mascotforge_spec_export`.

### Image de base générée par l'agent

Utiliser ce parcours quand l'utilisateur n'a pas d'image et que l'agent dispose
d'un outil de génération d'image (par exemple un MCP Hugging Face comme
Z-Image Turbo, ou tout autre outil d'image déjà connecté). L'image obtenue
sert ensuite d'entrée à la vidéo, à `image3d` ou à la fiche Wobnimo dessinée
par l'agent. Ce parcours remplace la génération Flux de MascotForge.

1. Écrire le prompt en anglais à partir des réponses de l'interrogatoire, en
   trois parties :
   - Cadrage, toujours identique :
     `Mascot character, full body, centered, facing the viewer, on a plain transparent background, no shadow, no ground, no text, no other objects. Character: `
     Si l'outil ne gère pas la transparence, remplacer le fond par
     `on a solid pure bright green (#00FF00) chroma key background`.
   - Personnage : espèce ou objet, couleur dominante, un accessoire au plus.
   - Style : un des blocs ci-dessous, ou celui que demande l'utilisateur.
2. Générer 3 ou 4 variantes, chacune avec un personnage ou un accessoire différent.
3. Regarder chaque image et écarter celles qui ont une ombre au sol, un fond
   dégradé ou teinté, un corps coupé ou du texte.
4. Montrer les variantes et laisser l'utilisateur choisir.
5. Enregistrer l'image retenue en PNG, JPG ou WEBP dans le projet, puis la
   passer à `--image` (vidéo, `image3d`) ou s'en servir de référence pour la
   fiche Wobnimo.

Blocs de style :

| Style | Bloc à ajouter |
|---|---|
| Peluche kawaii | `chubby round plush creature, one soft bean-shaped body with no neck, short stubby arms and legs, short dense fuzzy felt fur with visible fiber texture, two small glossy black bead eyes set wide apart, soft pink blush cheeks, tiny gentle smile, kawaii collectible designer toy, soft 3D render, studio softbox lighting, subtle subsurface glow, clean silhouette` |
| Vinyle lisse | `smooth glossy vinyl designer toy, rounded chunky proportions, big head, simple face, soft 3D render, studio lighting, clean silhouette` |
| Dessin plat | `flat 2D vector illustration, thick clean outlines, limited palette of 3 colors, simple shapes, sticker style` |

Règles :

- Avec un fond vert, ne jamais faire une mascotte verte : le détourage
  effacerait des parties du personnage.
- Pour un personnage à poils, demander `short dense fur` et `clean silhouette` :
  des poils longs gardent un liseré vert après détourage.
- S'inspirer d'un style, jamais d'un personnage existant d'une marque : pas le
  même personnage, pas son nom, pas sa combinaison de forme et de couleurs.
- Le prompt ne contient que la description du personnage, jamais de données
  personnelles ni de nom de projet confidentiel.
- Si l'outil d'image est payant, annoncer son coût et obtenir l'accord avant
  de générer.

### Image vers 3D payante

Obtenir d'abord l'estimation sans `--yes` :

```bash
python -m mascotforge image3d ./image.png --out ./mascotte
```

Après accord explicite, lancer :

```bash
python -m mascotforge image3d ./image.png --out ./mascotte --yes
```

En MCP, appeler `mascotforge_image3d_start(image="./image.png", user_confirmed=false)`, annoncer l'estimation, obtenir l'accord, rappeler avec `user_confirmed=true`, puis utiliser `mascotforge_status` et `mascotforge_export`.

### Vidéo payante

Passer les états de l'interrogatoire avec `--states`. Sans fichier d'états,
`--usage` prend un preset (`agent`, `site`, `complet`).

Obtenir d'abord l'estimation sans `--yes` :

```bash
python -m mascotforge video --image ./image.png --states ./etats.json --out ./mascotte
```

Après accord explicite, lancer :

```bash
python -m mascotforge video --image ./image.png --states ./etats.json --out ./mascotte --yes
```

En MCP, appeler `mascotforge_video_start(image="./image.png", states=[...], user_confirmed=false)`, annoncer l'estimation, obtenir l'accord, rappeler avec `user_confirmed=true`, puis utiliser `mascotforge_status` et `mascotforge_export`.

## Respecter les règles de sécurité

- Ne jamais lancer `image3d`, `video` ou un outil MCP payant sans l'accord explicite de l'utilisateur après annonce de l'estimation.
- Ne jamais placer une clé dans une URL, un log, une commande affichée ou un fichier du projet.
- Transmettre les clés uniquement par Réglages ou par les variables d'environnement prévues.

## Intégrer l'export

1. Copier le dossier exporté dans le projet.
2. Ajouter le composant et son script :

   ```html
   <mascot-avatar id="mascotte" manifest="./mascot/manifest.json" label="Mon assistant"></mascot-avatar>
   <script src="./mascot/mascot.js"></script>
   ```

3. Brancher l'état sur le cycle de l'agent :

   ```js
   const mascotte = document.querySelector("#mascotte");
   mascotte.play("thinking"); // pendant la réflexion
   mascotte.play("talking");  // pendant la réponse
   mascotte.play("error");    // en cas d'échec
   mascotte.play("idle");     // au repos
   ```

Utiliser les états réellement présents dans le manifest. Le widget traduit les équivalences courantes, dont `talking` et `speaking`.
