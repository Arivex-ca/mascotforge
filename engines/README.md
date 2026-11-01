# Moteurs de mascottes en code (tiers, licence MIT)

MascotForge reprend tels quels deux projets open source pour les mascottes
dessinées et animées en code. Les fichiers ne sont pas modifiés ; chaque
dossier garde la licence de son auteur, copiée aussi dans chaque export.

| Moteur | Auteur | Licence | Source | Version embarquée | SHA-256 |
|---|---|---|---|---|---|
| Blob Atelier (`blob-atelier/agent-mascot.js`) | Victoria Wu | MIT | https://github.com/victoriawu-77/blob-atelier | commit `c76954a` du 2026-10-24 | `3c41acab060d3f4e74ce740c303b6f2001745b4d1dc1b5938c7736a294026798` |
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

- Blob Atelier : la série « blobs » seulement (8 formes, 6 matières). Ses
  animaux 3D chargent three.js depuis un CDN externe ; MascotForge ne les
  propose pas, pour qu'une mascotte n'appelle aucun serveur tiers.
- Wobnimo : les 20 personnages et leurs 10 humeurs, via `<wobnimo-mascot>`.

Mettre à jour un moteur : remplacer le fichier par une version publiée, mettre
à jour ce tableau (version, empreinte) et relancer les tests.
