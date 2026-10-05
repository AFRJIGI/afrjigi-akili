"""Construit donnees/documents_m_coulibaly.json depuis les fichiers transmis par M. Coulibaly
(professeur d'economie et de mathematiques).

  python3 donnees/construire_documents_m_coulibaly.py "dossier/des/fichiers" donnees/documents_m_coulibaly.json

Programmes educatifs et formats d'epreuves : texte de pdftotext -layout, decoupe en extraits
de 2 600 caracteres au plus (l'API ne lit que 2 800 caracteres par document hors progression).
Progressions : texte complet (l'API centre la progression sur le mois en cours).
Les fichiers ne sont pas dans le depot : seul le texte extrait l'est.
"""
import hashlib, json, os, re, subprocess, sys
import docx

TAILLE = 2450
CI, BG, BT = "CLASSE_INTERMEDIAIRE", "BAC_GENERAL", "BAC_TECHNIQUE"
SOURCE_PE = "Programme éducatif et guide d'exécution de Mathématiques (DPFC, version septembre 2023)"
SOURCE_FMT = "Formats des évaluations de Mathématiques (DPFC, CPN du 27 novembre 2019, document 2021-2022)"

# fichier, type, titre, niveau, cibles [(examen, serie)], libelle de classe
FICHIERS = [
    ("01. Prog Éduct MATHS 6e CND 0923.pdf", "PROGRAMME", "6e", "6E", [(CI, "6E")]),
    ("02. Prog Éduct MATHS 5e CND 0923.pdf", "PROGRAMME", "5e", "5E", [(CI, "5E")]),
    ("03. Prog Éduct MATHS 4e CND 0923 (1).pdf", "PROGRAMME", "4e", "4E", [(CI, "4E")]),
    ("05. Prog Éduct MATHS 2A CND 0923 (1).pdf", "PROGRAMME", "Seconde A", "SECONDE", [(CI, "SECONDE_A")]),
    ("06.Prog Educt maths 2C CND 0923.pdf", "PROGRAMME", "Seconde C", "SECONDE", [(CI, "SECONDE_C")]),
    ("07. Prog Éduct MATHS 1A1 CND 0923.pdf", "PROGRAMME", "Première A1", "PREMIERE", [(CI, "PREMIERE_A")]),
    ("08. Prog Éduct MATHS 1A2 CND 0923.pdf", "PROGRAMME", "Première A2", "PREMIERE", [(CI, "PREMIERE_A")]),
    ("09.Prog Educt maths 1C CND 0923.pdf", "PROGRAMME", "Première C", "PREMIERE", [(CI, "PREMIERE_C")]),
    ("10.Prog Educt maths 1D CND 0923.pdf", "PROGRAMME", "Première D", "PREMIERE", [(CI, "PREMIERE_D")]),
    ("11. Prog Éduct MATHS TA1 CND 0923.pdf", "PROGRAMME", "Terminale A1", "TERMINALE", [(BG, "A1")]),
    ("12. Prog Éduct MATHS TA2 CND 0923.pdf", "PROGRAMME", "Terminale A2", "TERMINALE", [(BG, "A2")]),
    ("14. Prog Educt maths TD CND 0923.pdf", "PROGRAMME", "Terminale D", "TERMINALE", [(BG, "D")]),
    ("1.Formats des évaluations en maths au Collège D2021-2.pdf", "FORMAT_EPREUVE", "Collège (6e à 3e) : interrogations et devoirs", "1ER_CYCLE",
     [(CI, "6E"), (CI, "5E"), (CI, "4E"), ("BEPC", "BEPC")]),
    ("2.Format de l'épreuve du BEPC en maths D2021-2.pdf", "FORMAT_EPREUVE", "Épreuve de Mathématiques du BEPC", "3E", [("BEPC", "BEPC")]),
    ("3.Formats des évaluations 2nd cycle littéraire D2021-2.pdf", "FORMAT_EPREUVE", "Second cycle littéraire (2de A, 1re A, Tle A) : interrogations et devoirs", "2ND_CYCLE",
     [(CI, "SECONDE_A"), (CI, "PREMIERE_A"), (BG, "A1A2")]),
    ("5.Format du Bac série A1 D2021-2.pdf", "FORMAT_EPREUVE", "Épreuve de Mathématiques du BAC série A1", "TERMINALE", [(BG, "A1")]),
    ("6.Format du Bac série A2 D2021-2.pdf", "FORMAT_EPREUVE", "Épreuve de Mathématiques du BAC série A2", "TERMINALE", [(BG, "A2")]),
    ("7.Format du Bac série C D2021-2.pdf", "FORMAT_EPREUVE", "Épreuve de Mathématiques du BAC série C", "TERMINALE", [(BG, "C")]),
    ("8.Format du Bac série D D2021-2.pdf", "FORMAT_EPREUVE", "Épreuve de Mathématiques du BAC série D", "TERMINALE", [(BG, "D")]),
    ("MATHEMATIQUES - Progressions annuelles_DPFC_2026_2027.pdf", "PROGRESSION_ANNUELLE", "Progressions annuelles de Mathématiques 2026-2027 (6e à Terminale)", "TOUS_CYCLES", [("TOUS", "TOUTES")]),
    ("PROGRESSION DE SCIENCES ECONOMIQUES ET SOCIALES Tle B.docx", "PROGRESSION_ANNUELLE", "Sciences économiques et sociales, Terminale B", "TERMINALE", [(BT, "B")]),
    ("PROGRESSION DE SCIENCES ECONOMIQUES ET SOCIALES 1ière B.docx", "PROGRESSION_ANNUELLE", "Sciences économiques et sociales, Première B", "PREMIERE", [(BT, "B")]),
    ("PROGRESSION DE SCIENCES ECONOMIQUES ET SOCIALES 2nde AB.docx", "PROGRESSION_ANNUELLE", "Sciences économiques et sociales, Seconde AB", "SECONDE", [(BT, "B")]),
    ("PROGRESSION DE INITIATION ECONOMIQUE 2nde G1&G2.docx", "PROGRESSION_ANNUELLE", "Initiation économique, Seconde G1 et G2", "SECONDE", [(BT, "G1G2")]),
    ("PROGRESSION DE ECONOMIE D’ENTREPRISE Tle G1&G2.docx", "PROGRESSION_ANNUELLE", "Économie d'entreprise, Terminale G1 et G2", "TERMINALE", [(BT, "G1G2")]),
    ("PROGRESSION DE ECONOMIE GENERALE Tle G.docx", "PROGRESSION_ANNUELLE", "Économie générale, Terminale G", "TERMINALE", [(BT, "G1G2")]),
]
# Hors perimetre d'Akili (Brevet de Technicien, apres le BEPC) : "BT industriel Maths revisé 2022.pdf",
# "BT tertiaire  Maths Gles revisé 2022-1.pdf". Doublons "(1)" et captures d'ecran ignores.

PIED = re.compile(r"^(page \d+ sur \d+|\d+/\d+|math[ée]matiques? \S+$|.*page \d+ sur \d+$|commission p[ée]dagogique nationale.*$|coordination nationale disciplinaire.*\d+/\d+$)", re.I)


def texte_pdf(chemin):
    brut = subprocess.run(["pdftotext", "-layout", chemin, "-"], capture_output=True, text=True).stdout
    lignes = []
    for l in brut.replace("\f", "\n").split("\n"):
        l = re.sub(r" {3,}", " | ", l.strip()).strip(" |")
        if not l:
            if lignes and lignes[-1]:
                lignes.append("")
            continue
        if PIED.match(l) or re.fullmatch(r"\d{1,3}", l):
            continue
        lignes.append(l)
    return "\n".join(lignes).strip()


def texte_docx(chemin):
    d = docx.Document(chemin)
    lignes, prec = [], None
    for t in d.tables:
        for r in t.rows:
            cells, last = [], None
            for c in r.cells:
                if c._tc is last:
                    continue
                last = c._tc
                v = " ".join(c.text.split())
                if not v or v in cells or re.fullmatch(r"\d{1,3}", v) or re.match(r"^(PREMIER|DEUXIEME) SEMESTRE", v):
                    continue
                cells.append(v)
            ligne = " | ".join(cells)
            if ligne and ligne != prec and not ligne.startswith(("MOIS |", "N° |", "SEMESTRE |", "MINISTERE", "ANNEE SCOLAIRE |")):
                lignes.append(ligne)
            prec = ligne
    return "\n".join(lignes)


def decouper(texte, motif_section):
    """Extraits coupes aux sections (lecons, exercices...), puis aux paragraphes."""
    blocs, courant = [], []
    for l in texte.split("\n"):
        if motif_section.match(l) and courant:
            blocs.append("\n".join(courant).strip())
            courant = []
        courant.append(l)
    blocs.append("\n".join(courant).strip())
    morceaux, actuel = [], ""
    for bloc in blocs:
        paras = bloc.split("\n\n") if len(bloc) > TAILLE else [bloc]
        for p in paras:
            while len(p) > TAILLE:  # tableau sans ligne vide : coupe aux lignes
                coupe = p.rfind("\n", 0, TAILLE)
                coupe = coupe if coupe > 500 else TAILLE
                if actuel:
                    morceaux.append(actuel); actuel = ""
                morceaux.append(p[:coupe].strip()); p = p[coupe:].strip()
            if actuel and len(actuel) + len(p) + 2 > TAILLE:
                morceaux.append(actuel); actuel = ""
            actuel += ("\n\n" if actuel else "") + p
    if actuel.strip():
        morceaux.append(actuel)
    return [m.strip() for m in morceaux if len(m.strip()) > 80]


def contexte(texte):
    """Dernier theme / lecon vu avant l'extrait, pour l'en-tete."""
    themes = re.findall(r"(TH[ÈE]ME \d+ ?: ?[^\n|]+)", texte, flags=re.I)
    lecons = re.findall(r"(Le[çc]on \d+ ?: ?[^\n|]+)", texte)
    return themes, lecons


def main(dossier, sortie):
    import unicodedata
    noms = {unicodedata.normalize("NFC", n): n for n in os.listdir(dossier)}  # accents decomposes (Windows)
    sources = []
    for fichier, type_doc, titre, niveau, cibles in FICHIERS:
        chemin = os.path.join(dossier, noms[unicodedata.normalize("NFC", fichier)])
        contenu = open(chemin, "rb").read()
        if type_doc == "PROGRESSION_ANNUELLE" and fichier.endswith(".docx"):
            texte = texte_docx(chemin)
            entete = (f"PROGRESSION 2025-2026 - {titre} - Lycée technique d'Abidjan "
                      f"(transmise par M. Coulibaly)\n")
            morceaux = [entete + texte]
        elif type_doc == "PROGRESSION_ANNUELLE":
            morceaux = [texte_pdf(chemin)]
        else:
            texte = texte_pdf(chemin)
            if type_doc == "PROGRAMME":
                debut = re.search(r"I\. ?PROFIL DE SORTIE", texte)
                texte = texte[debut.start():] if debut else texte  # sans le mot de la ministre
                motif = re.compile(r"^(Le[çc]on \d+|TH[ÈE]ME \d+|COMP[ÉE]TENCE \d+$|CORPS DU PROGRAMME|II\. PROPOSITION|I\. PROGRESSION)", re.I)
                source = SOURCE_PE
            else:
                motif = re.compile(r"^(I+V?\.|V\.|EXERCICE \d|Exemple d.épreuve|\d\. DEVOIR|\d\.\d\. Devoir)", re.I)
                source = SOURCE_FMT
            bruts = decouper(texte, motif)
            morceaux, theme, lecon, corps = [], "", "", False
            for k, m in enumerate(bruts, 1):
                en = f"{'PROGRAMME ÉDUCATIF DE MATHÉMATIQUES' if type_doc == 'PROGRAMME' else 'FORMAT DES ÉVALUATIONS DE MATHÉMATIQUES'} - {titre}"
                if type_doc == "PROGRAMME":
                    if lecon and not re.match(r"^(Le[çc]on|TH[ÈE]ME)", m, re.I):
                        en += f" - {theme + ' - ' if theme else ''}{lecon} (suite)"
                    # Le contexte ne vient que des titres en debut de ligne du corps du programme
                    # et du guide (le tableau synoptique du debut cite toutes les lecons).
                    for ligne in m.split("\n"):
                        if re.match(r"^(CORPS DU PROGRAMME|II\. PROPOSITION)", ligne, re.I):
                            corps, theme, lecon = True, "", ""
                        elif corps and re.match(r"^TH[ÈE]ME \d+ ?:", ligne, re.I):
                            theme, lecon = ligne.split(" | ")[0].strip(), ""
                        elif corps and re.match(r"^Le[çc]on \d+ ?:", ligne):
                            lecon = ligne.split(" | ")[0].strip()
                morceaux.append(f"{en} - extrait {k}/{len(bruts)}\nSource : {source}.\n\n{m}")
        sources.append({"fichier": fichier, "sha256": hashlib.sha256(contenu).hexdigest(), "type_doc": type_doc,
                        "titre": titre, "niveau": niveau, "cibles": cibles,
                        "matiere": "ECO" if fichier.endswith(".docx") else "MATHS", "morceaux": morceaux})
        print(f"{type_doc:21} {len(morceaux):3} extraits {sum(map(len, morceaux)):7} car. | {fichier}")
    json.dump({"transmis_par": "M. Coulibaly, professeur d'économie et de mathématiques", "recu_le": "2026-10-05",
               "sources": sources}, open(sortie, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
