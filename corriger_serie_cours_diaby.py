"""Retire la serie B du cours d'Economie generale de M. Diaby (support de BTS) dans la base.

M. Coulibaly, enseignant d'economie, constate qu'en serie B Akili ramene l'economie vers la
comptabilite. Les 38 extraits d'Economie generale du support de BTS (comptabilite nationale,
agregats, tableaux) etaient rattaches a B, G1 et G2 et passaient avant la progression SES de la
serie B. Ils restent pour G1 et G2 ; la serie B garde son programme SES, ses progressions et ses
annales.

  python3 corriger_serie_cours_diaby.py            # audit, aucune ecriture
  python3 corriger_serie_cours_diaby.py --apply    # sauvegarde la base puis corrige

Redeployer akili-api ensuite. Retour en arriere : recopier la sauvegarde indiquee.
"""
import argparse
import json
from datetime import datetime, timezone

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
PREFIXE = "diaby_cours_eco_eg_"


def a_corriger(documents):
    return [d for d in documents if str(d.get("id", "")).startswith(PREFIXE) and d.get("serie") != "G1G2"]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from google.cloud import storage

    bucket = storage.Client(project="astute-curve-307922").bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    cibles = a_corriger(data["documents"])
    print(f"Base : {len(data['documents'])} documents ; extraits d'Économie générale (Diaby) à passer en G1G2 : {len(cibles)}")
    for d in cibles[:3]:
        print(f"  {d['id']} : série {d.get('serie')} -> G1G2")
    if not args.apply or not cibles:
        print("Audit terminé, aucune écriture." if not args.apply else "Rien à corriger.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_avant_serie_diaby_{stamp}.json"
    bucket.blob(sauvegarde).upload_from_string(original, content_type="application/json", if_generation_match=0)
    print(f"Sauvegarde : gs://{BUCKET}/{sauvegarde}")
    for d in cibles:
        d["serie"] = "G1G2"
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    blob.upload_from_string(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json",
                            if_generation_match=generation)
    print(f"Terminé : {len(cibles)} extraits corrigés. Redéploie akili-api.")


if __name__ == "__main__":
    main()
