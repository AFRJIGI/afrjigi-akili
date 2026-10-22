"""Construit donnees/cours_maths_generales_g2_g3.json : cours harmonises de mathematiques generales des
Secondes, Premieres et Terminales G2-G3 (edition de septembre 2023), transmis par M. Brou le 22 oct. 2026.

  python3 donnees/construire_cours_maths_g2_g3.py "dossier Mr Brou" donnees/cours_maths_generales_g2_g3.json

Texte extrait par pdftotext, sans en-tetes ni pieds de page, numeros de telephone et adresses e-mail retires,
puis decoupe par chapitre en extraits de 2 300 caracteres au plus (memes regles que les cours du BT de
M. Adia). Les PDF ne sont pas dans le depot : seul le texte extrait l'est.
Non retenus (22 oct.) : deux cours camerounais (series ACC, CG, FIG, SES, absentes de Cote d'Ivoire) et les
cours de BT Tertiaire du LPMMS d'Agboville, « tout droit reserve », en attente de l'accord de leur auteur.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from construire_cours_bt_adia import morceaux, nfc  # noqa: E402

COURS = {
    "COURS Mathematiques-Generales 2nde G2-G3 BY TEHUA.pdf": "SECONDE",
    "COURS Mathematiques-Generales 1ière G2-G3 2 BY TEHUA.pdf": "PREMIERE",
    "COURS Mathematiques-Generales Tle G2-G3 BY TEHUA.pdf": "TERMINALE",
}
EMAILS = re.compile(r"\S+@\S+\.\w+")
BRUIT = re.compile(r"^(MATH[ÉE]MATIQUES G[ÉE]N[ÉE]RALES(\s+(SECONDES|PREMI[ÈE]RES|TERMINALES).*)?"
                   r"|(SECONDES|PREMI[ÈE]RES|TERMINALES)\s*G2\s*[–-]\s*G3|[ÉE]DITION DE SEPTEMBRE 2023.*"
                   r"|Page(\s+\d+)?|\d{1,3}|[‐­\-–]|Observations|Remédiations\s*:?|Clôture (cognitive|sociale).*"
                   r"|Vérification de l’atteinte des objectifs|\(évaluations\))$", re.I)
CHAPITRE = re.compile(r"^CHAPITRE\s*:?\s*(\d+)\s*:?\s*(.*)$")   # « CHAPITRE 1 : », « CHAPITRE : 5 » (corps du cours)


def nettoyer(brut):
    lignes = []
    for l in brut.replace("\f", "\n").split("\n"):
        l = re.sub(r"[ \t]+", " ", l).strip()
        if l and BRUIT.match(l):
            continue
        lignes.append(l)
    texte = re.sub(r"\n{3,}", "\n\n", "\n".join(lignes))
    # Pas de suppression des suites de nombres : les series statistiques des exercices y ressembleraient a
    # des numeros de telephone (ces cours n'en contiennent aucun ; seules les adresses e-mail sont retirees).
    return EMAILS.sub("", texte).strip()


def chapitres(texte):
    """[(titre, corps)] ; ce qui precede le premier « CHAPITRE 0 : » du corps est le programme de l'annee."""
    lignes = texte.split("\n")
    blocs, titre, courant = [], "Programme de l'année", []
    i = 0
    while i < len(lignes):
        m = CHAPITRE.match(lignes[i])
        if m:
            nom = m.group(2).strip()
            j = i + 1
            while not nom and j < len(lignes):  # titre sur la ligne suivante
                nom = lignes[j].strip()
                j += 1
            # titre sur deux lignes : « RAPPELS SUR L’ETUDE DES » / « FONCTIONS NUMERIQUES »
            while j < len(lignes) and lignes[j].strip() and lignes[j].strip().upper() == lignes[j].strip() \
                    and re.search(r"[A-Z]{3}", lignes[j]) and len(nom) < 90:
                nom = f"{nom} {lignes[j].strip()}"
                j += 1
            if "\n".join(courant).strip():
                blocs.append((titre, "\n".join(courant).strip()))
            nom = re.split(r"\s*(?:OBJECTIFS P[ÉE]DAGOGIQUES|\uf0b7|PR[ÉE]-?REQUIS)", nom)[0].strip()
            titre, courant, i = f"Chapitre {m.group(1)} : {nom}"[:120], [], j
            continue
        courant.append(lignes[i])
        i += 1
    if "\n".join(courant).strip():
        blocs.append((titre, "\n".join(courant).strip()))
    return blocs


def main(dossier, sortie):
    noms = {nfc(n): n for n in os.listdir(dossier)}
    sources = []
    for fichier, classe in COURS.items():
        chemin = os.path.join(dossier, noms[nfc(fichier)])
        brut = subprocess.run(["pdftotext", chemin, "-"], capture_output=True, text=True).stdout
        # NFKC : 𝑓(𝑥) -> f(x), ℝ -> R (lettres mathematiques italiques du PDF, plus courtes a lire)
        extraits = [{"chapitre": t, "texte": m} for t, corps in chapitres(nettoyer(unicodedata.normalize("NFKC", brut)))
                    for m in morceaux(corps) if len(m) >= 120]
        sources.append({"fichier": nfc(fichier).replace(" BY TEHUA", ""), "sha256": hashlib.sha256(open(chemin, "rb").read()).hexdigest(),
                        "classe": classe, "extraits": extraits})
        print(f"{classe:10} {len(extraits):3} extraits {sum(len(e['texte']) for e in extraits):7} car. | {fichier}")
    json.dump({"recu_le": "2026-10-22", "transmis_par": "M. Brou, professeur de mathématiques",
               "edition": "Cours harmonisés, édition de septembre 2023", "sources": sources},
              open(sortie, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:3])
