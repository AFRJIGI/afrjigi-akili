import streamlit as st
from examens_config import get_series, get_matieres
import coefficients
import time
import requests
import firebase_admin
from firebase_admin import credentials, firestore
from datetime import datetime, date
import os
from gtts import gTTS
import io, json, hashlib, urllib.parse

AKILI_API_URL = "https://akili-api-598190730734.us-central1.run.app/question"
TRANSCRIBE_URL = "https://akili-api-598190730734.us-central1.run.app/transcribe"
QUESTIONS_GRATUITES = 5
ACCES_GRATUIT_BAC = date.today() <= date(2026, 6, 15)
PAYDUNYA_MASTER_KEY = os.environ.get("")
PAYDUNYA_PRIVATE_KEY = os.environ.get("")
PAYDUNYA_TOKEN = os.environ.get("")
STRIPE_LINK = os.environ.get("STRIPE_LINK", "https://buy.stripe.com/test_9B6dRb3znaUq4I49Xa1Jm00")

if not firebase_admin._apps:
    cred = credentials.Certificate("firebase_credentials.json")
    firebase_admin.initialize_app(cred)
db = firestore.client()

st.set_page_config(page_title="AfrJigi - Prépare ton BAC avec l'IA", page_icon="🌍", layout="wide")

query_params = st.query_params
if query_params.get("page") == "landing":
    with open("static/index.html", "r") as f:
        st.components.v1.html(f.read(), height=5000, scrolling=True)
    st.stop()

MATIERES = [
    "Mathématiques",
    "Philosophie",
    "Physique-Chimie",
    "Sciences de la Vie et de la Terre (SVT)",
    "Histoire-Géographie",
    "Anglais",
    "Français",
    "Allemand",
    "Espagnol"
]

def get_or_create_user(email, name):
    clean_email = email.strip()
    ref = db.collection("users").document(clean_email)
    user = ref.get()
    today = date.today().isoformat()
    if not user.exists:
        ref.set({"email": clean_email, "name": name, "plan": "gratuit", "questions_today": 0, "last_question_date": today, "created_at": datetime.now().isoformat()})
        return ref.get().to_dict()
    data = user.to_dict()
    if data.get("last_question_date") != today:
        ref.update({"questions_today": 0, "last_question_date": today})
        data["questions_today"] = 0
    return data

def increment_questions(email):
    db.collection("users").document(email.strip()).update({"questions_today": firestore.Increment(1)})

def save_message(email, role, content_msg, matiere, type_examen):
    db.collection("users").document(email.strip()).collection("messages").add({"role": role, "content": content_msg, "timestamp": datetime.now().isoformat(), "matiere": matiere, "type_examen": type_examen})

def load_messages(email, matiere, type_examen):
    try:
        msgs = db.collection("users").document(email.strip()).collection("messages").where("matiere", "==", matiere).where("type_examen", "==", type_examen).order_by("timestamp").limit(50)
        return [{"role": m.to_dict()["role"], "content": m.to_dict()["content"]} for m in msgs.stream()]
    except Exception as e:
        print(f"Erreur : {e}")
        st.warning(f"⚠️ Impossible de charger l'historique : {e}")
        return []

def clear_messages(email):
    msgs = db.collection("users").document(email.strip()).collection("messages")
    for msg in msgs.stream():
        msg.reference.delete()

def can_ask_question(user_data):
    if ACCES_GRATUIT_BAC:
        return True
    if user_data.get("plan") == "premium" or user_data.get("tier") == "PREMIUM":
        return True
    return user_data.get("questions_today", 0) < QUESTIONS_GRATUITES

def questions_restantes(user_data):
    if ACCES_GRATUIT_BAC or user_data.get("plan") == "premium" or user_data.get("tier") == "PREMIUM":
        return "∞"
    return max(0, QUESTIONS_GRATUITES - user_data.get("questions_today", 0))

if "user" not in st.session_state: st.session_state.user = None
if "user_data" not in st.session_state: st.session_state.user_data = None
if "onboarded" not in st.session_state: st.session_state.onboarded = False
if "messages" not in st.session_state: st.session_state.messages = []
if "image_cliquee" not in st.session_state: st.session_state.image_cliquee = None
if "audio_prompt" not in st.session_state: st.session_state.audio_prompt = None
if "profile" not in st.session_state: st.session_state.profile = {}

# ─── PAGE CONNEXION ───────────────────────────────────
if not st.session_state.user:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        col_l, col_m, col_r = st.columns([1, 2, 1])
        with col_m:
            st.image("static/logo.png", width=250)
        st.markdown("<div style='text-align:center;padding:20px 0;'><p style='color:#6B7280;font-size:1.2em;'>La plateforme IA de préparation au BAC africain</p></div>", unsafe_allow_html=True)
        st.markdown("---")
        st.markdown("### 🔐 Connecte-toi pour commencer")
        email = st.text_input("📧 Ton adresse email", placeholder="exemple@gmail.com")
        name = st.text_input("👤 Ton prénom", placeholder="Kouamé")
        if st.button("🚀 Accéder à AfrJigi", use_container_width=True):
            if email and name:
                user_data = get_or_create_user(email, name)
                st.session_state.user = {"email": email.strip(), "name": name}
                st.session_state.user_data = user_data
                st.session_state.messages = []  # sera charge une fois la matiere connue
                # Si l'utilisateur a deja un profil complet en Firestore, on le recharge
                # et on saute l'onboarding (evite le bug de profil BEPC/BAC melange)
                if user_data.get("type_examen"):
                    st.session_state.profile = {
                        "type_examen": user_data.get("type_examen"),
                        "serie": user_data.get("serie"),
                        "matiere_fatigue": user_data.get("matiere_fatigue", ""),
                        "genre": user_data.get("genre", ""),
                        "tranche_age": user_data.get("tranche_age", ""),
                        "nom_ecole": user_data.get("nom_ecole", ""),
                        "profil_type": user_data.get("profil_type", ""),
                        "profil_autre": user_data.get("profil_autre", ""),
                    }
                    st.session_state.onboarded = True
                st.rerun()
            else:
                st.error("Remplis ton adresse email et ton prénom !")
        st.markdown("---")
        col_a, col_b, col_c = st.columns(3)
        with col_a:
            st.metric("📚 Documents BAC", "800+")
        with col_b:
            st.metric("🎓 Séries", "Toutes séries")
        with col_c:
            st.metric("📅 Années", "2006-2026")

# ─── ONBOARDING ───────────────────────────────────────
elif not st.session_state.onboarded:
    user = st.session_state.user
    st.markdown(f"<h1 style='color:#1E3A8A;'>🌍 Bienvenue {user['name']} !</h1>", unsafe_allow_html=True)

    # Type d'examen HORS du form pour permettre le rerun immediat
    # (les series/matieres dependent de ce choix)
    type_examen = st.selectbox("🎓 Tu prépares...", ["BEPC", "BAC Général", "BAC Technique"], key="type_examen_choice")

    series_dispo = get_series(type_examen)

    with st.form("onboarding_form"):
        col1, col2 = st.columns(2)
        with col1:
            profil_type = st.selectbox("👤 Qui es-tu ?", ["Élève (Collège/Lycée)", "Étudiant (Université/BTS)", "Professeur", "Parent d'élève", "Autre"])
            profil_autre = ""
            if profil_type == "Autre":
                profil_autre = st.text_input("✏️ Précise ton profil", placeholder="Ex: Formateur, Coach...")
            genre = st.radio("Genre", ["Fille", "Garçon"])
            tranche_age = st.selectbox("🎂 Tranche d'âge", ["14-16 ans", "17-18 ans", "19-21 ans", "22-30 ans", "30 ans et plus"])
        with col2:
            if series_dispo:
                serie = st.selectbox("📚 Ta Série", series_dispo)
            else:
                serie = "BEPC"
                st.write("📚 Série : BEPC (3ème)")
            tentatives = st.number_input("Nombre de tentatives à l'examen", 0, 5)
            nom_ecole = st.text_input("🏫 Nom de ton école/institution", placeholder="Ex: Lycée Moderne de Cocody")
            matieres_dispo = get_matieres(type_examen, serie)
            matiere_fatigue = st.selectbox("La matière qui te fatigue le plus", matieres_dispo)
        if st.form_submit_button("✅ Accéder à Akili"):
            st.session_state.profile = {"type_examen": type_examen, "serie": serie, "matiere_fatigue": matiere_fatigue, "genre": genre, "tranche_age": tranche_age, "nom_ecole": nom_ecole, "profil_type": profil_type, "profil_autre": profil_autre}
            db.collection("users").document(user["email"].strip()).update({
                "type_examen": type_examen,
                "tranche_age": tranche_age,
                "nom_ecole": nom_ecole,
                "genre": genre,
                "serie": serie,
                "tentatives_bac": tentatives,
                "profil_type": profil_type,
                "profil_autre": profil_autre
            })
            st.session_state.onboarded = True
            st.rerun()

# ─── INTERFACE PRINCIPALE ─────────────────────────────
else:
    user = st.session_state.user
    profile = st.session_state.profile
    user_data = get_or_create_user(user["email"], user["name"])
    st.session_state.user_data = user_data
    is_premium = user_data.get("plan") == "premium" or user_data.get("tier") == "PREMIUM"
    restantes = questions_restantes(user_data)

    with st.sidebar:
        st.image("static/logo.png", width=150)
        st.write(f"👋 {user['name']}")
        st.write(f"👤 {profile.get('profil_type', 'Élève')}")
        if profile.get('serie'):
            st.write(f"🎓 Série {profile['serie']}")
        if ACCES_GRATUIT_BAC:
            st.success("🎓 Accès 100% GRATUIT jusqu'au BAC — 15 juin 2026")
        elif is_premium:
            st.success("⭐ Plan Premium")
        else:
            st.info(f"💬 Questions restantes : **{restantes}/{QUESTIONS_GRATUITES}**")
            if restantes == 0:
                st.error("Limite atteinte !")
            st.markdown("---")
            st.markdown("### 🚀 Passe en Premium")
            st.write("✅ Questions illimitées")
            st.write("✅ Scan d'exercices (Vision IA)")
            st.write("✅ Réponses vocales")
            st.write("✅ Historique des conversations")
            st.markdown("**3$/mois ou 2 000 FCFA/mois**")
            if st.button("💳 Stripe (Carte bancaire)", use_container_width=True):
                st.markdown(f"[Payer par carte]({STRIPE_LINK})")
            if st.button("📱 Wave / Orange Money", use_container_width=True):
                try:
                    headers = {"PAYDUNYA-MASTER-KEY": PAYDUNYA_MASTER_KEY, "PAYDUNYA-PRIVATE-KEY": PAYDUNYA_PRIVATE_KEY, "PAYDUNYA-TOKEN": PAYDUNYA_TOKEN, "Content-Type": "application/json"}
                    payload = {"invoice": {"total_amount": 2000, "description": "AfrJigi Premium - 1 mois"}, "store": {"name": "AfrJigi", "website_url": "https://afrjigi.com"}, "actions": {"callback_url": "https://akili-api-598190730734.us-central1.run.app/webhook/paydunya", "return_url": "https://afrjigi.com", "cancel_url": "https://afrjigi.com"}, "custom_data": {"email": user["email"].strip()}}
                    res = requests.post("https://app.paydunya.com/api/v1/checkout-invoice/create", json=payload, headers=headers, timeout=30)
                    if res.status_code == 200:
                        data = res.json()
                        if data.get("response_code") == "00":
                            st.markdown(f"[Payer 2 000 FCFA]({data.get('response_text')})")
                        else:
                            st.error(f"PayDunya refusé : {data.get('response_code')}")
                    else:
                        st.error(f"Erreur PayDunya : {res.status_code}")
                except Exception as e:
                    st.error(f"Erreur : {e}")
        st.divider()
        MATIERE_API_MAP = {
            "Mathématiques": "MATHS",
            "Physique-Chimie": "PC",
            "Physique": "PC",
            "Sciences de la Vie et de la Terre (SVT)": "SVT",
            "SVT": "SVT",
            "Français": "FRANÇAIS",
            "Histoire-Géographie": "HISTOIRE-GEOGRAPHIE",
            "Anglais": "ANGLAIS",
            "Allemand": "ALLEMAND",
            "Espagnol": "ESPAGNOL",
            "Philosophie": "PHILO",
            "Économie": "ECO",
            "Comptabilité": "COMPTA",
            "Mathématiques financières": "MATHS",
            "Droit": "DROIT",
            "Étude de cas": "ETUDE-CAS",
            "Techniques d'organisation": "OC",
            "Outils de communication": "OC",
            "Correspondance commerciale": "OC",
            "ESTI": "ESTI",
            "Électronique": "ELECTRO",
            "Électrotechnique": "ELECTRO",
            "Physique appliquée": "PHY-APP",
            "Mesure": "MESURE",
            "Analyse fonctionnelle": "ANALYSE-FONCT",
        }

        type_examen_actuel = profile.get("type_examen", "BAC Général")
        serie_actuelle = profile.get("serie", "TOUTES")
        matieres_dispo_principal = get_matieres(type_examen_actuel, serie_actuelle)

        matiere_key = f"matiere_principale_{type_examen_actuel}_{serie_actuelle}"
        matiere_actuelle = st.selectbox(
            "📖 Matière",
            matieres_dispo_principal,
            index=0,
            key=matiere_key
        )
        matiere_api = MATIERE_API_MAP.get(matiere_actuelle, matiere_actuelle)

        if "mode_travail" not in st.session_state:
            st.session_state.mode_travail = "etude"
        st.markdown("#### 🎯 Mode de travail")
        col_etude, col_examen = st.columns(2)
        with col_etude:
            if st.button("📘 Mode Étude", use_container_width=True,
                         type="primary" if st.session_state.mode_travail == "etude" else "secondary"):
                st.session_state.mode_travail = "etude"
                st.rerun()
        with col_examen:
            if st.button("🎯 Mode Examen", use_container_width=True,
                         type="primary" if st.session_state.mode_travail == "examen" else "secondary"):
                st.session_state.mode_travail = "examen"
                st.rerun()
        st.divider()

        if st.session_state.get("matiere_courante") != matiere_actuelle:
            st.session_state.messages = load_messages(user["email"].strip(), matiere_actuelle, profile.get("type_examen"))
            st.session_state.matiere_courante = matiere_actuelle
        image_file = None
        st.markdown("---")
        st.markdown("### 📷 Scanner un document")
        option_photo = st.radio("Source :", ["Désactivé", "Prendre une photo", "Importer un fichier"])
        if option_photo == "Prendre une photo":
            image_file = st.camera_input("📸 Photo nette du document")
        elif option_photo == "Importer un fichier":
            image_file = st.file_uploader("Image ou PDF", type=["png", "jpg", "jpeg", "pdf"])
        elif matiere_actuelle == "Philosophie":
            matiere_api = "PHILO"
            st.markdown("---")
            st.markdown("### 💡 Prompts rapides")
            sujet_philo = st.text_input("✏️ Ton sujet", placeholder="Ex: La liberté est-elle une illusion ?", key="sujet_philo")
            if sujet_philo:
                if st.button("📝 Rédiger l'introduction", use_container_width=True):
                    st.session_state.audio_prompt = f"Rédige directement l'introduction complète de la dissertation philosophique sur : '{sujet_philo}'. La TOUTE PREMIÈRE PHRASE doit définir un terme clé du sujet. Ensuite : contextualisation, problématique, annonce du plan. Un seul bloc rédigé."
                if st.button("📝 Développer l'Axe 1", use_container_width=True):
                    st.session_state.audio_prompt = f"Akili, développe le premier axe de ma dissertation sur '{sujet_philo}'. Argument clair, citation d'auteur avec l'œuvre en italique, exemple concret BAC CI."
                if st.button("📝 Développer l'Axe 2", use_container_width=True):
                    st.session_state.audio_prompt = f"Akili, développe le deuxième axe (antithèse) sur '{sujet_philo}'. Argument opposé, citation d'auteur, exemple concret."
                if st.button("✅ Rédiger la conclusion", use_container_width=True):
                    st.session_state.audio_prompt = f"Akili, rédige la conclusion de ma dissertation sur '{sujet_philo}'. Bilan, point de vue personnel : 'Pour notre part, nous disons que...' et une ouverture philosophique."
                if st.button("📄 Rédiger la dissertation complète", use_container_width=True):
                    st.session_state.audio_prompt = f"Akili, rédige la dissertation philosophique COMPLÈTE sur : '{sujet_philo}'. Introduction complète (définitions → problématique → plan), Axe 1 avec argument + citation + exemple, Transition, Axe 2 avec argument + citation + exemple, Conclusion complète avec point de vue personnel. Format BAC CI officiel."
        elif matiere_actuelle == "Français" and profile.get("type_examen") == "BEPC":
            matiere_api = "Français-BEPC-Composition"
            st.markdown("---")
            st.markdown("### 📚 Type de sujet")
            type_fr_bepc = st.radio("", ["Composition Française", "Orthographe / Dictée"], label_visibility="collapsed")
            if type_fr_bepc == "Composition Française":
                matiere_api = "Français-BEPC-Composition"
                st.markdown("### 📋 Prompts rapides")
                sujet_fr_bepc = st.text_input("✏️ Ton sujet", placeholder="Ex: Raconte une expérience qui t'a marqué...", key="sujet_compo_bepc")
                if sujet_fr_bepc:
                    if st.button("📝 Rédiger l'introduction", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, aide-moi à rédiger l'introduction de ma composition sur : '{sujet_fr_bepc}'"
                    if st.button("✍️ Développer mes idées", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, aide-moi à développer mes idées pour la composition sur : '{sujet_fr_bepc}'"
                    if st.button("✅ Rédiger la conclusion", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, aide-moi à rédiger la conclusion de ma composition sur : '{sujet_fr_bepc}'"
            else:
                matiere_api = "Français-BEPC-Orthographe"
                st.markdown("### 📋 Prompts rapides")
                sujet_ortho_bepc = st.text_input("✏️ Ta phrase ou ton exercice", placeholder="Colle la phrase ou l'exercice ici...", key="sujet_ortho_bepc")
                if sujet_ortho_bepc:
                    if st.button("🔍 Vérifier l'orthographe", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, aide-moi a verifier l'orthographe et m'expliquer les regles : '{sujet_ortho_bepc}'"
                    if st.button("📖 Expliquer la règle de grammaire", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, explique-moi la regle de grammaire concernee par : '{sujet_ortho_bepc}'"
        elif matiere_actuelle == "Français":
            st.markdown("---")
            st.markdown("### 📚 Type de sujet")
            type_fr = st.radio("", ["Sujet 1 — QRP", "Sujet 2 — Commentaire Composé", "Sujet 3 — Dissertation Littéraire"], label_visibility="collapsed")
            if type_fr == "Sujet 1 — QRP":
                matiere_api = "Français-QRP"
                st.markdown("### 📋 Prompts rapides")
                sujet_fr = st.text_input("✏️ Ton sujet ou texte", placeholder="Ex: Résume ce texte...", key="sujet_qrp")
                if sujet_fr:
                    if st.button("❓ Rédiger une réponse rédigée", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, aide-moi à rédiger une réponse entièrement rédigée à cette question : '{sujet_fr}'"
                    if st.button("📝 Rédiger le résumé", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, guide-moi pour résumer ce texte (reformulation, 1/4 du texte original) : '{sujet_fr}'"
                    if st.button("✍️ Rédiger la production écrite", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, aide-moi à rédiger la production écrite sur : '{sujet_fr}'. Introduction, développement par axes avec exemples littéraires, conclusion."
                    if st.button("📄 Rédiger le sujet complet QRP", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, rédige le sujet QRP COMPLET sur : '{sujet_fr}'. 1) Réponses rédigées aux questions (sujet+verbe+complément). 2) Résumé reformulé au 1/4 du texte. 3) Production écrite complète avec introduction, développement par axes avec exemples littéraires, conclusion. Format BAC CI officiel."
            elif type_fr == "Sujet 2 — Commentaire Composé":
                matiere_api = "Français-Commentaire"
                st.markdown("### 📋 Prompts rapides")
                sujet_fr = st.text_input("✏️ Colle le texte à commenter", placeholder="Colle l'extrait littéraire ici...", key="sujet_commentaire")
                if sujet_fr:
                    if st.button("🔍 Trouver les Centres d'Intérêt", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, analyse ce texte et propose 2 Centres d'Intérêt pour le commentaire composé, avec l'introduction complète : '{sujet_fr}'"
                    if st.button("📝 Développer un axe", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, développe un paragraphe : Idée → Procédé stylistique (citation) → Analyse → Effet de sens : '{sujet_fr}'"
                    if st.button("✅ Rédiger la conclusion", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, rédige la conclusion du commentaire composé avec bilan des axes et ouverture littéraire : '{sujet_fr}'"
                    if st.button("📄 Rédiger le commentaire complet", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, rédige le commentaire composé COMPLET sur : '{sujet_fr}'. Introduction complète (situation+idée générale+2 centres d'intérêt+annonce plan), Développement des 2 axes (idée+procédé stylistique+citation+analyse+effet), Conclusion avec bilan et ouverture. Format BAC CI officiel."
            else:
                matiere_api = "Français-Dissertation"
                st.markdown("### 📋 Prompts rapides")
                sujet_fr = st.text_input("✏️ La citation ou thèse du sujet", placeholder="Ex: La poésie n'est-elle qu'un jeu avec les mots ?", key="sujet_diss_fr")
                if sujet_fr:
                    if st.button("💬 Rédiger l'introduction", use_container_width=True):
                        st.session_state.audio_prompt = f"Rédige directement l'introduction de la dissertation littéraire sur : '{sujet_fr}'. Ordre : Accroche → Explication de la citation → Problématique → Annonce du plan. Un seul bloc rédigé."
                    if st.button("📝 Développer un axe", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, développe un axe de dissertation littéraire sur '{sujet_fr}' avec argument + 2 exemples d'auteurs africains et occidentaux."
                    if st.button("✅ Rédiger la conclusion", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, rédige la conclusion de la dissertation littéraire sur '{sujet_fr}' avec bilan et ouverture vers un autre débat littéraire."
                    if st.button("📄 Rédiger la dissertation complète", use_container_width=True):
                        st.session_state.audio_prompt = f"Akili, rédige la dissertation littéraire COMPLÈTE sur : '{sujet_fr}'. Introduction (accroche+problématique+plan), Développement (thèse+antithèse+exemples d'auteurs africains et occidentaux), Conclusion avec bilan et ouverture. Format BAC CI officiel."
        elif matiere_actuelle == "Histoire-Géographie":
            matiere_api = "HISTOIRE-GEOGRAPHIE"
            st.markdown("---")
            st.markdown("### 🌍 Type d'exercice")
            sujet_hg = st.text_input("✏️ Ton sujet ou document", placeholder="Ex: La décolonisation de l'Afrique...", key="sujet_hg")
            if sujet_hg:
                if st.button("📜 Dissertation", use_container_width=True):
                    st.session_state.audio_prompt = f"Akili, aide-moi à rédiger une dissertation sur : '{sujet_hg}'. Rédige l'introduction complète (Accroche → Problématique → Annonce du plan), puis propose un plan en 2 ou 3 parties avec faits précis et datés."
                if st.button("📊 Commentaire de document", use_container_width=True):
                    st.session_state.audio_prompt = f"Akili, aide-moi à commenter ce document : '{sujet_hg}'. Guide-moi sur l'introduction (nature, auteur, date, idée générale), l'explication avec mes connaissances, et la portée."
                if st.button("🎯 Situation d'évaluation", use_container_width=True):
                    st.session_state.audio_prompt = f"Akili, voici ma situation d'évaluation : '{sujet_hg}'. Guide-moi pour traiter chaque tâche de manière distincte et entièrement rédigée."
                if st.button("📄 Traiter le sujet complet", use_container_width=True):
                    st.session_state.audio_prompt = f"Akili, traite ce sujet d'Histoire-Géographie COMPLET : '{sujet_hg}'. Introduction complète (accroche+problématique+annonce plan), Développement en 2 ou 3 parties avec faits précis et datés, Transitions entre les parties, Conclusion avec bilan et ouverture. Format BAC CI officiel."
        elif matiere_actuelle == "Anglais":
            matiere_api = "ANGLAIS-ORAL"
        st.markdown("---")
        # audio recorder deplace dans la zone principale
        st.markdown("---")
        type_examen_actuel = profile.get("type_examen", "BAC Général") if profile else "BAC Général"
        est_bepc = type_examen_actuel == "BEPC"
        nom_examen = "BEPC" if est_bepc else "BAC"
        date_examen = date(2027, 6, 5) if est_bepc else date(2027, 6, 15)
        serie_ou_niveau = "3ème" if est_bepc else profile.get("serie", "A") if profile else "A"
        mention_serie = "Je suis en classe de 3ème." if est_bepc else f"Je suis en Série {serie_ou_niveau}."

        st.markdown(f"### 📅 Planning {nom_examen}")
        jours_restants = (date_examen - date.today()).days
        st.info(f"⏰ **{jours_restants} jours** avant le {nom_examen} !")
        if st.button(f"📅 Générer mon Planning de révision", use_container_width=True, key="btn_planning"):
            NOMS_MATIERES = {
                "MATHS": "Mathématiques", "PC": "Physique-Chimie", "SVT": "SVT",
                "FRENCH": "Français", "HG": "Histoire-Géographie", "PHILO": "Philosophie",
                "ANGLAIS": "Anglais", "ALLEMAND": "Allemand", "ESPAGNOL": "Espagnol",
                "ARTS": "Arts Plastiques", "EPS": "EPS", "CONDUITE": "Conduite",
                "ECO": "Économie", "COMPTA": "Comptabilité", "EDHC": "EDHC",
            }
            niveau_coeff = "3EME" if est_bepc else "TERMINALE"
            coeffs = coefficients.get_toutes_matieres_serie(serie_ou_niveau, niveau_coeff)
            lignes_coeff = []
            for code_m, coef_m in coeffs.items():
                nom_m = NOMS_MATIERES.get(code_m, code_m)
                lignes_coeff.append("- " + nom_m + " : coefficient " + str(coef_m))
            bloc_coeff = "\n".join(lignes_coeff)
            planning_prompt = (
                f"Crée-moi un planning de révision personnalisé et détaillé pour les {jours_restants} jours "
                f"qui restent avant le {nom_examen} CI du {date_examen.strftime('%d/%m/%Y')}. {mention_serie}\n\n"
                f"COEFFICIENTS OFFICIELS (source DPFC, Ministere de l'Education Nationale de Cote d'Ivoire) "
                f"pour ma serie. Utilise EXCLUSIVEMENT ces coefficients, ne les invente pas :\n{bloc_coeff}\n\n"
                f"Organise les matieres en priorisant celles a fort coefficient, en tenant compte aussi de leur difficulte. "
                f"Présente le planning jour par jour avec : la matière du jour, les thèmes prioritaires à réviser, "
                f"et un conseil de méthode. Termine par 3 conseils essentiels pour la semaine du {nom_examen}."
            )
            st.session_state.audio_prompt = planning_prompt
        st.markdown("---")
        st.markdown(f"### 🎯 Quiz {nom_examen}")
        if st.button(f"🎯 Générer un Quiz type {nom_examen}", use_container_width=True, key="btn_quiz"):
            quiz_prompt = (
                f"Génère 5 questions d'entraînement type {nom_examen} en {matiere_actuelle} "
                f"pour un élève {'de 3ème' if est_bepc else 'de Série ' + serie_ou_niveau}. "
                f"Pour chaque question : numérote-la, énonce-la clairement, "
                f"puis donne le corrigé complet attendu par le correcteur du {nom_examen} CI. "
                f"Sois précis, rigoureux et utilise le format officiel ivoirien."
            )
            st.session_state.audio_prompt = quiz_prompt
        st.divider()
        if st.button("🗑️ Effacer l'historique", use_container_width=True):
            clear_messages(user["email"])
            st.session_state.messages = []
            st.rerun()
        if st.button("🔄 Modifier mon profil"):
            st.session_state.onboarded = False

            
            st.session_state.profile = {}
            st.rerun()
        st.markdown("---")
        st.markdown("### 🌍 Rejoins la communauté AfrJigi")
        st.markdown(
            "[📘 Facebook](https://facebook.com/afrjigi) · "
            "[📷 Instagram](https://instagram.com/afrjigi_officiel) · "
            "[🎵 TikTok](https://tiktok.com/@afrjigi)"
        )
        st.caption("Suis-nous pour des astuces BAC, des conseils de révision et les nouveautés !")
        if st.button("🚪 Déconnexion"):
            st.session_state.user = None
            st.session_state.user_data = None
            st.session_state.onboarded = False
            st.session_state.messages = []
            st.rerun()

    # ─── ZONE PRINCIPALE ──────────────────────────────
    st.markdown("<h1 style='color:#1E3A8A;'>🌍 AfrJigi — Akili</h1>", unsafe_allow_html=True)

    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg["role"] == "assistant" and "audio" in msg:
                st.audio(msg["audio"], format="audio/mp3")

    user_input = None
    if st.session_state.audio_prompt:
        user_input = st.session_state.audio_prompt
        st.session_state.audio_prompt = None

    # ── Enregistreur vocal ──
    with st.expander("🎤 Message vocal — Parle à Akili"):
        audio_data = st.audio_input("Enregistre ton message")
        if st.button("📤 Envoyer l'audio", use_container_width=True):
            if audio_data is not None:
                with st.spinner("Transcription en cours..."):
                    try:
                        res_tr = requests.post(TRANSCRIBE_URL, files={"file": ("audio.webm", audio_data.getvalue(), "audio/webm")}, timeout=60)
                        if res_tr.status_code == 200:
                            transcription = res_tr.json().get("transcript", "")
                            if transcription:
                                st.session_state.audio_prompt = transcription
                                st.rerun()
                            else:
                                st.warning("Transcription vide. Réessaie.")
                        else:
                            st.error(f"Erreur {res_tr.status_code}")
                    except Exception as e:
                        st.error(f"Erreur : {e}")
            else:
                st.warning("Enregistre d'abord un message.")

    prompt = user_input or st.chat_input("Pose ta question à Akili ou décris ton exercice...")

    if prompt:
        if not can_ask_question(user_data):
            st.error("🚫 Tu as atteint ta limite de 5 questions gratuites aujourd'hui. Passe en Premium !")
        else:
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)
                if image_file:
                    if hasattr(image_file, "name") and image_file.name.lower().endswith(".pdf"):
                        st.info(f"📄 PDF joint : {image_file.name}")
                    else:
                        st.image(image_file, caption="Image envoyée à Akili", width=300)
            with st.chat_message("assistant"):
                try:
                    clean_email = user["email"].strip()
                    history_to_send = [
                        {"role": m["role"], "content": m["content"]}
                        for m in st.session_state.messages[-8:]
                        if m["role"] in ["user", "assistant"]
                    ]
                    form_data = {
                        "question": prompt,
                        "email": clean_email,
                        "matiere": matiere_api,
                        "serie": profile["serie"],
                        "type_examen": profile.get("type_examen", "BAC Général"),
                        "mode": st.session_state.get("mode_travail", "etude"),
                        "history": json.dumps(history_to_send)
                    }
                    files = None
                    if image_file is not None:
                        image_file.seek(0)
                        files = {"file": (image_file.name, image_file.read(), image_file.type)}
                    with st.spinner("Akili analyse... 🤔"):
                        res = requests.post(AKILI_API_URL, data=form_data, files=files, timeout=120)
                        reponse = res.json().get("reponse", "Désolé, je n'ai pas pu générer de réponse.")
                    def _stream():
                        for mot in reponse.split():
                            yield mot + " "
                            time.sleep(0.02)
                    st.write_stream(_stream())
                    save_message(clean_email, "user", prompt, matiere_actuelle, profile.get("type_examen"))
                    save_message(clean_email, "assistant", reponse, matiere_actuelle, profile.get("type_examen"))
                    audio_bytes = None
                    try:
                        texte_propre = reponse.replace("**", "").replace("$$", "").replace("$", "")
                        tts = gTTS(text=texte_propre[:1000], lang="fr", slow=False)
                        audio_buffer = io.BytesIO()
                        tts.write_to_fp(audio_buffer)
                        audio_bytes = audio_buffer.getvalue()
                        st.audio(audio_bytes, format="audio/mp3")
                    except Exception as audio_err:
                        print(f"Erreur Audio : {audio_err}")
                    msg_payload = {"role": "assistant", "content": reponse}
                    if audio_bytes:
                        msg_payload["audio"] = audio_bytes
                    st.session_state.messages.append(msg_payload)
                    increment_questions(clean_email)
                    st.session_state.user_data = get_or_create_user(clean_email, user["name"])
                    st.rerun()
                except Exception as e:
                    st.error(f"Erreur réseau : {e}")
