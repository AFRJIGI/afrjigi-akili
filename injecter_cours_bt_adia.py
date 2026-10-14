"""Cours du BT Electronique de M. Adia (ETIC Korhogo, 14 oct. 2026) dans la base, pour la serie F2.

Dix fascicules, de la 1re a la 3e annee (= Seconde, Premiere, Terminale) : telephonie et radio-television
(matiere Electronique de F2), architecture des systemes informatiques (ASI) et teleinformatique et reseaux
(TIR) (matiere Informatique industrielle de F2). Chaque extrait devient un document COURS_ESSENTIEL (moins de
2 800 caracteres, lu en entier par l'API) avec une ligne qui rappelle que c'est un cours du BT : le programme
du BAC F2 peut etre different (decision du 10 oct. pour les documents BT).
Paquet : donnees/cours_bt_adia.json (donnees/construire_cours_bt_adia.py).

  python3 injecter_cours_bt_adia.py            # audit, aucune ecriture
  python3 injecter_cours_bt_adia.py --apply    # sauvegarde la base puis ajoute

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
DONNEES = Path(__file__).with_name("donnees") / "cours_bt_adia.json"
# discipline du fascicule -> matiere de la serie F2 dans le bot
MATIERES_F2 = {"TELEPHONIE": "ELECTRONIQUE", "RADIO_TV": "ELECTRONIQUE", "ASI": "INFORMATIQUE_INDUSTRIELLE",
               "TIR": "INFORMATIQUE_INDUSTRIELLE"}
CLASSES = {"SECONDE": "Seconde", "PREMIERE": "Première", "TERMINALE": "Terminale"}
ANNEES = {"SECONDE": "1re année", "PREMIERE": "2e année", "TERMINALE": "3e année"}


def documents_paquet(paquet):
    docs = []
    for s in paquet["sources"]:
        classe, annee = CLASSES[s["classe"]], ANNEES[s["classe"]]
        nb = len(s["extraits"])
        for k, e in enumerate(s["extraits"], 1):
            texte = (f"COURS DU BT ÉLECTRONIQUE - {s['libelle']}, {annee} (M. Adia, ETIC Korhogo) - {e['chapitre']}"
                     f" (extrait {k}/{nb})\n"
                     f"Cours du BT Électronique, donné à titre de cours pour la classe de {classe} de F2 : le "
                     "programme du BAC F2 peut être différent, suis la progression officielle de la série.\n\n"
                     + e["texte"])
            docs.append(dict(
                id=f"adia_cours_{s['discipline'].lower()}_{s['classe'].lower()}_{k:03d}",
                nom_fichier=f"{s['fichier']} (extrait {k}/{nb})",
                matiere=MATIERES_F2[s["discipline"]], discipline=s["discipline"], examen="BAC_TECHNIQUE",
                serie="F2", niveau=s["classe"], type_doc="COURS_ESSENTIEL", source="ENSEIGNANT",
                institution=paquet["institution"], transmis_par=paquet["transmis_par"], titre_chapitre=e["chapitre"],
                annee="2026", sha256=hashlib.sha256(texte.encode("utf-8")).hexdigest(), sha256_source=s["sha256"],
                texte=texte, score=5,
                resume=f"Cours de {s['libelle']} du BT Électronique ({annee}), {e['chapitre']}, par M. Adia",
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
        print(f"  F2 {matiere:26} {niveau:10} : {n} extraits à ajouter")
    print(f"Ajouts : {len(ajouts)} ; déjà présents : {len(candidats) - len(ajouts)} ; "
          f"total prévu : {len(data['documents']) + len(ajouts)}")
    if not args.apply or not ajouts:
        print("Audit terminé, aucune écriture." if not args.apply else "Rien à ajouter.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_avant_cours_bt_adia_{stamp}.json"
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
