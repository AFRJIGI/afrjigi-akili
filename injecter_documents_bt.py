"""Tous les documents BT (Brevet de Technicien) dans la base d'Akili (decision du 9 oct. 2026).

Le BT fait partie du BAC Technique : options BT_ELN (Electronique), BT_IND (industriel), BT_TER (tertiaire) ;
1re, 2e et 3e annee rangees comme Seconde, Premiere et Terminale.

Contenu :
  - donnees/documents_bt.json (construit par donnees/construire_documents_bt.py) :
      21 progressions 2026-2027 du BT Electronique (M. Adia, ETIC Korhogo), de la 1re a la 3e annee ;
      6 progressions 2026-2027 d'Economie generale et d'EOE, 1re a 3e annee BT (M. Coulibaly) ;
      programmes de Mathematiques BT industriel (toutes options) et BT tertiaire (METFPA 2022), en extraits ;
  - le cours de mecanique appliquee / RDM de M. Sidibe (« MECA-RDM-BT1-BT2 »), deja present pour F1 et F2,
    ajoute aussi pour le BT industriel (matiere MECANIQUE_APPLIQUEE).

  python3 injecter_documents_bt.py            # audit, aucune ecriture
  python3 injecter_documents_bt.py --apply    # sauvegarde la base puis ajoute

Redeployer akili-api ensuite : l'API charge la base au demarrage.
"""
import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import injecter_cours_mecanique_sidibe as meca

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
DONNEES = Path(__file__).with_name("donnees") / "documents_bt.json"
RATTACHEMENT_MECA_BT = [("BT_IND", "MECANIQUE_APPLIQUEE", "sidibe_cours_meca_bt_ind",
                         "Utilisé aussi en BT industriel (1re et 2e année, BT1 et BT2 du document).\n")]


def slug(texte):
    texte = unicodedata.normalize("NFKD", texte).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "_", texte).strip("_")[:40]


def documents_paquet(paquet):
    docs = []
    for s in paquet["sources"]:
        nb = len(s["morceaux"])
        base_id = f"{slug(s['serie'].split()[0])}_{s['matiere'].lower()}"  # bt_eln_telephonie_seconde
        base_id += f"_{s['niveau'].lower()}" if s["type_doc"] != "PROGRAMME" else "_programme"
        for k, texte in enumerate(s["morceaux"], 1):
            docs.append(dict(
                id=base_id + (f"_{k:02d}" if nb > 1 else ""),
                nom_fichier=s["fichier"] + (f" (extrait {k}/{nb})" if nb > 1 else ""),
                matiere=s["matiere"], examen="BAC_TECHNIQUE", serie=s["serie"], niveau=s["niveau"],
                type_doc=s["type_doc"], source="ENSEIGNANT", institution=s["institution"],
                transmis_par=s["transmis_par"], titre=s["titre"],
                annee="2026-2027" if s["type_doc"] == "PROGRESSION_ANNUELLE" else "2022",
                sha256=hashlib.sha256(texte.encode("utf-8")).hexdigest(), sha256_source=s["sha256"],
                texte=texte, score=5,
                resume=f"{s['titre']} ({s['type_doc'].lower().replace('_', ' ')}), transmis par {s['transmis_par']}",
            ))
    return docs


def documents_meca_bt():
    paquet = json.loads(meca.DONNEES.read_text(encoding="utf-8"))
    return meca.documents_base(paquet, RATTACHEMENT_MECA_BT)


def plan(existants, candidats):
    ids = {d.get("id") for d in existants}
    empreintes = {d.get("sha256") for d in existants if d.get("sha256")}
    return [d for d in candidats if d["id"] not in ids and d["sha256"] not in empreintes]


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from google.cloud import storage

    candidats = documents_paquet(json.loads(DONNEES.read_text(encoding="utf-8"))) + documents_meca_bt()
    bucket = storage.Client(project="astute-curve-307922").bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    deja_bt = sum(1 for d in data["documents"] if str(d.get("serie") or "").upper().startswith("BT_"))
    print(f"Base actuelle : {len(data['documents'])} documents, dont {deja_bt} pour le BT")
    ajouts = plan(data["documents"], candidats)
    for (serie, matiere), n in sorted(Counter((d["serie"], d["matiere"]) for d in ajouts).items()):
        print(f"  {serie:14} {matiere:26} : {n} à ajouter")
    print(f"Ajouts proposés : {len(ajouts)} ; déjà présents : {len(candidats) - len(ajouts)} ; "
          f"total prévu : {len(data['documents']) + len(ajouts)}")
    if not args.apply or not ajouts:
        print("Audit terminé, aucune écriture." if not args.apply else "Rien à ajouter.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sauvegarde = f"data/backups/jigi_global_database_avant_documents_bt_{stamp}.json"
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
