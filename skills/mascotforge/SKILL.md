---
name: mascotforge
description: Créer, exporter et intégrer une mascotte ou un avatar animé avec MascotForge. Utiliser quand l'utilisateur demande une « mascotte », un « avatar animé », « donner un visage à mon agent », un personnage réactif pour un agent IA ou un site, ou l'intégration des états idle, thinking, talking et error.
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

## Choisir le parcours

### Blob gratuit

Utiliser un blob pour une mascotte légère et personnalisable.

```bash
python -m mascotforge code --engine blob --set shape=cloud --out ./mascotte
```

MCP : `mascotforge_code(engine="blob", config={"shape":"cloud"}, out="./mascotte")`.

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

Obtenir d'abord l'estimation sans `--yes` :

```bash
python -m mascotforge video --image ./image.png --usage agent --out ./mascotte
```

Après accord explicite, lancer :

```bash
python -m mascotforge video --image ./image.png --usage agent --out ./mascotte --yes
```

En MCP, appeler `mascotforge_video_start(usage="agent", image="./image.png", user_confirmed=false)`, annoncer l'estimation, obtenir l'accord, rappeler avec `user_confirmed=true`, puis utiliser `mascotforge_status` et `mascotforge_export`.

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
