"""Decoupe la fiche de lecon « Limites et continuite » (Terminale D) de M. Sidibe Zoumana en extraits pour la base.

Source : "Fiche lecon 1 - Limites et continuite - Tle D_4.pdf" (50 pages, 15 seances de 55 min, programme DPFC).
Les formules du PDF (editeur d'equations Word) sont cassees par l'extraction automatique : le cours a ete
transcrit page par page dans cours_limites_continuite_m_sidibe_zoumana_transcription.txt (trace ecrite,
activites et exercices avec leurs corriges, formules en notation simple ; erreurs du document signalees
par "[Verification : ...]").

  python3 donnees/construire_cours_limites_m_sidibe_zoumana.py   # ecrit cours_limites_m_sidibe_zoumana.json
"""
import json
import re
from pathlib import Path

ICI = Path(__file__).parent
TRANSCRIPTION = ICI / "cours_limites_continuite_m_sidibe_zoumana_transcription.txt"
SORTIE = ICI / "cours_limites_m_sidibe_zoumana.json"
SHA256_PDF = "1368b6f7950c5466567a57c11a2c8aa3f7cebbadff3e9ea3d35c98f1306cbefd"
MAX_CORPS = 2250  # l'API garde 2800 caracteres par document, l'en-tete prend le reste
LECON = "Leçon 1 : Limites et continuité"


def blocs(texte):
    """Liste ordonnee de (numero, titre, corps) : presentation (0), seances 1 a 15, exercices de fin (16)."""
    resultat = []
    morceaux = re.split(r"(?m)^=== (.+?) ===\s*$", texte)[1:]
    for entete, corps in zip(morceaux[::2], morceaux[1::2]):
        seance = re.match(r"SEANCE (\d+)/15\s*:\s*(.+)", entete)
        if seance:
            resultat.append((int(seance.group(1)), f"Séance {seance.group(1)}/15 : {seance.group(2).strip()}", corps.strip()))
        elif entete.startswith("PRESENTATION"):
            resultat.append((0, "Présentation de la leçon (situation, habiletés, plan, séances)", corps.strip()))
        else:
            resultat.append((16, "Exercices de fin de leçon et situation d'évaluation corrigée", corps.strip()))
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
    """Regroupe les paragraphes en extraits d'au plus MAX_CORPS caracteres, sans couper un paragraphe."""
    extraits, courant = [], []
    for para in paragraphes(corps):
        if courant and sum(len(p) + 2 for p in courant) + len(para) > MAX_CORPS:
            extraits.append("\n\n".join(courant))
            courant = []
        courant.append(para)
    if courant:
        extraits.append("\n\n".join(courant))
    return extraits


def construire():
    texte = TRANSCRIPTION.read_text(encoding="utf-8")
    documents = []
    for numero, titre, corps in blocs(texte):
        extraits = decouper(corps)
        for k, contenu in enumerate(extraits, start=1):
            entete = (f"COURS DE MATHÉMATIQUES — Terminale D — {LECON} — {titre} (partie {k}/{len(extraits)})\n"
                      "Fiche de leçon de M. Sidibé Zoumana, enseignant de mathématiques (programme DPFC, "
                      "15 séances de 55 min) : trace écrite, activités et exercices avec leurs corrigés.\n")
            documents.append(dict(seance=numero, titre=titre, morceau=k, nb_morceaux=len(extraits),
                                  texte=entete + "\n" + contenu))
    return dict(source="Fiche lecon 1 - Limites et continuite - Tle D_4.pdf",
                transmis_par="M. Sidibé Zoumana, enseignant", recu_le="2026-10-09",
                classe_source="Terminale D", sha256_pdf=SHA256_PDF, documents=documents)


if __name__ == "__main__":
    paquet = construire()
    SORTIE.write_text(json.dumps(paquet, ensure_ascii=False, indent=1), encoding="utf-8")
    tailles = [len(d["texte"]) for d in paquet["documents"]]
    print(f"{len(tailles)} extraits, de {min(tailles)} à {max(tailles)} caractères -> {SORTIE.name}")
