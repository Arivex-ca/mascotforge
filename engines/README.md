# Moteurs de mascottes en code (tiers, licence MIT)

MascotForge reprend tels quels deux projets open source pour les mascottes
dessinées et animées en code. Les fichiers ne sont pas modifiés ; chaque
dossier garde la licence de son auteur, copiée aussi dans chaque export.

| Moteur | Auteur | Licence | Source | Version embarquée | SHA-256 |
|---|---|---|---|---|---|
| Blob Atelier (`blob-atelier/agent-mascot.js`) | Victoria Wu | MIT | https://github.com/victoriawu-77/blob-atelier | commit `c76954a` du 2026-10-24 | `3c41acab060d3f4e74ce740c303b6f2001745b4d1dc1b5938c7736a294026798` |
| Wobnimo (`wobnimo/wobnimo.js`) | Pourya Akhbari | MIT | https://github.com/Pouryaak/wobnimo | paquet npm `wobnimo@0.2.0`, `dist/wobnimo.js` | `85443e0bd564e9e8428aced315346d80c304d647b8859bdb95b5203a2b5752ef` |

Ce que MascotForge en utilise :

- Blob Atelier : la série « blobs » seulement (8 formes, 6 matières). Ses
  animaux 3D chargent three.js depuis un CDN externe ; MascotForge ne les
  propose pas, pour qu'une mascotte n'appelle aucun serveur tiers.
- Wobnimo : les 20 personnages et leurs 10 humeurs, via `<wobnimo-mascot>`.

Mettre à jour un moteur : remplacer le fichier par une version publiée, mettre
à jour ce tableau (version, empreinte) et relancer les tests.
