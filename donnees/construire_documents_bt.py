"""Construit donnees/documents_bt.json : tous les documents BT (Brevet de Technicien) recus.

  python3 donnees/construire_documents_bt.py "dossier Mr Adia" "dossier Progression_Mr Coulibaly" donnees/documents_bt.json

BT = BAC Technique (decision de Daouda, 9 oct. 2026). Le paquet garde l'origine des documents (BT_ELN :
Electronique ; BT_ELN BT_IND : industriel ; BT_TER : tertiaire) ; injecter_documents_bt.py les rattache
aux series F2, E et F, B G1 G2. Les 3 annees sont la Seconde, la Premiere et la Terminale.

Sources :
  - M. Adia (ETIC Korhogo) : « PROGRESSION BT ELN 2026-2027.pdf », 26 progressions de la 1re a la 3e annee
    (construction electronique / maintenance, electronique analogique et numerique, mesures, radio-television,
    technologie et schemas, telephonie). Theorie et TP d'une meme matiere sont reunis en une progression.
  - M. Coulibaly : progressions 2026-2027 d'Economie generale (EG) et d'Economie et organisation des
    entreprises (EOE), 1re a 3e annee BT ; programmes de Mathematiques BT industriel (toutes options) et
    BT tertiaire (METFPA, juillet 2022), decoupes en extraits.
Les fichiers ne sont pas dans le depot : seul le texte extrait l'est.
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from construire_documents_m_coulibaly import decouper, texte_docx, texte_pdf  # noqa: E402

ANNEES = {"1": "SECONDE", "2": "PREMIERE", "3": "TERMINALE"}
LIBELLES_ANNEES = {"SECONDE": "1re année", "PREMIERE": "2e année", "TERMINALE": "3e année"}
ADIA = "PROGRESSION BT ELN 2026-2027.pdf"
# Titre de la progression (sans accents, majuscules) -> (matiere, libelle)
MATIERES_ELN = [
    ("CONSTRUCTION ELECTRONIQUE", "CONSTRUCTION_ELECTRONIQUE", "Construction électronique (atelier)"),
    ("MAINTENANCE", "CONSTRUCTION_ELECTRONIQUE", "Maintenance (atelier)"),
    ("ELECTRONIQUE ANALOGIQUE", "ELECTRONIQUE_ANALOGIQUE", "Électronique analogique"),
    ("ELECTRONIQUE NUMERIQUE", "ELECTRONIQUE_NUMERIQUE", "Électronique numérique"),
    ("TP MESURES", "MESURES_ESSAIS", "Mesures et instrumentation (TP)"),
    ("TP RADIO", "RADIO_TV", "Radio-télévision (TP)"),
    ("RADIO-TELEVISION THEORIE", "RADIO_TV", "Radio-télévision (théorie)"),
    ("TECHNO", "TECHNO_SCHEMAS", "Technologie et schémas"),
    ("TP TELEPHONIE", "TELEPHONIE", "Téléphonie (TP)"),
    ("TELEPHONIE THEORIE", "TELEPHONIE", "Téléphonie (théorie)"),
]
# Lignes sans contenu pedagogique (en-tetes, legendes, signatures, cumuls d'heures isoles).
BRUIT = re.compile(
    r"^(MINISTERE|L.ENSEIGNEMENT TECHNIQUE|CABINET DU MINISTRE|-{5,}|ETABLISSEMENT|VOLUME|ANNEE SCOLAIRE|/SEMAINE|"
    r"SEMAINE \||SEMESTRE \||TE$|CD$|\(%\)$|N° \| C|MOIS \||MODELE DE PROGRESSION|D : Dur|RESPONSABLE DU CONSEIL|"
    r"NOM ET PRENOMS|OBSERVATIONS SUR|NOTA BENE|h$|\d{1,3}$|\d{1,3} \| h$|h \| \d{1,3}$|REPUBLIQUE)", re.I)


def simple(texte):
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().upper()
    return " ".join(texte.replace("’", "'").split())


def pages_pdf(chemin):
    nb = int(re.search(r"Pages:\s+(\d+)", subprocess.run(["pdfinfo", chemin], capture_output=True, text=True).stdout).group(1))
    return [subprocess.run(["pdftotext", "-layout", "-f", str(p), "-l", str(p), chemin, "-"],
                           capture_output=True, text=True).stdout for p in range(1, nb + 1)]


def nettoyer_progression(brut):
    lignes = []
    for l in brut.replace("\f", "\n").split("\n"):
        l = re.sub(r" {3,}", " | ", l.strip()).strip(" |")
        if l and not BRUIT.match(l):
            lignes.append(l)
    return "\n".join(lignes)


def progressions_eln(chemin):
    """[(matiere, niveau, libelle, texte)] : une entree par progression du PDF de M. Adia."""
    blocs = []
    for page in pages_pdf(chemin):
        titre = re.search(r"PROGRESSION D[E’']\s*(.+?)\s*$", page, flags=re.M)
        classe = re.search(r"\b([123])\s*A?\s*BT\s*ELN\b", page)
        if titre and classe:
            blocs.append({"titre": simple(titre.group(1)).rstrip("."), "annee": classe.group(1), "pages": [page]})
        elif blocs:
            blocs[-1]["pages"].append(page)
    sortie = []
    for b in blocs:
        matiere, libelle = next((m, lib) for cle, m, lib in MATIERES_ELN if cle in b["titre"])
        sortie.append((matiere, ANNEES[b["annee"]], libelle, nettoyer_progression("\n".join(b["pages"]))))
    return sortie


def source(fichier, contenu, type_doc, titre, matiere, serie, niveau, morceaux, transmis_par, institution):
    return {"fichier": fichier, "sha256": hashlib.sha256(contenu).hexdigest(), "type_doc": type_doc,
            "titre": titre, "matiere": matiere, "serie": serie, "niveau": niveau, "morceaux": morceaux,
            "transmis_par": transmis_par, "institution": institution}


def documents_adia(dossier):
    chemin = os.path.join(dossier, ADIA)
    contenu = open(chemin, "rb").read()
    regroupes = {}
    for matiere, niveau, libelle, texte in progressions_eln(chemin):
        regroupes.setdefault((matiere, niveau), []).append((libelle, texte))
    sources = []
    for (matiere, niveau), parties in regroupes.items():
        noms = " et ".join(lib for lib, _ in parties)
        corps = "\n\n".join(f"=== {lib.upper()} ===\n{texte}" for lib, texte in parties)
        entete = (f"PROGRESSION 2026-2027 - BT Électronique, {LIBELLES_ANNEES[niveau]} - {noms}\n"
                  "Établissement : ETIC Korhogo (transmise par M. Adia, professeur d'électronique).\n")
        sources.append(source(ADIA, contenu, "PROGRESSION_ANNUELLE", f"{noms}, {LIBELLES_ANNEES[niveau]} BT ELN",
                              matiere, "BT_ELN", niveau, [entete + corps],
                              "M. Adia, professeur d'électronique", "ETIC Korhogo"))
    return sources


def documents_coulibaly(dossier):
    noms = {unicodedata.normalize("NFC", n): n for n in os.listdir(dossier)}
    lire = lambda f: os.path.join(dossier, noms[unicodedata.normalize("NFC", f)])
    sources, transmis = [], "M. Coulibaly, professeur d'économie et de mathématiques"
    for sigle, matiere, libelle in (("EG", "ECO", "Économie générale"),
                                    ("EOE", "EOE", "Économie et organisation des entreprises")):
        for annee in "123":
            fichier = f"{sigle} {annee}BT.docx"
            niveau = ANNEES[annee]
            entete = (f"PROGRESSION 2026-2027 - {libelle}, {LIBELLES_ANNEES[niveau]} BT (tertiaire) "
                      "(transmise par M. Coulibaly)\n")
            sources.append(source(fichier, open(lire(fichier), "rb").read(), "PROGRESSION_ANNUELLE",
                                  f"{libelle}, {LIBELLES_ANNEES[niveau]} BT", matiere, "BT_TER", niveau,
                                  [entete + texte_docx(lire(fichier))], transmis, "METFPA"))
    for fichier, option, serie in (("BT industriel Maths revisé 2022.pdf", "BT Industriel (toutes options)", "BT_ELN BT_IND"),
                                   ("BT tertiaire  Maths Gles revisé 2022-1.pdf", "BT Tertiaire", "BT_TER")):
        texte = texte_pdf(lire(fichier))
        debut = re.search(r"^2\. ?PRESENTATION GENERALE", texte, flags=re.M)
        texte = texte[debut.start():] if debut else texte  # sans avertissement ni equipe de production
        texte = "\n".join(l for l in texte.split("\n") if not l.startswith(("METFPA –", "MEMEASFP –")))
        motif = re.compile(r"^(\d\. ?[A-Z]|[ÉE]l[ée]ment de comp[ée]tence \d+|ANNEES|\d[èe]re Ann[ée]e|\d[èe]me Ann[ée]e)", re.I)
        bruts = decouper(texte, motif)
        morceaux = [f"PROGRAMME DE MATHÉMATIQUES - {option} - extrait {k}/{len(bruts)}\n"
                    f"Source : Programme de formation BT, METFPA, juillet 2022 (transmis par M. Coulibaly).\n\n{m}"
                    for k, m in enumerate(bruts, 1)]
        sources.append(source(fichier, open(lire(fichier), "rb").read(), "PROGRAMME", f"Mathématiques, {option}",
                              "MATHS", serie, "TOUS", morceaux, transmis, "METFPA"))
    return sources


def main(dossier_adia, dossier_coulibaly, sortie):
    sources = documents_adia(dossier_adia) + documents_coulibaly(dossier_coulibaly)
    for s in sources:
        print(f"{s['serie']:14} {s['niveau']:10} {s['matiere']:26} {len(s['morceaux']):3} extraits "
              f"{sum(map(len, s['morceaux'])):7} car. | {s['titre']}")
    json.dump({"recu_le": "2026-10-09", "sources": sources}, open(sortie, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:4])
