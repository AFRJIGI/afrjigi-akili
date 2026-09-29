"""Un seul ajout : progression du Lycee technique Abidjan, Terminale G.

Audit par defaut. --apply sauvegarde puis ajoute, sans remplacer les documents.
Dependance Cloud Shell : google-cloud-storage. Extraction DOCX sans IA.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import re
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

BUCKET = "akili-database-storage-astute-curve-307922"
DATABASE = "data/jigi_global_database.json"
URL = "https://www.fomesoutra.com/livres/23282-progression-de-economie-generale-tle-g/file?force_download=1"
SHA256 = "d407f740a8d76d177634f7f363d3964cc3dfbfe318cbb7a9541847e802241d37"
DOC_ID = "metfpa_progression_economie_generale_2025_2026_terminale_g"
W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def normalized(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"\W+", "", text)


def build_document(content):
    if hashlib.sha256(content).hexdigest() != SHA256:
        raise ValueError("Le fichier source a change : nouvelle verification requise.")
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs = ["".join(n.text or "" for n in p.iter(W + "t")) for p in root.iter(W + "p")]
    text = "\n".join(p for p in paragraphs if p.strip())
    compact = normalized(text)
    for marker in ("20252026", "terminale g", "economie generale", "lycee technique abidjan"):
        if normalized(marker) not in compact:
            raise ValueError("Metadonnee attendue absente : " + marker)
    return dict(
        id=DOC_ID, nom_fichier="METFPA_LTA_2025-2026_ECONOMIE_GENERALE_TERMINALE_G.docx",
        matiere="ECO", discipline="ECONOMIE_GENERALE", examen="BAC_TECHNIQUE",
        serie="G1G2", classe_source="TERMINALE G", niveau="TERMINALE",
        perimetre_indexation="G1 et G2 dans le perimetre BAC tertiaire Akili",
        annee="2025-2026", version="2025-2026", type_doc="PROGRESSION_ANNUELLE",
        source="METFPA_LYCEE_TECHNIQUE_ABIDJAN", institution="METFPA",
        etablissement="Lycee technique Abidjan", portee="ETABLISSEMENT",
        portail_source="FOMESOUTRA", statut_source="MIROIR_FOMESOUTRA",
        source_url=URL, sha256=SHA256, texte=text, score=5,
        resume="Progression d'etablissement, economie generale Terminale G, 2025-2026. Ne constitue pas une preuve de prescription nationale.",
    )


def assess(existing, candidate):
    """Identite certaine => SKIP ; ressemblance importante => REVIEW bloquant."""
    target = normalized(candidate["texte"])
    words = set(re.findall(r"\w+", candidate["texte"].lower()))
    suspects = []
    for doc in existing:
        raw = doc.get("texte") or ""
        if isinstance(raw, list):
            raw = " ".join(map(str, raw))
        raw = str(raw)
        text = normalized(raw)
        url = str(doc.get("source_url") or "")
        if (doc.get("id") == DOC_ID or doc.get("sha256") == SHA256
                or "23282-progression-de-economie-generale-tle-g/" in url
                or (text and text == target)):
            return "SKIP", [doc.get("id") or doc.get("nom_fichier")]
        # Un texte voisin ou deja inclus dans un gros document requiert une revue.
        other_words = set(re.findall(r"\w+", raw.lower()))
        overlap = len(words & other_words) / max(1, len(words | other_words))
        if (text and min(len(text), len(target)) > 500 and (target in text or text in target)) or overlap >= 0.80:
            suspects.append(doc.get("id") or doc.get("nom_fichier"))
    return ("REVIEW", suspects) if suspects else ("CREATE", [])


def persist(bucket, blob, generation, original, data, candidate, content):
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = f"data/backups/jigi_before_economie_generale_{stamp}.json"
    bucket.blob(backup).upload_from_string(original, content_type="application/json", if_generation_match=0)
    print(f"Backup: gs://{BUCKET}/{backup}")
    doc = dict(candidate)
    doc["chemin"] = f"ingestion_officielle/metfpa/economie/{SHA256}.docx"
    target = bucket.blob(doc["chemin"])
    if not target.exists():
        target.upload_from_string(content, content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", if_generation_match=0)
    doc["integre_le"] = datetime.now(timezone.utc).isoformat()
    result = dict(data, documents=[*data["documents"], doc])
    result.update(total=len(result["documents"]), generated_at=doc["integre_le"])
    blob.upload_from_string(json.dumps(result, ensure_ascii=False, indent=2), content_type="application/json", if_generation_match=generation)
    print(f"Termine: 1 ajout; total={result['total']}")


def run(bucket, content, apply=False):
    candidate = build_document(content)
    blob = bucket.blob(DATABASE)
    blob.reload()
    generation = int(blob.generation)
    original = blob.download_as_bytes(if_generation_match=generation, timeout=600)
    data = json.loads(original)
    status, matches = assess(data["documents"], candidate)
    print(f"Base actuelle: {len(data['documents'])} documents")
    print(f"{status} | {DOC_ID}")
    if matches:
        print("Documents a comparer :", json.dumps(matches, ensure_ascii=False))
    print("Source : progression d'etablissement, Lycee technique Abidjan, 2025-2026.")
    if status == "REVIEW":
        raise RuntimeError("Ressemblance detectee : aucune ecriture, verifier le contenu.")
    if status == "SKIP" or not apply:
        print("Aucune ecriture. Ajouts proposes:", int(status == "CREATE"))
        return
    persist(bucket, blob, generation, original, data, candidate, content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from google.cloud import storage
    for attempt in range(4):
        try:
            request = urllib.request.Request(URL, headers={"User-Agent": "AfrJigi-Akili/1.0"})
            with urllib.request.urlopen(request, timeout=90) as response:
                content = response.read()
            break
        except OSError:
            if attempt == 3:
                raise
            time.sleep(5 * (attempt + 1))
    bucket = storage.Client(project="astute-curve-307922").bucket(BUCKET)
    run(bucket, content, args.apply)


if __name__ == "__main__":
    main()
