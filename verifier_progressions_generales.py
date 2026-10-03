"""Verifie, sur la vraie base, quelle partie de progression Akili donnerait a chaque classe.

  python3 verifier_progressions_generales.py            # toutes les matieres
  python3 verifier_progressions_generales.py FRENCH     # une matiere
  python3 verifier_progressions_generales.py --voir ANGLAIS 4E   # le debut de la partie retenue
  python3 verifier_progressions_generales.py --titres ANGLAIS 4E # les titres de classe reperes

Pour chaque matiere et chaque classe : la progression choisie, la longueur de la partie
retenue et son debut. "AUCUNE" veut dire qu'Akili n'utilisera pas de progression.
Ne modifie rien.
"""
import ast
import json
import re
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

SOURCE = (Path(__file__).parent / "akili_api" / "main.py").read_text(encoding="utf-8")
FONCTIONS = {"serie_match", "normaliser_libelle_classe", "niveau_demande", "progression_de_reference",
             "aplatir", "classe_generale", "titres_de_classes", "section_de_classe", "fenetre_periode",
             "progression_generale"}
NOMS = {"CLASSES_GENERALES", "ALIAS_CLASSES", "MOIS_MAJ", "_SANS_ACCENT", "CLASSES_CONNUES"}
ns = {"re": re, "unicodedata": unicodedata, "datetime": datetime, "timezone": timezone}
noeuds = [n for n in ast.parse(SOURCE).body
          if (isinstance(n, ast.FunctionDef) and n.name in FONCTIONS)
          or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in NOMS for t in n.targets))]
exec(compile(ast.Module(body=noeuds, type_ignores=[]), "main.py", "exec"), ns)

CLASSES = [("6E", "CLASSE_INTERMEDIAIRE"), ("5E", "CLASSE_INTERMEDIAIRE"), ("4E", "CLASSE_INTERMEDIAIRE"),
           ("BEPC", "BEPC"), ("SECONDE_A", "CLASSE_INTERMEDIAIRE"), ("SECONDE_C", "CLASSE_INTERMEDIAIRE"),
           ("PREMIERE_A", "CLASSE_INTERMEDIAIRE"), ("PREMIERE_D", "CLASSE_INTERMEDIAIRE"),
           ("A2", "BAC_GENERAL"), ("C", "BAC_GENERAL"), ("D", "BAC_GENERAL")]


def main():
    from google.cloud import storage
    blob = storage.Client().bucket("akili-database-storage-astute-curve-307922").blob("data/jigi_global_database.json")
    docs = json.loads(blob.download_as_text(timeout=600))["documents"]
    if len(sys.argv) >= 4 and sys.argv[1] == "--voir":
        matiere, serie = sys.argv[2], sys.argv[3]
        examen = dict(CLASSES).get(serie, "BAC_GENERAL")
        p = ns["progression_de_reference"](docs, matiere, serie, examen, "Propose-moi un exercice")
        print(p["texte"][:2500] if p else "AUCUNE")
        return
    if len(sys.argv) >= 4 and sys.argv[1] == "--titres":
        matiere, serie = sys.argv[2], sys.argv[3]
        examen = dict(CLASSES).get(serie, "BAC_GENERAL")
        p = ns["progression_de_reference"](docs, matiere, serie, examen, "Propose-moi un exercice")
        if not p:
            print("AUCUNE")
            return
        original = next(d for d in docs if d.get("id") == p.get("id"))
        print(f"Document : {original.get('niveau')} ({len(original.get('texte', ''))} car.)")
        for pos, codes, ligne in ns["titres_de_classes"](original.get("texte", "")):
            print(f"  {pos:7} {'/'.join(sorted(codes)):12} {ligne[:90]}")
        return
    matieres = sorted({d.get("matiere") for d in docs if d.get("examen") == "TOUS"
                       and str(d.get("type_doc", "")).startswith("PROGRESSION")})
    if len(sys.argv) > 1:
        matieres = [m for m in matieres if m in sys.argv[1:]]
    maintenant = datetime.now(timezone.utc)
    for matiere in matieres:
        print("=" * 90)
        print(matiere)
        for serie, examen in CLASSES:
            p = ns["progression_de_reference"](docs, matiere, serie, examen, "Propose-moi un exercice")
            if not p:
                print(f"  {serie:11} AUCUNE")
                continue
            fenetre = ns["fenetre_periode"](p["texte"], maintenant)
            debut = re.sub(r"\s+", " ", p["texte"][:90])
            print(f"  {serie:11} {p.get('niveau', ''):17} partie {len(p['texte']):6} car. | {debut}")


if __name__ == "__main__":
    main()
