"""Audit par defaut ; --apply sauvegarde puis ajoute les PDF verifies.

Dependances : google-cloud-storage, pypdf. Pas d'extraction generative.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import time
import urllib.request
from datetime import datetime, timezone

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
VERSION = "2026-09"
# Identifiant du portail, niveau, serie du registre, classe originale du PDF.
CANDIDATES = [
    (28974, "PREMIERE", "B", "1B"),
    (28973, "PREMIERE", "E", "1E"),
    (28972, "PREMIERE", "F1F2F3", "1F1,2,3"),
    (28971, "PREMIERE", "F7", "1F7"),
    (28970, "PREMIERE", "G1", "1G1"),
    (28969, "PREMIERE", "G2", "1G2"),
    (28967, "SECONDE", "B", "2NDE AB"),
    (28966, "SECONDE", "G2", "2NDE G2"),
    (28956, "SECONDE", "G1", "2NDE G1"),
    (28961, "TERMINALE", "B", "TB"),
    (28960, "TERMINALE", "E", "TE"),
    (28959, "TERMINALE", "F1F2F3", "TF1,2,3"),
    (28958, "TERMINALE", "F7", "TF7"),
    (28957, "TERMINALE", "G1", "TG1"),
    (28948, "TERMINALE", "G2", "TG2"),
]


def download(url):
    for attempt in range(4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AfrJigi-Akili/1.0"})
            with urllib.request.urlopen(req, timeout=90) as response:
                content = response.read()
            if not content.startswith(b"%PDF-"):
                raise ValueError("Reponse non PDF : " + url)
            return content
        except OSError:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))


def plan(existing, candidates):
    """Deduplication globale par ID, URL, empreinte PDF ou texte exact."""
    ids = {d.get("id") for d in existing}
    urls = {d.get("source_url") for d in existing if d.get("source_url")}
    hashes = {d.get("sha256") for d in existing if d.get("sha256")}
    texts = {" ".join(d["texte"].split()) for d in existing if isinstance(d.get("texte"), str) and d["texte"].strip()}
    additions = []
    for doc in candidates:
        normalized = " ".join(doc["texte"].split())
        duplicate = doc["id"] in ids or doc["source_url"] in urls or doc["sha256"] in hashes or normalized in texts
        print(f"{'SKIP' if duplicate else 'CREATE'} | {doc['id']}")
        if not duplicate:
            additions.append(doc)
            ids.add(doc["id"])
            urls.add(doc["source_url"])
            hashes.add(doc["sha256"])
            texts.add(normalized)
    return additions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from google.cloud import storage
    from pypdf import PdfReader

    inventory = json.loads((Path(__file__).parent / "reports/bac_technique_progressions_inventory.json").read_text(encoding="utf-8"))["inventaire"]
    client = storage.Client(project="astute-curve-307922")
    bucket = client.bucket(BUCKET)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    print(f"Base actuelle: {len(data['documents'])} documents")
    docs, pdfs = [], {}
    for portal_id, level, series, original_class in CANDIDATES:
        matches = [d for d in inventory if d["url"].split("/")[-2].startswith(str(portal_id) + "-")]
        if len(matches) != 1:
            raise ValueError(f"Lien ambigu ou absent : {portal_id}")
        url = matches[0]["url"]
        content = download(url)
        text = "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages)
        normalized = " ".join(text.upper().split())
        if "SEPTEMBRE 2026" not in normalized or f"PROGRESSION {original_class}" not in normalized:
            raise ValueError(f"Edition ou classe inattendue : {portal_id}")
        digest = hashlib.sha256(content).hexdigest()
        pdfs[digest] = content
        name = f"METFPA_MATHS_EDITION_2026-09_{level}_{series}.pdf"
        docs.append(dict(
            id=f"metfpa_progression_maths_2026_09_{level.lower()}_{series.lower()}",
            nom_fichier=name, chemin=f"knowledge_base/MATHS/{series}/{name}",
            matiere="MATHS", discipline="MATHEMATIQUES", examen="BAC_TECHNIQUE",
            serie=series, niveau=level, classe_source=original_class,
            annee="2026", version=VERSION, annee_scolaire=None,
            edition_source="Septembre 2026", type_doc="PROGRESSION_ANNUELLE",
            source="METFPA_OFFICIEL", institution="METFPA",
            institution_catalogue="METFPA", portail_source="FOMESOUTRA",
            autorite_document="Ministere de l'Education nationale, de l'Alphabetisation et de l'Enseignement technique - Cabinet du ministre delegue charge de l'Enseignement technique",
            statut_source="MIROIR_FOMESOUTRA", source_url=url, sha256=digest,
            texte=text, score=5,
            resume=f"Progression mathematiques {level} {series}, edition septembre 2026",
        ))
    additions = plan(data["documents"], docs)
    print(f"Ajouts proposes: {len(additions)}; total prevu: {len(data['documents']) + len(additions)}")
    print("Les anciens PDF sans SHA256 ne peuvent pas etre compares octet par octet.")
    if not args.apply or not additions:
        print("Audit termine, aucune ecriture.")
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = f"data/backups/jigi_global_database_before_maths_tech_2026_09_{stamp}.json"
    bucket.blob(backup).upload_from_string(original, content_type="application/json", if_generation_match=0)
    print(f"Backup: gs://{BUCKET}/{backup}")
    for doc in additions:
        # Stockage immuable adresse par empreinte ; aucun ancien PDF remplace.
        doc["chemin"] = f"ingestion_officielle/metfpa/maths/{doc['sha256']}.pdf"
        target = bucket.blob(doc["chemin"])
        if not target.exists():
            target.upload_from_string(pdfs[doc["sha256"]], content_type="application/pdf", if_generation_match=0)
        doc["integre_le"] = datetime.now(timezone.utc).isoformat()
    data["documents"].extend(additions)
    data["total"] = len(data["documents"])
    data["generated_at"] = datetime.now(timezone.utc).isoformat()
    blob.upload_from_string(json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json", if_generation_match=generation)
    print(f"Termine: {len(additions)} ajouts; total={data['total']}")


if __name__ == "__main__":
    main()
