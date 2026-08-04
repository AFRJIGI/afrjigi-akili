import json
from google.cloud import storage
from datetime import datetime
import vertexai
from vertexai.generative_models import GenerativeModel, Part

PROJECT_ID = "astute-curve-307922"
BUCKET_NAME = "akili-database-storage-astute-curve-307922"
DB_BLOB = "data/jigi_global_database.json"

vertexai.init(project=PROJECT_ID, location="us-central1")
model = GenerativeModel("gemini-2.5-flash")

FICHIERS = [
    {"local": "Jigi/01_OFFICIAL_ARCHIVES/SERIE-C/MATHS/2015_BAC_SERIE-C_MATHS_SUJET-CORR-BAREME.pdf", "matiere": "MATHS", "serie": "C", "annee": "2015"},
    {"local": "Jigi/01_OFFICIAL_ARCHIVES/SERIE-C/MATHS/2018_BAC_SERIE-C_MATHS_SUJET-CORR-BAREME.pdf", "matiere": "MATHS", "serie": "C", "annee": "2018"},
    {"local": "Jigi/01_OFFICIAL_ARCHIVES/SERIE-C/PC/2023_BAC_SERIE-CE_PC_SUJET-BAREME.pdf", "matiere": "PC", "serie": "C", "annee": "2023"},
    {"local": "Jigi/01_OFFICIAL_ARCHIVES/SERIE-C/PC/2023_BAC_SERIE-C-E_PC_SUJET-BAREME.pdf", "matiere": "PC", "serie": "CE", "annee": "2023"},
    {"local": "Jigi/01_OFFICIAL_ARCHIVES/SERIE-A/ANG/2023_BAC_SERIE-A1A2_ANG_SUJET-BAREME.pdf", "matiere": "ANGLAIS", "serie": "A", "annee": "2023"},
    {"local": "Jigi/02_INSTRUCTIONAL_LOGIC/PEDAGOGICAL_GUIDES/MATHS/0000_MANUEL_SERIE-C_MATHS_GEOM-PROBA.pdf.pdf", "matiere": "MATHS", "serie": "C", "annee": "INCONNUE"},
    {"local": "Jigi/02_INSTRUCTIONAL_LOGIC/PEDAGOGICAL_GUIDES/MATHS/0000_MANUEL_SERIE-C_MATHS_ANALYSE.pdf.pdf", "matiere": "MATHS", "serie": "C", "annee": "INCONNUE"},
]

def load_database():
    client = storage.Client()
    data = json.loads(client.bucket(BUCKET_NAME).blob(DB_BLOB).download_as_text())
    print(f"Base chargee : {data['total']} documents")
    return data

def save_database(data):
    client = storage.Client()
    data["generated_at"] = datetime.now().isoformat()
    data["total"] = len(data["documents"])
    client.bucket(BUCKET_NAME).blob(DB_BLOB).upload_from_string(
        json.dumps(data, ensure_ascii=False, indent=2), content_type="application/json")
    print(f"Base sauvegardee : {data['total']} documents")

def extraire_texte(file_bytes):
    try:
        part = Part.from_data(data=file_bytes, mime_type="application/pdf")
        response = model.generate_content([part,
            "Extrais tout le texte de ce document PDF de maniere complete et fidele. Inclus tous les exercices, enonces, questions et reponses. Reponds uniquement avec le texte extrait sans commentaire."])
        return response.text.strip()
    except Exception as e:
        print(f"  Erreur extraction : {e}")
        return ""

def run():
    data = load_database()
    client = storage.Client()
    bucket = client.bucket(BUCKET_NAME)
    mis_a_jour = 0
    for f in FICHIERS:
        local_path = f["local"]
        nom_fichier = local_path.split("/")[-1]
        print(f"\nTraitement : {nom_fichier}")
        try:
            with open(local_path, "rb") as fp:
                file_bytes = fp.read()
            print(f"  Taille : {len(file_bytes)} bytes")
            blob = bucket.blob(local_path)
            blob.upload_from_string(file_bytes, content_type="application/pdf")
            print(f"  Upload GCS OK")
            texte = extraire_texte(file_bytes)
            print(f"  Texte extrait : {len(texte)} caracteres")
            for doc in data["documents"]:
                if doc.get("nom_fichier") == nom_fichier:
                    doc["texte"] = texte
                    doc["nb_caracteres"] = len(texte)
                    mis_a_jour += 1
                    print(f"  Document mis a jour dans la base")
                    break
        except Exception as e:
            print(f"  Erreur : {e}")
    if mis_a_jour > 0:p
        save_database(data)
    print(f"\nTermine : {mis_a_jour} documents mis a jour")

run()