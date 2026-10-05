"""Decoupe le cours de mecanique / RDM de M. Sidibe en extraits pour la base d'Akili.

Source : "MECA-RDM-BT1-BT2 Doc Prof.pdf" (58 fiches professeur, classes 2nde F2 / 1ere F2).
Les formules du PDF sont des images : le texte a ete transcrit page par page dans
cours_mecanique_m_sidibe_transcription.txt (formules en notation simple, figures decrites
entre crochets, erreurs de calcul de la fiche signalees par "[Verification : ...]").

  python3 donnees/construire_cours_mecanique_m_sidibe.py   # ecrit cours_mecanique_m_sidibe.json
"""
import json
import re
from pathlib import Path

ICI = Path(__file__).parent
TRANSCRIPTION = ICI / "cours_mecanique_m_sidibe_transcription.txt"
SORTIE = ICI / "cours_mecanique_m_sidibe.json"
SHA256_PDF = "3bd4bfbb7fda30ec60333d947e9200c813bfc312852780bbcd51bf13d68d673e"
MAX_CORPS = 2250  # l'API garde 2800 caracteres par document, l'en-tete prend le reste

TITRES = {
    "VECTEURS": ("vecteurs", "Vecteurs"),
    "FORCES ET VECTEURS-FORCES": ("forces", "Forces et vecteurs-forces"),
    "MODELISATION DES ACTIONS MECANIQUES": ("modelisation", "Modélisation des actions mécaniques"),
    "MOMENTS ET COUPLES": ("moments", "Moments et couples"),
    "RESULTANTES": ("resultantes", "Résultantes"),
    "PRINCIPE FONDAMENTAL DE LA STATIQUE": ("pfs", "Principe fondamental de la statique (PFS)"),
    "SOLIDE SOUMIS A L'ACTION DE TROIS FORCES CONCOURANTES": (
        "trois_forces", "Solide soumis à l'action de trois forces concourantes"),
    "SOLIDE SOUMIS A QUATRE FORCES": ("quatre_forces", "Solide soumis à quatre forces"),
    "SOLIDE SOUMIS A QUATRE FORCES (METHODE DE CULMAN)": (
        "culman", "Solide soumis à quatre forces (méthode de Culman)"),
    "MOUVEMENTS DE SOLIDE": ("mouvements", "Mouvements de solide (translation, rotation)"),
    "GENERALITES SUR LA RESISTANCE DES MATERIAUX": ("rdm", "Généralités sur la résistance des matériaux (RDM)"),
    "TRACTION": ("traction", "Traction"),
    "CISAILLEMENT": ("cisaillement", "Cisaillement"),
}
# Ordre des fiches dans le PDF : statique, cinematique, puis RDM.
PARTIES = {
    "vecteurs": "Statique", "forces": "Statique", "modelisation": "Statique", "moments": "Statique",
    "resultantes": "Statique", "pfs": "Statique", "trois_forces": "Statique", "quatre_forces": "Statique",
    "culman": "Statique", "mouvements": "Cinématique", "rdm": "Résistance des matériaux",
    "traction": "Résistance des matériaux", "cisaillement": "Résistance des matériaux",
}
TITRE_SECTION = re.compile(r"^(\d+(\.\d+)*\.?\s+\S|Exercices?\b|EXERCICES?\b|EVALUATION|ÉVALUATION|Application\b)")


def sans_accents(texte):
    import unicodedata
    texte = unicodedata.normalize("NFKD", texte)
    return "".join(c for c in texte if not unicodedata.combining(c)).upper().strip()


def chapitres(texte):
    """Liste ordonnee de (code, titre, corps) ; deux fiches de suite du meme chapitre sont fusionnees."""
    resultat = []
    blocs = re.split(r"(?m)^=== CHAPITRE : (.+?) ===\s*$", texte)[1:]
    for titre, corps in zip(blocs[::2], blocs[1::2]):
        code, libelle = TITRES[sans_accents(titre)]
        if resultat and resultat[-1][0] == code:
            resultat[-1] = (code, libelle, resultat[-1][2] + "\n\n" + corps.strip())
        else:
            resultat.append((code, libelle, corps.strip()))
    return resultat


def paragraphes(corps):
    morceaux = []
    for para in re.split(r"\n\s*\n", corps):
        para = para.strip()
        if not para:
            continue
        if len(para) <= MAX_CORPS:
            morceaux.append(para)
            continue
        courant = ""
        for ligne in para.splitlines():
            if courant and len(courant) + len(ligne) + 1 > MAX_CORPS:
                morceaux.append(courant)
                courant = ""
            courant = f"{courant}\n{ligne}" if courant else ligne
        if courant:
            morceaux.append(courant)
    return morceaux


def decouper(corps):
    """Regroupe les paragraphes en extraits ; chaque extrait rappelle la section en cours."""
    extraits, courant, section, section_debut = [], [], "", ""
    for para in paragraphes(corps):
        premiere = para.splitlines()[0].strip()
        est_titre = bool(TITRE_SECTION.match(premiere)) and len(premiere) < 120
        taille = sum(len(p) + 2 for p in courant) + len(para)
        if courant and (taille > MAX_CORPS - 80 or (est_titre and taille > MAX_CORPS * 0.75)):
            extraits.append((section_debut, "\n\n".join(courant)))
            courant, section_debut = [], section
        if est_titre:
            section = premiere
            if not courant:
                section_debut = ""
        courant.append(para)
    if courant:
        extraits.append((section_debut, "\n\n".join(courant)))
    return extraits


def construire():
    texte = TRANSCRIPTION.read_text(encoding="utf-8")
    documents = []
    liste = chapitres(texte)
    for numero, (code, libelle, corps) in enumerate(liste, start=1):
        extraits = decouper(corps)
        for k, (suite, contenu) in enumerate(extraits, start=1):
            entete = (f"COURS DE MÉCANIQUE APPLIQUÉE / RDM — {libelle} (partie {k}/{len(extraits)})\n"
                      f"Fiches de cours de 2nde F2 / 1ère F2 transmises par M. Sidibé, enseignant "
                      f"(aussi utiles en Terminale F2 pour les révisions). Partie : {PARTIES[code]}.\n")
            if suite:
                entete += f"(Suite de : {suite})\n"
            documents.append(dict(chapitre=numero, code=code, titre=libelle, partie=PARTIES[code],
                                  morceau=k, nb_morceaux=len(extraits), texte=entete + "\n" + contenu))
    sommaire = ["COURS DE MÉCANIQUE APPLIQUÉE / RDM — Sommaire du cours de M. Sidibé (liste des chapitres, programme couvert)",
                "Fiches de cours de 2nde F2 / 1ère F2 (document « MECA-RDM-BT1-BT2 Doc Prof », 58 fiches), "
                "transmises par M. Sidibé, enseignant. Chaque chapitre contient le cours, des applications "
                "corrigées et des évaluations ou exercices.", ""]
    partie = None
    for numero, (code, libelle, _) in enumerate(liste, start=1):
        if PARTIES[code] != partie:
            partie = PARTIES[code]
            sommaire.append(f"{partie} :")
        sommaire.append(f"  Chapitre {numero} : {libelle}")
    documents.insert(0, dict(chapitre=0, code="sommaire", titre="Sommaire", partie="Sommaire",
                             morceau=1, nb_morceaux=1, texte="\n".join(sommaire)))
    return dict(source="MECA-RDM-BT1-BT2 Doc Prof.pdf", transmis_par="M. Sidibé, enseignant",
                recu_le="2026-10-04", classes_source="2nde F2 / 1ère F2", sha256_pdf=SHA256_PDF,
                documents=documents)


if __name__ == "__main__":
    paquet = construire()
    SORTIE.write_text(json.dumps(paquet, ensure_ascii=False, indent=1), encoding="utf-8")
    tailles = [len(d["texte"]) for d in paquet["documents"]]
    print(f"{len(tailles)} extraits, de {min(tailles)} à {max(tailles)} caractères -> {SORTIE.name}")
