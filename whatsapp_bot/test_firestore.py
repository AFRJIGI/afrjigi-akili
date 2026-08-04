from google.cloud import firestore
from datetime import date

try:
    print("⏳ Tentative de connexion à Firestore...")
    db = firestore.Client()
    
    test_ref = db.collection("users").document("test_phone_number")
    
    print("✍️ Écriture d'un profil fictif...")
    test_ref.set({
        "whatsapp_phone": "123456789",
        "tier": "FREE",
        "questions_today": 0,
        "last_message_date": str(date.today()),
        "serie": "D",
        "matiere": "MATHS"
    })
    
    print("🎉 SUCCÈS : L'écriture dans Firestore a fonctionné !")
    
    print("📖 Lecture de vérification...")
    doc = test_ref.get()
    if doc.exists:
        print(f"📊 Données lues avec succès : {doc.to_dict()}")
    else:
        print("❌ Erreur : Le document n'a pas été trouvé après l'écriture.")

except Exception as e:
    print(f"💥 ÉCHEC de la configuration : {e}")
