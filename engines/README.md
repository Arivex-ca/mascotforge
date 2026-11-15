# Moteurs de mascottes en code (tiers, licence MIT)

MascotForge embarque deux projets open source pour les mascottes dessinées et
animées en code. Chaque dossier garde la licence de son auteur, copiée aussi
dans chaque export.

| Moteur | Auteur | Licence | Source | Version embarquée | SHA-256 |
|---|---|---|---|---|---|
| Blob Atelier (`blob-atelier/agent-mascot.js`) | Victoria Wu | MIT | https://github.com/victoriawu-77/blob-atelier | fork https://github.com/Arivex-ca/blob-atelier, branche `states-accessories-offline`, commit `e611a55` (sur `c76954a` du 2026-10-24) | `341e9eae43524c4a5b16bfc6f50c783ecdb027970c3f99d9ef183315453c96c4` |
| three.js (`blob-atelier/vendor/three.module.min.js`) | three.js authors | MIT | https://github.com/mrdoob/three.js | paquet npm `three@0.170.0`, `build/three.module.min.js`, non modifié | `08fd7545d13d2c7fb65ab691530a802dafefd638596501854f267d0fb13c39e7` |
| Wobnimo (`wobnimo/dist/wobnimo.js`) | Pourya Akhbari | MIT | https://github.com/Pouryaak/wobnimo | paquet npm `wobnimo@0.2.0`, `dist/wobnimo.js` | `85443e0bd564e9e8428aced315346d80c304d647b8859bdb95b5203a2b5752ef` |

Pour créer un personnage Wobnimo à partir d'une image, MascotForge embarque
aussi, du même paquet `wobnimo@0.2.0` (MIT) :

| Fichier | Origine dans le paquet | SHA-256 |
|---|---|---|
| `wobnimo/dist/cli.js` | `dist/cli.js` (vérificateur et aperçu, lancés avec Node) | `1598672f156a2080ed4af46f05fb9a6a634039c5fba4eca1f0e509d66abee906` |
| `wobnimo/skill/SKILL.md` | `skill/SKILL.md` (le guide pour agents) | `3dd7f9a9df7077da6fd7c554f87bb4da3eeb96202622bf7e0b95fafcb40c24fe` |
| `wobnimo/skill/spec.md` | `skill/reference/spec.md` | `93e2901661fd0f424adaef1996ec0bdbe5bf2d79c8118c56b133ec61a3c250ac` |
| `wobnimo/skill/volt.json` | `dist/characters/volt.js`, exporté en JSON | `f1a565b20ae321e0d4a42b939850afca560fe73ace655f886e41a0d7268f2460` |

Le dossier `wobnimo/` reprend l'organisation du paquet (`dist/cli.js` à côté
de `dist/wobnimo.js`) : l'aperçu de `cli.js` cherche le moteur à cet endroit.
`wobnimo/package.json` n'est pas celui du paquet : il déclare seulement
`"type": "module"`, pour que Node lise `cli.js` comme un module.

Ce que MascotForge en utilise :

- Blob Atelier : les blobs (8 formes, 6 matières, contours sur mesure) et les
  8 animaux 3D (3 tissus), avec accessoires et états sur mesure. three.js est
  copié dans `blob-atelier/vendor/` et dans chaque export animal, pour qu'une
  mascotte n'appelle aucun serveur tiers.
- Wobnimo : les 20 personnages et leurs 10 humeurs, via `<wobnimo-mascot>`.

## Fork Blob Atelier

`agent-mascot.js` est le build (`node src/build.js`) du fork Arivex, qui ajoute
au code d'origine (empreinte d'origine
`3c41acab060d3f4e74ce740c303b6f2001745b4d1dc1b5938c7736a294026798`) :

- `AgentMascot.defineState(name, recipe)` : états sur mesure ;
- `AgentMascot.defineAccessory(name, spec)` : accessoires en pièces simples,
  sur les blobs et les animaux 3D ;
- `AgentMascot.THREE_URL` en liste, résolue depuis l'URL du script ;
- `AgentMascot.defineShape(name, points)` : contours sur mesure de 72 points ;
- une mascotte figée (`still`) applique sa couleur tout de suite.

Les 8 états et les 3 accessoires d'origine rendent comme avant (tests du fork).

Mettre à jour un moteur : remplacer le fichier par une version publiée, mettre
à jour ce tableau (version, empreinte) et relancer les tests.
