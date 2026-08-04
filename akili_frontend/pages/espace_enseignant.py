import streamlit as st
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime
import os

st.set_page_config(page_title="Espace Enseignant - AfrJigi", page_icon="🎓", layout="centered")

# Initialisation Firebase (reutilise l'app existante si deja initialisee)
if not firebase_admin._apps:
    cred_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "firebase_credentials.json")
    cred = credentials.Certificate(cred_path)
    firebase_admin.initialize_app(cred)
db = firestore.client()

st.markdown("<h1 style='color:#1E3A8A;'>🎓 Espace Enseignant AfrJigi</h1>", unsafe_allow_html=True)
st.markdown(
    "AfrJigi invite les enseignants à **tester Akili, signaler les erreurs et contribuer** "
    "à améliorer l'accompagnement des élèves ivoiriens. Rejoins le cercle enseignant AfrJigi !"
)
st.divider()

if "enseignant_soumis" not in st.session_state:
    st.session_state.enseignant_soumis = False

if st.session_state.enseignant_soumis:
    st.success("✅ Merci pour ton inscription ! Nous te contacterons bientôt sur WhatsApp ou par email.")
    if st.button("← Retour à l'accueil"):
        st.session_state.enseignant_soumis = False
        st.rerun()
else:
    with st.form("form_enseignant"):
        col1, col2 = st.columns(2)
        with col1:
            nom = st.text_input("👤 Nom complet *", placeholder="Ex: Kouamé N'Guessan")
            matiere = st.text_input("📖 Matière enseignée *", placeholder="Ex: Mathématiques")
            niveau = st.selectbox("🎓 Niveau enseigné *", ["BEPC", "BAC Général", "BAC Technique", "Plusieurs niveaux"])
        with col2:
            ecole = st.text_input("🏫 École / Université *", placeholder="Ex: Lycée Moderne de Cocody")
            whatsapp = st.text_input("📱 Numéro WhatsApp *", placeholder="Ex: +225 XX XX XX XX XX")
            email = st.text_input("📧 Email *", placeholder="exemple@gmail.com")
        commentaire = st.text_area("💬 Commentaire ou retour (optionnel)", placeholder="Dis-nous ce qui t'intéresse dans AfrJigi...")

        submit = st.form_submit_button("🚀 Rejoindre le cercle enseignant AfrJigi", use_container_width=True)

        if submit:
            if nom and matiere and niveau and ecole and whatsapp and email:
                db.collection("enseignants_interet").add({
                    "nom": nom.strip(),
                    "matiere": matiere.strip(),
                    "niveau": niveau,
                    "ecole": ecole.strip(),
                    "whatsapp": whatsapp.strip(),
                    "email": email.strip(),
                    "commentaire": commentaire.strip() if commentaire else "",
                    "statut": "nouveau",
                    "date_inscription": datetime.now().isoformat(),
                    "source": "app_streamlit",
                })
                st.session_state.enseignant_soumis = True
                st.rerun()
            else:
                st.error("⚠️ Merci de remplir tous les champs obligatoires (*).")
