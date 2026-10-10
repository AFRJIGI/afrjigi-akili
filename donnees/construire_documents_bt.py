"""Construit donnees/documents_bt.json : tous les documents BT (Brevet de Technicien) recus.

  python3 donnees/construire_documents_bt.py "dossier Mr Adia" "dossier Progression_Mr Coulibaly" donnees/documents_bt.json \
      "dossier Progressions_Electroniques" "dossier CMC_Tertiare"

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
  - Dossier « Progressions_Electroniques » (10 oct.) : 29 progressions Word du BT Electronique. On ne garde que
    les matieres absentes du PDF 2026-2027 de M. Adia : dessin industriel (1re a 3e annee), informatique,
    architecture des systemes informatiques, teleinformatique et reseaux, francais / techniques d'expression
    (1re a 3e annee, 2024-2025) et CMC (2e annee BT industriel, 2023-2024). Les autres sont des versions plus
    anciennes (2021-2023) de progressions deja recues. Les numeros de telephone sont retires.
  - Dossier « CMC_Tertiare » (10 oct.) : CMC (Connaissance du monde contemporain) du BT tertiaire, 1re a 3e
    annee (2023-2024).
Les fichiers ne sont pas dans le depot : seul le texte extrait l'est.
"""
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import unicodedata
import zipfile

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


# fichier -> (matiere, serie d'origine, annee, libelle). « BT_TOUS » : toutes les options du BT.
ELN_WORD = {
    "file (6).docx": ("DESSIN_INDUSTRIEL", "BT_ELN", "1", "Dessin industriel"),
    "file (1).docx": ("DESSIN_INDUSTRIEL", "BT_ELN", "2", "Dessin industriel"),
    "file (2).docx": ("DESSIN_INDUSTRIEL", "BT_ELN", "3", "Dessin industriel"),
    "file (24).docx": ("INFORMATIQUE_INDUSTRIELLE", "BT_ELN", "1", "Informatique"),
    "file (9).docx": ("INFORMATIQUE_INDUSTRIELLE", "BT_ELN", "2", "Architecture des systèmes informatiques"),
    "file (8).docx": ("INFORMATIQUE_INDUSTRIELLE", "BT_ELN", "2", "Téléinformatique et réseaux"),
    "file (11).docx": ("FRANCAIS", "BT_TOUS", "1", "Français / techniques d'expression"),
    "file (3).docx": ("FRANCAIS", "BT_TOUS", "2", "Français / techniques d'expression"),
    "file (7).docx": ("FRANCAIS", "BT_TOUS", "3", "Français / techniques d'expression"),
    "file (16).docx": ("HG", "BT_IND", "2", "Connaissance du monde contemporain (CMC)"),
}
CMC_TERTIAIRE = {
    "file.docx": ("HG", "BT_TER", "1", "Connaissance du monde contemporain (CMC)"),
    "file (1).docx": ("HG", "BT_TER", "2", "Connaissance du monde contemporain (CMC)"),
    "file (2).docx": ("HG", "BT_TER", "3", "Connaissance du monde contemporain (CMC)"),
}
# file (17).docx = file (16).docx ; les autres fichiers : versions 2021-2023 de progressions deja dans le PDF.
TELEPHONES = re.compile(r"\d{9,}|(?<!\d)\d{6}-\d{4}(?!\d)")


def ouvrir_docx(chemin):
    """Document Word ; une image illisible (CRC faux dans « file (7).docx ») est remplacee par un fichier vide."""
    import docx
    try:
        return docx.Document(chemin)
    except zipfile.BadZipFile:
        tampon = io.BytesIO()
        with zipfile.ZipFile(chemin) as source, zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as copie:
            for nom in source.namelist():
                try:
                    contenu = source.read(nom)
                except zipfile.BadZipFile:
                    contenu = b""
                copie.writestr(nom, contenu)
        tampon.seek(0)
        return docx.Document(tampon)


def documents_eln_word(dossier, fichiers=ELN_WORD, nom_dossier="Progressions_Electroniques"):
    import construire_documents_m_coulibaly as coul
    sources = []
    for fichier, (matiere, serie, annee, libelle) in fichiers.items():
        chemin = os.path.join(dossier, fichier)
        document = ouvrir_docx(chemin)
        original = coul.docx.Document
        coul.docx.Document = lambda _chemin, _d=document: _d  # texte_docx relit le fichier : on lui passe le document
        try:
            texte = coul.texte_docx(chemin)
        finally:
            coul.docx.Document = original
        texte = TELEPHONES.sub("", texte)
        niveau = ANNEES[annee]
        option = {"BT_ELN": "BT Électronique", "BT_IND": "BT industriel", "BT_TER": "BT tertiaire", "BT_TOUS": "BT"}[serie]
        entete = f"PROGRESSION - {option}, {LIBELLES_ANNEES[niveau]} - {libelle}\n"
        sources.append(source(f"{nom_dossier}/{fichier}", open(chemin, "rb").read(), "PROGRESSION_ANNUELLE",
                              f"{libelle}, {LIBELLES_ANNEES[niveau]} {option}", matiere, serie, niveau,
                              [entete + texte], "progressions BT transmises à AfrJigi (10 oct. 2026)", "METFPA"))
    return sources


def main(dossier_adia, dossier_coulibaly, sortie, dossier_eln_word=None, dossier_cmc_tertiaire=None):
    sources = documents_adia(dossier_adia) + documents_coulibaly(dossier_coulibaly)
    if dossier_eln_word:
        sources += documents_eln_word(dossier_eln_word)
    if dossier_cmc_tertiaire:
        sources += documents_eln_word(dossier_cmc_tertiaire, CMC_TERTIAIRE, "CMC_Tertiare")
    for s in sources:
        print(f"{s['serie']:14} {s['niveau']:10} {s['matiere']:26} {len(s['morceaux']):3} extraits "
              f"{sum(map(len, s['morceaux'])):7} car. | {s['titre']}")
    json.dump({"recu_le": "2026-10-09", "sources": sources}, open(sortie, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main(*sys.argv[1:6])
