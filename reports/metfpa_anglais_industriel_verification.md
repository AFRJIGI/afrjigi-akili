# Anglais industriel : controle des progressions 2024-2025

Source : dossiers `BAC_E`, `BAC_F1`, `BAC_F2`, `BAC_F3`, `BAC_F4` et `BAC_F7` de l'inventaire Fomesoutra local rattache au METFPA.

Les 18 entrees du portail ont ete telechargees avec `?force_download=1`. Tous les fichiers sont des PDF de trois pages portant l'en-tete `MODELE DE PROGRESSION - IGETFPA - SEPTEMBRE 2024` et l'annee scolaire 2024-2025.

## Dedoublonnage

Les 12 entrees classees dans les dossiers E, F1, F2 et F3 sont quatre copies binaires de trois memes PDF :

| Classe indiquee dans le document | IDs portail dupliques | SHA256 |
|---|---|---|
| Seconde T1/F2 | 25511, 25550, 25600, 25627 | `43f60a6d487732de246ffe65a50b5f29ded5ee682f7b9ffcb6436cdb37c816ad` |
| Premiere E-F1-F2-F3 | 25510, 25549, 25599, 25626 | `85bebfd4feb1837a00bcb0486ba71ac67379f684c5f418d9feb973a9263d38a9` |
| Terminale E-F1-F2-F3 | 25512, 25551, 25601, 25628 | `8c509b7b6c890e418b19afed6bc12077e984109289438713da65a97b189290b0` |

Les six fichiers F4 et F7 sont uniques :

| Classe indiquee dans le document | ID portail | SHA256 |
|---|---:|---|
| Seconde T2 | 25659 | `156b95ac60760b77a78dcf4764a0df686df7d32e7333375a1d454553c6d55539` |
| Premiere F4 | 25658 | `751773240dd4bc1c3711bfed18933b115bd121586b4fa9543d23633951fc085e` |
| Terminale F4 | 25660 | `6eb438bc432b1ff65d9305bf276c994a10404a1d35b0f9a681fa63358182d0ef` |
| Seconde T3 | 25692 | `9040afd46a71022f36c668bea4bc68b18523e30d8d1f4bd11f060f6311f4f6df` |
| Premiere F7 | 25691 | `6d73813bc86ebb7359520a575867264deefc7453bff9df06820be4574e260355` |
| Terminale F7 | 25693 | `18596dfc594a01c5fde730f67c90ddd254199d5589573d87b01b6ea415c8fce7` |

Le lot industriel contient donc 9 progressions pedagogiques uniques, et non 18.

## Comparaison avec Akili

La recherche effectuee dans `jigi_global_database.json` a retourne les 7 progressions anglaises tertiaires B/G1/G2 de 2025-2026 et les 2 progressions DPFC generales de 2026-2027. Elle n'a retourne aucune progression anglaise industrielle E, F1, F2, F3, F4, F7, T1, T2 ou T3.

Les 9 progressions industrielles de ce lot sont donc absentes de la base active au moment du controle.

## Regles pour une future injection

- Conserver l'annee reelle 2024-2025 ; ne pas les etiqueter 2025-2026 ou 2026-2027.
- Identifier la source comme `METFPA_IGETFPA`, sans les confondre avec les progressions DPFC.
- N'injecter qu'une seule copie des trois documents E/F1/F2/F3 partages.
- Conserver les classes `Seconde T1/F2`, `Seconde T2` et `Seconde T3` telles qu'elles figurent dans les documents ; ne pas inventer une equivalence de serie non ecrite.
- Utiliser `BAC_TECHNIQUE`, `ANGLAIS` et `PROGRESSION_ANNUELLE` dans les metadonnees de recherche.
- Creer une sauvegarde de la base, executer d'abord un audit sans ecriture, puis tester la selection de source sur l'API reelle apres un eventuel deploiement.

Aucun document n'a ete injecte et aucun service n'a ete redeploye pendant ce controle.

Les fichiers originaux sont conserves localement dans `tmp/pdfs/metfpa-anglais-industriel/` et restent hors Git.
