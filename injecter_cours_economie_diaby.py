"""Cours d'economie transmis par M. Diaby : Support d'Economie (version preliminaire
septembre 2026, redige par l'Inspection de l'Economie), decoupe par chapitre et par section.

Le texte a deja ete extrait du PDF dans donnees/cours_economie_m_diaby_2026.json
(script donnees/construire_cours_economie_m_diaby.py). Chaque extrait devient un document
COURS_ESSENTIEL de la matiere ECO (BAC Technique) :
  - Economie generale (comptabilite nationale, croissance, sous-developpement, relations
    economiques internationales, change, balance des paiements) : series G1, G2 (pas B,
    qui suit son programme SES) ;
  - Economie et organisation des entreprises : series G1, G2.
Akili s'en sert pour expliquer les notions avec le contenu des enseignants.

  python3 injecter_cours_economie_diaby.py            # audit, aucune ecriture
  python3 injecter_cours_economie_diaby.py --apply    # sauvegarde la base puis ajoute

Redeployer akili-api ensuite : l'API charge la base au demarrage.
"""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
DONNEES = Path(__file__).with_name("donnees") / "cours_economie_m_diaby_2026.json"
CODES_PARTIE = {"Économie générale": "eg", "Économie et organisation des entreprises": "eoe"}


def documents_base(paquet):
    docs = []
    for d in paquet["documents"]:
        code = CODES_PARTIE[d["partie"]]
        docs.append(dict(
            id=f"diaby_cours_eco_{code}_ch{d['chapitre']}_{d['morceau']}",
            nom_fichier=f"Support d'Économie - {d['partie']} - {d['titre']} ({d['morceau']}/{d['nb_morceaux']})",
            matiere="ECO", discipline="ECONOMIE", examen="BAC_TECHNIQUE",
            serie=d["serie"], niveau="TERMINALE", niveau_source="BTS tertiaire 2e année",
            type_doc="COURS_ESSENTIEL", source="ENSEIGNANT", institution="Inspection de l'Économie",
            transmis_par=paquet["transmis_par"], version="2026-09 (version préliminaire)", annee="2026",
            partie=d["partie"], chapitre=d["chapitre"], titre_chapitre=d["titre"],
            sha256=hashlib.sha256(d["texte"].encode("utf-8")).hexdigest(),
            sha256_source=paquet.get("sha256_pdf", ""),
            texte=d["texte"], score=5,
            resume=f"Cours d'économie ({d['partie']}) : {d['titre']}, extrait {d['morceau']}/{d['nb_morceaux']}",
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

    paquet = json.loads(DONNEES.read_text(encoding="utf-8"))
    candidats = documents_base(paquet)
    client = storage.Client(project="astute-curve-307922")
    bucket = client.bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    deja = [d for d in data["documents"] if str(d.get("matiere", "")).upper() == "ECO"]
    print(f"Base actuelle : {len(data['documents'])} documents, dont {len(deja)} en économie")
    ajouts = plan(data["documents"], candidats)
    for partie in CODES_PARTIE:
        n = sum(1 for d in ajouts if d["partie"] == partie)
        chapitres = sorted({d["chapitre"] for d in candidats if d["partie"] == partie})
        print(f"  {partie} : {n} extraits à ajouter ({len(chapitres)} chapitres)")
    print(f"Ajouts proposés : {len(ajouts)} ; déjà présents : {len(candidats) - len(ajouts)} ; "
          f"total prévu : {len(data['documents']) + len(ajouts)}")
    if not args.apply or not ajouts:
        print("Audit terminé, aucune écriture." if not args.apply else "Rien à ajouter.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_avant_cours_eco_diaby_{stamp}.json"
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
