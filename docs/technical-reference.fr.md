# Référence technique MascotForge

Cette page regroupe les détails d'implémentation, de sécurité, d'API, de fournisseurs et d'agents retirés du README principal.

[Retour au README](../README.fr.md) · [Galerie visuelle](gallery.fr.md) · [Référence anglaise](technical-reference.md)

## Prérequis et exécution

- Python 3.10 ou plus
- ffmpeg et ffprobe dans le PATH, ou `MASCOTFORGE_FFMPEG`
- Node 18 ou plus pour vérifier et rendre les personnages Wobnimo
- Chrome ou Edge pour comparer visuellement les résultats image vers 3D
- Une clé fal.ai pour la vidéo IA
- Une clé OpenRouter uniquement avec la lecture directe d'image par OpenRouter

Sans ffmpeg, la génération vidéo fonctionne et conserve le fond vert. `GET /api/health` indique la disponibilité de ffmpeg et de la clé de repli du serveur.

Lance le serveur :

```bash
.venv/bin/python -m uvicorn backend.main:app --port 8766 --env-file .env
```

`--env-file` charge `FAL_KEY` et les réglages locaux depuis `.env`. Les clés de l'utilisateur arrivent dans des en-têtes dédiés.

## Réglages des clés et sécurité

Le studio accepte une clé fal.ai et une clé OpenRouter facultative.

- Sans « Se souvenir sur cet appareil », le navigateur utilise `sessionStorage`.
- Avec cette option, il utilise `localStorage`.
- Si le navigateur bloque le stockage, le studio garde la clé en mémoire.
- Le navigateur envoie les clés dans `X-Fal-Key` et `X-OpenRouter-Key`.
- `X-Vision-Provider: fal|openrouter` sélectionne le lecteur d'image.
- MascotForge refuse les secrets dans les URL et les paramètres de requête.
- Le serveur n'écrit aucune clé dans les tâches, `data/`, les journaux, les exports ou les réponses.

`FAL_KEY` sert de repli sur un serveur local. Ne la configure pas sur un serveur accessible au public. Les visiteurs sans clé personnelle utiliseraient ce compte. Le plafond mensuel serait aussi partagé entre tous les utilisateurs.

Le test de clé ne lance aucune génération. OpenRouter vérifie la clé par `GET https://openrouter.ai/api/v1/key`. fal.ai utilise sa demande de jeton de stockage sans envoyer de fichier ni exécuter d'inférence.

## Agents, CLI et MCP

Le CLI et le serveur MCP utilisent l'API HTTP. `MASCOTFORGE_URL` pointe par défaut vers `http://localhost:8766`. `MASCOTFORGE_FAL_KEY` et `MASCOTFORGE_OPENROUTER_KEY` fournissent les clés dans des en-têtes dédiés.

### CLI

```bash
python -m mascotforge styles
python -m mascotforge code --engine blob --set shape=cloud --out ./mon-blob
python -m mascotforge code --engine 3d --set character=volt --out ./mon-robot
python -m mascotforge blob guide --out ./guide-blob.md
python -m mascotforge blob check ./blob.json
python -m mascotforge blob preview ./blob.json --out ./planche-blob.png
python -m mascotforge blob export ./blob.json --out ./blob-personnalise
python -m mascotforge image3d ./robot.png --out ./robot-3d
python -m mascotforge video --image ./robot.png --usage agent --out ./robot-video
python -m mascotforge video --prompt "un petit renard orange" --usage site --out ./renard
python -m mascotforge status ID
python -m mascotforge export ID --out ./export
python -m mascotforge cost
```

Ajoute `--json` pour obtenir une sortie lisible par un agent. `image3d` et `video` sont payants. Sans `--yes`, ces commandes affichent le prix estimé et quittent avant la génération. Relance avec `--yes` uniquement après l'approbation du coût.

### Boucle Blob personnalisée

Un agent peut décrire une superellipse et ses bosses dans une fiche JSON. Le vérificateur refuse les intersections, les contours trop fins, les formes hors du cadre et les valeurs hors limites.

```bash
python -m mascotforge blob guide --out ./guide-blob.md
python -m mascotforge blob check ./blob.json
python -m mascotforge blob preview ./blob.json --out ./planche-blob.png
python -m mascotforge blob export ./blob.json --out ./blob-personnalise
```

L'aperçu montre chaque état avant l'export.

### Boucle visuelle Wobnimo

Un agent capable de voir une image peut écrire une fiche Wobnimo sans appel fournisseur :

1. Lire le guide et inspecter l'image de référence.
2. Écrire la fiche JSON et lancer le vérificateur.
3. Rendre la planche et comparer la vue de face avec la source.
4. Corriger la fiche, puis répéter la vérification et l'aperçu.
5. Enregistrer ou exporter le résultat.

```bash
python -m mascotforge spec guide --out ./guide-wobnimo.md
python -m mascotforge spec check ./personnage.json
python -m mascotforge spec preview ./personnage.json --out ./planche.png
python -m mascotforge spec save ./personnage.json
python -m mascotforge spec export ./personnage.json --out ./personnage-3d
```

### MCP par stdio

```bash
python -m mascotforge mcp
```

Les créations longues utilisent trois appels : un outil de démarrage, `mascotforge_status`, puis `mascotforge_export`. Les outils payants exigent `user_confirmed=true`.

Les outils gratuits de fiche et de Blob renvoient les aperçus sous forme d'images MCP. L'agent peut inspecter et corriger le résultat avant l'export.

Configuration Claude Desktop dans `%APPDATA%\Claude\claude_desktop_config.json` :

```json
{
  "mcpServers": {
    "mascotforge": {
      "command": "C:\\chemin\\vers\\mascotforge\\.venv\\Scripts\\python.exe",
      "args": ["-m", "mascotforge", "mcp"],
      "env": {"MASCOTFORGE_URL": "http://localhost:8766"}
    }
  }
}
```

Cursor utilise le même bloc dans `.cursor/mcp.json`.

Configuration Codex CLI et application dans `~/.codex/config.toml` :

```toml
[mcp_servers.mascotforge]
command = 'C:\chemin\vers\mascotforge\.venv\Scripts\python.exe'
args = ["-m", "mascotforge", "mcp"]
cwd = 'C:\chemin\vers\mascotforge'
env = { MASCOTFORGE_URL = "http://localhost:8766" }
```

Codex CLI et l'application lisent le même fichier. Si tu retires `cwd`, ajoute `PYTHONPATH` à la table d'environnement.

Avec `codex exec`, personne ne peut approuver un appel MCP. Ajoute `default_tools_approval_mode = "approve"` à ce bloc serveur et lance `codex exec -c 'approval_policy="never"'` uniquement dans un environnement où tu fais déjà confiance aux outils MascotForge configurés.

### Skill Agent Skills

```bash
python -m mascotforge skill
python -m mascotforge skill --dir DOSSIER_CIBLE
```

La commande copie le skill dans `.claude/skills/mascotforge/` et `.agents/skills/mascotforge/`. Elle préserve les fichiers locaux modifiés. Utilise `--force` uniquement après approbation du remplacement.

## API

| Méthode | Route | Description |
|---|---|---|
| GET | `/api/health` | Santé, ffmpeg et état de la clé serveur |
| POST | `/api/keys/test` | Tester une clé fournisseur reçue dans un en-tête |
| GET | `/api/presets` | Modèles d'états, limite et coût |
| POST | `/api/character/from-prompt` | Créer un personnage de base depuis un prompt |
| POST | `/api/character/from-upload` | Envoyer une image de base, 10 Mo maximum |
| POST | `/api/generate` | Démarrer la génération des états |
| GET | `/api/jobs/{job_id}` | Lire le statut, les états, les erreurs et le coût |
| POST | `/api/jobs/{job_id}/retry` | Relancer les états en échec |
| POST | `/api/jobs/{job_id}/states/{state}/regenerate` | Régénérer un état |
| POST | `/api/jobs/{job_id}/look` | Générer le suivi du curseur |
| GET | `/api/jobs/{job_id}/manifest.json` | Lire le manifeste d'aperçu |
| POST | `/api/export/{job_id}` | Construire l'archive d'export |
| GET | `/api/engines` | Lister les moteurs et leurs réglages |
| GET | `/api/engines/blob/guide` | Lire le guide Blob personnalisé |
| GET | `/api/engines/3d/guide` | Lire le guide des fiches Wobnimo |
| POST | `/api/engines/blob/specs/check` | Vérifier une fiche Blob personnalisée |
| POST | `/api/engines/blob/specs/preview` | Rendre l'aperçu d'un Blob personnalisé |
| POST | `/api/engines/blob/specs/export` | Exporter un Blob personnalisé |
| POST | `/api/engines/3d/specs/check` | Vérifier une fiche Wobnimo |
| POST | `/api/engines/3d/specs/preview` | Rendre un aperçu Wobnimo |
| POST | `/api/engines/3d/specs` | Enregistrer une fiche Wobnimo |
| POST | `/api/engines/3d/from-image` | Démarrer une création image vers 3D |
| GET | `/api/engines/3d/specs/{spec_id}` | Lire le statut image vers 3D |
| GET | `/api/engines/{engine}/manifest.json` | Prévisualiser une mascotte en code |
| POST | `/api/engines/{engine}/export` | Exporter une mascotte en code |
| GET | `/api/exports/{filename}` | Télécharger un export |
| GET | `/videos/{job_id}/{filename}` | Lire un clip généré |
| GET | `/api/cost` | Lire les dépenses, réservations et le plafond |

Les erreurs API renvoient un message français propre. Les détails fal.ai et ffmpeg restent dans les journaux du serveur.

## Modèles fournisseurs et coûts

Des variables d'environnement permettent de remplacer les modèles :

- Texte vers image : `fal-ai/flux/dev` par `MASCOTFORGE_TTI_MODEL`
- Image vers vidéo : `fal-ai/kling-video/v3/standard/image-to-video` par `MASCOTFORGE_I2V_MODEL`
- Repli vidéo : `fal-ai/kling-video/v3/pro/image-to-video` par `MASCOTFORGE_FALLBACK_MODEL`
- Fiche image vers 3D : `anthropic/claude-sonnet-5.5` par `MASCOTFORGE_SPEC_MODEL`

Tarifs relevés dans le projet :

- Kling 3.0 standard sans audio : 0,084 $ par seconde le 2026-10-30
- Un état de trois secondes : environ 0,25 $
- Mascotte de quatre états : environ 1 $, plus 0,025 $ pour une image créée par prompt
- Suivi du curseur : environ 0,67 $ pour un clip de huit secondes
- Image vers 3D : environ 0,15 à 0,60 $ selon les corrections

`MASCOTFORGE_MONTHLY_CAP_USD` définit le plafond mensuel partagé, 50 $ par défaut. MascotForge réserve l'estimation avant la génération pour empêcher des tâches simultanées de dépasser le plafond ensemble.

## Format d'export

`POST /api/export/{job_id}` crée :

```text
mascot/
  mascot.js
  manifest.json
  videos/
  README.md
```

Le manifeste V2 stocke l'état par défaut, le mode alpha, les sources, le comportement des boucles et les modèles. Les manifestes de mascottes en code stockent aussi le moteur, sa source, sa configuration et la fiche personnalisée éventuelle.

## Widget

```html
<mascot-avatar manifest="./mascot/manifest.json" label="Mon assistant"></mascot-avatar>
<script src="./mascot/mascot.js"></script>
```

Les méthodes publiques comprennent `play(state, { immediate })`, `wake()` et `getState()`.

Attributs disponibles :

- `click-state`
- `sleep-state`
- `sleep-after`
- `switch="loop-end|immediate"`
- `parallax`
- `follow-cursor`
- `label`

Le widget lit les manifestes V1 et V2. Des alias communs permettent à `talking` de fonctionner avec un moteur qui nomme l'état `speaking`, et à `happy` de fonctionner avec `celebrating`.

## Mascottes en code

| Style | Moteur | États |
|---|---|---|
| Blob | Blob Atelier, Victoria Wu, MIT | Huit formes intégrées, six matières, couleur libre, yeux, joues, accessoires et états personnalisés |
| 3D | Wobnimo, Pourya Akhbari, MIT | Vingt personnages intégrés, dix états courants et fiches JSON personnalisées |

L'export inclut le moteur choisi et sa licence. Les mascottes en code n'appellent aucun fournisseur à l'exécution.

## Personnage 3D depuis une image

1. Le fournisseur choisi lit l'image source. fal.ai l'envoie vers son stockage. OpenRouter direct transmet une URL de données base64 en mémoire et ne place pas l'image dans le stockage fal.ai.
2. Un modèle de vision écrit une fiche JSON Wobnimo.
3. Le vérificateur Wobnimo mesure la géométrie et renvoie des corrections précises.
4. Chrome ou Edge rend un aperçu lorsqu'il est disponible. `MASCOTFORGE_BROWSER` peut pointer vers l'exécutable du navigateur.
5. Le modèle compare la source avec l'aperçu et peut corriger la fiche deux fois.
6. MascotForge vérifie chaque correction et exporte la fiche validée.

Le résultat interprète la source dans le style de Wobnimo. Le vérificateur valide la géométrie. La comparaison visuelle traite la ressemblance.

## Suivi du curseur

MascotForge génère un clip de huit secondes dans lequel la tête regarde à gauche, à droite, en haut et en bas. Le détourage mesure la direction du regard dans chaque image et écrit une table de correspondance dans le manifeste.

Au repos, le widget affiche l'image la plus proche de la direction du curseur. Un appel `play()` arrête le suivi. Le clip se charge après le premier mouvement de souris. Le suivi reste coupé sur les appareils tactiles, avec les mouvements réduits ou lorsque `follow-cursor="false"`.

## Tests

```bash
.venv/bin/python -m pytest tests/ -v
```

fal.ai et OpenRouter sont simulés. `tests/test_alpha.py` exécute le vrai ffmpeg sur un clip synthétique. Les tests Chromium passent en skip sans Playwright. `widget/smoke.html` fournit un contrôle navigateur.

## Fichiers principaux

- `backend/main.py` : routes FastAPI et fichiers statiques
- `backend/blob.py` : fiches Blob, vérifications, aperçus et exports
- `backend/fal.py` : client fal.ai
- `backend/openrouter.py` : client OpenRouter direct
- `backend/alpha.py` : détourage et mesure du regard
- `backend/pipeline.py` : tâches, repli, reprises et redémarrage
- `backend/cost.py` : dépenses, réservations et plafond
- `backend/exporter.py` : génération du manifeste et de l'archive
- `backend/engines.py` : moteurs en code et manifestes
- `backend/image3d.py` : parcours image vers Wobnimo
- `mascotforge/` : CLI, client et serveur MCP
- `widget/mascot-avatar.js` : Web Component
- `studio/` : interface navigateur
- `skills/mascotforge/` : skill Agent Skills

