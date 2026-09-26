# METFPA : prochains lots BAC technique

Inventaire preliminaire etabli depuis `bac_technique_progressions_inventory.json`.
Les nombres sont des entrees du catalogue local, pas des PDF uniques ou des documents manquants dans Akili. Le site et la base active restent a comparer avant injection.

## Categories hors Histoire-Geographie

| Categorie | Entrees brutes |
|---|---:|
| Mathematiques | 50 |
| Droit, economie, comptabilite | 15 |
| Anglais | 12 |
| Francais et expression | 7 |
| Philosophie | 5 |
| EPS | 4 |
| Physique-chimie | 3 |
| Dossiers industriels E, F1, F2, F3, F4, F7 | 218 |

## Premier lot a examiner : mathematiques

Titres explicitement rattaches au BAC, hors BT et CAP :

- Premiere : B, E, F1/F2/F3, F7, G1, G2.
- Terminale : B, E, F1/F2/F3, F7, G1, G2.
- Seconde : AB, G1, G2, T1, T2, T3 (correspondances des filieres a verifier dans les PDF).
- Mathematiques financieres : Premiere G2 et Terminale G2, titres 2025-2026.

Les titres F7 indiquent 2025 ; plusieurs autres indiquent seulement 2026. Aucun de ces titres ne suffit a certifier une version 2026-2027.
F4 n'est pas explicite dans les titres du dossier Mathematiques : verifier le dossier BAC_F4 sans lui attribuer automatiquement le programme F1/F2/F3.

## Conditions avant injection

1. Lire les PDF pour confirmer institution, annee scolaire, matiere, classe et series couvertes.
2. Comparer les identifiants et empreintes avec la base GCS active pour eviter de reinjecter les contenus existants.
3. Exclure BT, BEP, BP et CAP du lot BAC ; verifier les documents partages avant inclusion.
4. Conserver l'annee reelle et signaler toute date inconnue ; ne pas reetiqueter les documents anciens en 2026-2027.
5. Apres injection, verifier une reponse API et sa source exacte pour les series concernees.
