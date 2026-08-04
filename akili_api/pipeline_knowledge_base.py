import json
from datetime import datetime
from google.cloud import storage, firestore
import vertexai
from vertexai.generative_models import GenerativeModel, Part

PROJECT_ID  = "astute-curve-307922"
BUCKET_NAME = "akili-database-storage-astute-curve-307922"
DB_BLOB     = "data/jigi_global_database.json"
SCORE_MIN   = 3

vertexai.init(project=PROJECT_ID, location="us-central1")
model = GenerativeModel("gemini-2.5-flash")
db    = firestore.Client()

def load_database():
    client = storage.Client()
    data   = json.loads(client.bucket(BUCKET_NAME).blob(DB_BLOB).download_as_text())
    print(f"Base chargee : {data['total']} documents")
    return data

def save_database(data):
    client = storage.Client()
    data["generated_at"] = datetime.utcnow().isoformat()
    data["total"] = len(data["documents"])
    client.bucket(BUCKET_NAME).blob(DB_BLOB).upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json")
    print(f"Base sauvegardee : {data['total']} documents")

def list_uploads():
    client = storage.Client()
    blobs  = list(client.bucket(BUCKET_NAME).list_blobs(prefix="uploads/"))
    result = [b for b in blobs if not b.name.endswith("/")]
    print(f"{len(result)} fichiers dans uploads/")
    return result

def analyser(blob):
    print(f"Analyse : {blob.name}")
    try:
        file_bytes = blob.download_as_bytes()
        mime_type  = blob.content_type or "image/jpeg"
        prompt = 'Analyse ce document educatif ivoirien. Reponds UNIQUEMENT en JSON: {"est_educatif": true, "matiere": "MATHS", "serie": "D", "annee": "2024", "type_doc": "SUJET", "resume": "...", "texte_extrait": "...", "score_qualite": 4}'
        part     = Part.from_data(data=file_bytes, mime_type=mime_type)
        response = model.generate_content([part, prompt])
        text     = response.text.strip()
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        result = json.loads(text.strip())
        print(f"  Matiere: {result.get('matiere')} Score: {result.get('score_qualite')}/5")
        return result
    except Exception as e:
        print(f"  Erreur: {e}")
        return None

def run():
    print("Pipeline AfrJigi Knowledge Base")
    data    = load_database()
    uploads = list_uploads()
    traites = set(d.get("upload_path", "") for d in data["documents"])
    integres = 0
    for blob in uploads:
        if blob.name in traites:
            print(f"Deja traite: {blob.name}")
            continue
        analyse = analyser(blob)
        if not analyse:
            continue
        if not analyse.get("est_educatif") or analyse.get("score_qualite", 0) < SCORE_MIN:
            print(f"  Rejete score {analyse.get('score_qualite', 0)}/5")
            continue
        matiere  = analyse.get("matiere", "AUTRE")
        serie    = analyse.get("serie", "TOUTES")
        annee    = analyse.get("annee", "INCONNUE")
        type_doc = analyse.get("type_doc", "AUTRE")
        filename = blob.name.split("/")[-1]
        dest     = f"knowledge_base/{matiere}/{serie}/{annee}_{type_doc}_{filename}"
        client   = storage.Client()
        client.bucket(BUCKET_NAME).copy_blob(blob, client.bucket(BUCKET_NAME), dest)
        print(f"  Copie vers: {dest}")
        data["documents"].append({
            "id": dest.replace("/", "_"),
            "nom_fichier": filename,
            "chemin": dest,
            "matiere": matiere,
            "serie": serie,
            "annee": annee,
            "type_doc": type_doc,
            "source": "upload_eleve",
            "score": analyse.get("score_qualite", 0),
            "texte": analyse.get("texte_extrait", ""),
            "resume": analyse.get("resume", ""),
            "integre_le": datetime.utcnow().isoformat(),
            "upload_path": blob.name
        })
        integres += 1
        print(f"  Integre dans la base")
    if integres > 0:
        save_database(data)
    print(f"Termine : {integres} documents integres")

run()
