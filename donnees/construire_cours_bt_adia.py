"""Construit donnees/cours_bt_adia.json : cours du BT Electronique transmis par M. Adia (ETIC Korhogo, 14 oct. 2026).

  python3 donnees/construire_cours_bt_adia.py "dossier Mr Adia" donnees/cours_bt_adia.json

Dix supports de cours (fascicules) de la 1re a la 3e annee du BT Electronique : telephonie (1BT, 2BT, 3BT),
radio-television (1BT, 2BT, 3e annee), architecture des systemes informatiques (ASI 2, ASI 3) et
teleinformatique et reseaux (TIR 2, TIR 3). Texte extrait (pdftotext, pandoc), sans en-tetes de page ni
sommaire, numeros de telephone retires, puis decoupe par chapitre en extraits de 2 300 caracteres au plus.
Les fichiers ne sont pas dans le depot : seul le texte extrait l'est.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata

# fichier -> (discipline, classe, libelle)
COURS = {
    "FASCICULE_TELEPHONIE__1BT_CMA[1].pdf": ("TELEPHONIE", "SECONDE", "Téléphonie"),
    "FASCICULE_TELEPHONIE_2BT_CMA[1].pdf": ("TELEPHONIE", "PREMIERE", "Téléphonie"),
    "FASCICULE TELEPHONIE 3BT CMA[2].pdf": ("TELEPHONIE", "TERMINALE", "Téléphonie"),
    "RTV_1BT_VRAI[1].pdf": ("RADIO_TV", "SECONDE", "Radio-télévision"),
    "FASCICULE TV 2BT[1].pdf": ("RADIO_TV", "PREMIERE", "Radio-télévision"),
    "RTV 3ième annee[1].pdf": ("RADIO_TV", "TERMINALE", "Radio-télévision"),
    "support de cours ASI 2.docx": ("ASI", "PREMIERE", "Architecture des systèmes informatiques"),
    "support de cours ASI 3.docx": ("ASI", "TERMINALE", "Architecture des systèmes informatiques"),
    "TIR 2.docx": ("TIR", "PREMIERE", "Téléinformatique et réseaux"),
    "TIR 3.docx": ("TIR", "TERMINALE", "Téléinformatique et réseaux"),
}
ANNEES = {"SECONDE": "1re année", "PREMIERE": "2e année", "TERMINALE": "3e année"}
TAILLE = 2300
TELEPHONES = re.compile(r"(?<!\d)(?:\+?225[ .]?)?(?:\d{2}[ .]?){4}\d{2}(?!\d)")
BRUIT = re.compile(r"^(PROFESSEUR\s*:.*|NOM\s*:?|Page \d+ sur \d+|\[\]|\d{1,3})$", re.I)
SOMMAIRE = re.compile(r"^.{3,100}?\s\d{1,3}$")          # « II. LES DIFFERENTS TYPES DE RESEAUX 25 »
CHAPITRE = re.compile(r"^\s*CHAPITRE\s*([0-9IVX]+)\b\s*:?\s*(.*)$", re.I)


def nfc(texte):
    return unicodedata.normalize("NFC", texte)


def texte_brut(chemin):
    if chemin.endswith(".pdf"):
        return subprocess.run(["pdftotext", chemin, "-"], capture_output=True, text=True).stdout
    return subprocess.run(["pandoc", "-t", "plain", "--wrap=none", chemin], capture_output=True, text=True).stdout


def nettoyer(brut):
    lignes = []
    for l in brut.replace("\f", "\n").split("\n"):
        l = re.sub(r"[ \t]+", " ", l).strip()
        if l and BRUIT.match(l):
            continue
        lignes.append(l)
    # Sommaire d'un document Word : tout ce qui precede la deuxieme ligne « CHAPITRE 1 ».
    premiers = [i for i, l in enumerate(lignes) if CHAPITRE.match(l) and CHAPITRE.match(l).group(1) in ("1", "I")]
    if len(premiers) > 1 and sum(1 for l in lignes[:premiers[1]] if SOMMAIRE.match(l)) >= 3:
        lignes = lignes[premiers[1]:]
    texte = "\n".join(lignes)
    texte = re.sub(r"\n{3,}", "\n\n", texte)
    return TELEPHONES.sub("", texte).strip()


def chapitres(texte):
    """[(titre, corps)] ; le texte avant le premier chapitre (programme de l'annee) est « Programme »."""
    blocs, titre, courant = [], "Programme de l'année", []
    for l in texte.split("\n"):
        m = CHAPITRE.match(l)
        if m:
            if "\n".join(courant).strip():
                blocs.append((titre, "\n".join(courant).strip()))
            titre, courant = f"Chapitre {m.group(1)}" + (f" : {m.group(2).strip()}" if m.group(2).strip() else ""), []
        else:
            courant.append(l)
    if "\n".join(courant).strip():
        blocs.append((titre, "\n".join(courant).strip()))
    return blocs


def morceaux(corps, taille=TAILLE):
    parties, actuel = [], ""
    for para in re.split(r"\n\s*\n|\n(?=\d[.\-‐]|\d\.\d|[A-Z]\.\s)", corps):
        para = para.strip()
        if not para:
            continue
        while len(para) > taille:  # paragraphe trop long : coupe a la phrase
            coupe = para.rfind(". ", 0, taille)
            coupe = coupe + 1 if coupe > taille // 2 else taille
            if actuel:
                parties.append(actuel)
                actuel = ""
            parties.append(para[:coupe].strip())
            para = para[coupe:].strip()
        if actuel and len(actuel) + len(para) + 2 > taille:
            parties.append(actuel)
            actuel = para
        else:
            actuel = f"{actuel}\n\n{para}" if actuel else para
    if actuel:
        parties.append(actuel)
    return parties


def main(dossier, sortie):
    noms = {nfc(n): n for n in os.listdir(dossier)}
    sources = []
    for fichier, (discipline, classe, libelle) in COURS.items():
        chemin = os.path.join(dossier, noms[nfc(fichier)])
        contenu = open(chemin, "rb").read()
        extraits = []
        for titre, corps in chapitres(nettoyer(texte_brut(chemin))):
            for m in morceaux(corps):
                if len(m) >= 120:  # pas d'extrait sans contenu (titre seul, legende)
                    extraits.append({"chapitre": titre[:120], "texte": m})
        sources.append({"fichier": nfc(fichier), "sha256": hashlib.sha256(contenu).hexdigest(),
                        "discipline": discipline, "classe": classe, "libelle": libelle, "extraits": extraits})
        print(f"{discipline:11} {classe:10} {len(extraits):3} extraits {sum(len(e['texte']) for e in extraits):7} car. | {fichier}")
    json.dump({"recu_le": "2026-10-14", "transmis_par": "M. Adia, professeur d'électronique",
               "institution": "ETIC Korhogo", "sources": sources},
              open(sortie, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:3])
