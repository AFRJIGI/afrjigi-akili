"""Cours harmonises de mathematiques generales G2-G3 (Seconde, Premiere, Terminale ; edition de septembre
2023), transmis par M. Brou le 22 oct. 2026, dans la base : matiere MATHS de la serie G2 du BAC Technique.

Chaque extrait devient un document COURS_ESSENTIEL (moins de 2 800 caracteres, lu en entier par l'API) avec
une ligne qui rappelle sa classe : la recherche de l'API ne filtre pas par classe.
Paquet : donnees/cours_maths_generales_g2_g3.json (donnees/construire_cours_maths_g2_g3.py).

  python3 injecter_cours_maths_g2_g3.py            # audit, aucune ecriture
  python3 injecter_cours_maths_g2_g3.py --apply    # sauvegarde la base puis ajoute

Redeployer akili-api ensuite : l'API charge la base au demarrage.
"""
import argparse
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
DONNEES = Path(__file__).with_name("donnees") / "cours_maths_generales_g2_g3.json"
CLASSES = {"SECONDE": "Seconde", "PREMIERE": "Première", "TERMINALE": "Terminale"}


def documents_paquet(paquet):
    docs = []
    for s in paquet["sources"]:
        classe = CLASSES[s["classe"]]
        nb = len(s["extraits"])
        for k, e in enumerate(s["extraits"], 1):
            texte = (f"COURS DE MATHÉMATIQUES GÉNÉRALES - {classe} G2-G3 (cours harmonisés, septembre 2023) - "
                     f"{e['chapitre']} (extrait {k}/{nb})\n"
                     f"Cours de la classe de {classe} G2 : pour un élève d'une autre classe, suis la progression "
                     "de sa classe.\n\n" + e["texte"])
            docs.append(dict(
                id=f"maths_g2_g3_{s['classe'].lower()}_{k:03d}",
                nom_fichier=f"Cours harmonisés de mathématiques générales {classe} G2-G3 (extrait {k}/{nb})",
                matiere="MATHS", examen="BAC_TECHNIQUE", serie="G2", niveau=s["classe"],
                type_doc="COURS_ESSENTIEL", source="ENSEIGNANT", institution="COURS_HARMONISES_G2_G3",
                transmis_par=paquet["transmis_par"], titre_chapitre=e["chapitre"], annee="2023",
                sha256=hashlib.sha256(texte.encode("utf-8")).hexdigest(), sha256_source=s["sha256"],
                texte=texte, score=5,
                resume=f"Cours harmonisé de mathématiques générales, {classe} G2-G3, {e['chapitre']}",
            ))
    return docs


def plan(existants, candidats):
    ids = {d.get("id") for d in existants}
    empreintes = {d.get("sha256") for d in existants if d.get("sha256")}
    return [d for d in candidats if d["id"] not in ids and d["sha256"] not in empreintes]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from google.cloud import storage

    candidats = documents_paquet(json.loads(DONNEES.read_text(encoding="utf-8")))
    bucket = storage.Client(project="astute-curve-307922").bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    ajouts = plan(data["documents"], candidats)
    print(f"Base actuelle : {len(data['documents'])} documents")
    for (matiere, niveau), n in sorted(Counter((d["matiere"], d["niveau"]) for d in ajouts).items()):
        print(f"  G2 {matiere:6} {niveau:10} : {n} extraits à ajouter")
    print(f"Ajouts : {len(ajouts)} ; déjà présents : {len(candidats) - len(ajouts)} ; "
          f"total prévu : {len(data['documents']) + len(ajouts)}")
    if not args.apply or not ajouts:
        print("Audit terminé, aucune écriture." if not args.apply else "Rien à ajouter.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_avant_cours_maths_g2_g3_{stamp}.json"
    bucket.blob(sauvegarde).upload_from_string(original, content_type="application/json", if_generation_match=0)
    print(f"Sauvegarde : gs://{BUCKET}/{sauvegarde}")
    maintenant = datetime.now(timezone.utc).isoformat()
    for d in ajouts:
        d["integre_le"] = maintenant
    data["documents"].extend(ajouts)
    data["total"] = len(data["documents"])
    data["generated_at"] = maintenant
    blob.upload_from_string(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json",
                            if_generation_match=generation)
    print(f"Terminé : {len(ajouts)} ajouts ; total {data['total']}. Redéploie akili-api.")


if __name__ == "__main__":
    main()
