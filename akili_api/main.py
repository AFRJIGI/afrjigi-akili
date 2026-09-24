import json
import os
from datetime import datetime, date
import vertexai
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google.cloud import storage, firestore
from vertexai.generative_models import GenerativeModel, Part
from typing import Optional
from PIL import Image
import io

# Configuration
PROJECT_ID = "astute-curve-307922"
LOCATION   = "us-central1"
BUCKET_NAME = "akili-database-storage-astute-curve-307922"
BLOB_NAME   = "data/jigi_global_database.json"

# Initialisation Vertex AI
vertexai.init(project=PROJECT_ID, location=LOCATION)
model = GenerativeModel("gemini-2.5-flash")

# Initialisation de Firestore (Sécurisée via IAM - pas besoin de clé JSON)
db = firestore.Client()

def load_db_from_gcs():
    """Charge la base de données depuis Google Cloud Storage."""
    try:
        print(f"⏳ Chargement de la base depuis gs://{BUCKET_NAME}/{BLOB_NAME}...")
        client = storage.Client()
        bucket = client.bucket(BUCKET_NAME)
        blob = bucket.blob(BLOB_NAME)

        content = blob.download_as_text()
        data = json.loads(content)

        docs = []
        for d in data.get("documents", []):
            texte = d.get("texte") or d.get("texte_extrait") or d.get("resume") or ""
            if isinstance(texte, list):
                texte = " ".join(str(x) for x in texte)
            texte = str(texte).strip()
            if texte:
                d["texte"] = texte
                docs.append(d)

        print(f"✅ {len(docs)} documents chargés avec succès.")
        return docs
    except Exception as e:
        print(f"❌ Erreur lors du chargement GCS : {e}")
        return []

# Chargement global au démarrage
documents = load_db_from_gcs()


PROMPT_HIST_GEO = """Tu es Akili, un professeur d'Histoire-Géographie expert du niveau Terminale pour le BAC en Côte d'Ivoire. Ton rôle est de guider méthodologiquement l'élève pour réussir la Dissertation, le Commentaire de documents et la Situation d'Évaluation selon le barème officiel ivoirien.

Tu dois appliquer et imposer STRICTEMENT les règles suivantes :

1. POUR LA DISSERTATION :
- INTRODUCTION : Un seul bloc fluide. Ordre : Accroche (cadre historique/géographique) -> Problématique -> Annonce du plan.
- DÉVELOPPEMENT : 2 ou 3 grandes parties. Chaque argument soutenu par des faits précis et datés (Histoire) ou chiffrés (Géographie). Transitions obligatoires entre les parties.
- CONCLUSION : Bilan concis répondant à la problématique + ouverture logique.

2. POUR LE COMMENTAIRE DE DOCUMENTS :
- Combat la paraphrase : interdiction de recopier le texte ou les chiffres sans analyse.
- INTRODUCTION : Nature du document, Auteur, Date, Idée générale.
- EXPLICATION : Citer brièvement le passage PUIS l'expliquer avec les connaissances du cours.
- PORTÉE : Dégager l'intérêt ou l'impact global du document.

3. POUR LA SITUATION D'ÉVALUATION :
- Les consignes (tâches 1, 2, 3) doivent être traitées de manière distincte et entièrement rédigée. Les listes à puces sans développement font perdre la majorité des points.
- Lier les indices de la situation aux faits historiques ou géographiques du programme ivoirien.

Adopte un ton rigoureux sur les faits et la chronologie, bienveillant et motivant pour propulser l'élève vers la mention.
"""

PROMPT_HIST_GEO_BEPC = """Tu es Akili, un professeur d'Histoire-Géographie expert du niveau 3ème pour le BEPC en Côte d'Ivoire. Ton rôle est de guider méthodologiquement l'élève pour réussir l'épreuve BEPC (questions de cours, exploitation de documents comme cartes/textes/statistiques, croquis simples).

Tu dois appliquer et imposer STRICTEMENT les règles suivantes :
1. QUESTIONS DE COURS :
- Exige des réponses ENTIÈREMENT RÉDIGÉES (phrase complète, sujet + verbe + complément), jamais de mots isolés.
- Vérifie que les dates, lieux et faits cités sont exacts et précis.
2. EXPLOITATION DE DOCUMENT (carte, texte, tableau statistique) :
- Étape 1 : identifier la nature et le thème du document.
- Étape 2 : relever les informations demandées SANS recopier tout le texte.
- Étape 3 : expliquer avec les connaissances du cours (le document seul ne suffit jamais).
3. CROQUIS / SCHÉMA (si demandé) :
- Rappelle les éléments obligatoires : titre, légende, orientation, échelle si pertinent.
- Guide sur le choix des figurés (couleurs, symboles) sans dessiner à la place de l'élève.

Adopte un ton simple, clair et encourageant, adapté à un élève de 3ème. Évite le vocabulaire complexe du lycée. Valorise chaque effort de rédaction complète."""

PROMPT_FR_BEPC_COMPO = """Tu es Akili, professeur expert de Français niveau 3ème pour le BEPC en Côte d'Ivoire. Tu guides l'élève sur la Composition Française (rédaction), notée sur 20 points.

STRUCTURE ATTENDUE :
INTRODUCTION (courte) : présente le sujet et annonce ce que tu vas raconter/expliquer.
DÉVELOPPEMENT : idées organisées en paragraphes clairs, chacun avec une idée principale + des détails/exemples concrets tirés de la vie courante ou de tes lectures.
CONCLUSION (courte) : un bref bilan, éventuellement un avis personnel.

RÈGLES :
- Exige des phrases complètes, correctement construites (sujet + verbe + complément).
- Corrige la ponctuation, les temps verbaux et les répétitions inutiles.
- Encourage un vocabulaire simple mais précis, adapté au niveau 3ème.
- Ne rédige JAMAIS la composition à la place de l'élève — guide-le paragraphe par paragraphe.

POSTURE : Bienveillant, patient, encourageant. Valorise chaque effort de structuration."""

PROMPT_FR_BEPC_ORTHO = """Tu es Akili, professeur expert de Français niveau 3ème pour le BEPC en Côte d'Ivoire. Tu guides l'élève sur l'épreuve d'Orthographe (dictée + exercices de langue : grammaire, conjugaison, vocabulaire), notée sur 20 points.

TA MÉTHODE :
1. Pour une dictée : rappelle les pièges classiques (accords sujet-verbe, participes passés, homophones comme a/à, on/ont, ou/où).
2. Pour un exercice de conjugaison/grammaire : demande à l'élève d'essayer d'abord, puis corrige en expliquant la RÈGLE (pas juste la bonne réponse).
3. Pour le vocabulaire : explique le sens d'un mot avec un exemple simple, puis fais-le réemployer dans une phrase par l'élève.

RÈGLES :
- Ne donne JAMAIS directement la correction complète sans que l'élève ait essayé.
- Explique toujours la règle grammaticale derrière chaque erreur.
- Reste concis : les élèves de 3ème lisent peu, va à l'essentiel.

POSTURE : Patient, pédagogue, rassurant face aux fautes (elles font partie de l'apprentissage)."""
app = FastAPI(title="Akili API", version="1.0")

# --- CONFIGURATION CORS (Pour corriger l'Erreur Réseau) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import re
from coefficients import get_toutes_matieres_serie

def serie_match(serie_doc, serie_eleve):
    """Un eleve de serie simple (A1/A2/C/D/E/BEPC) matche un libelle compose."""
    s_doc = (serie_doc or "").upper().strip()
    s_el  = (serie_eleve or "").upper().strip()
    if s_el == "BEPC":                     return s_doc == "BEPC"
    if s_doc == "BEPC":                    return False
    if not s_doc or s_doc == "TOUTES":     return True   # BAC toutes series
    if s_doc == s_el:                      return True
    if s_el in ("A1", "A2"):
        if s_el in s_doc:                  return True   # A1, A2, A1A2, A2A1
        if re.search(r"A(?![12])", s_doc): return True   # A nu : ABCD, AEH...
        return False
    if s_el in ("C", "D", "E"):
        return s_el in s_doc
    if s_el == "B":
        return "B" in s_doc
    if s_el in ("G1", "G2"):
        return s_el in s_doc
    if s_el in ("F1", "F2", "F3", "F4"):
        if s_el in s_doc: return True
        if s_doc == "F":  return True
        return False
    return False


ETUDE_TYPES = {
    "PROGRAMME": 40,
    "PROGRESSION_ANNUELLE": 38,
    "PROGRESSION_2NDE": 38,
    "PROGRESSION_1ERE": 38,
    "PROGRESSION_TLE": 38,
    "GUIDE": 35,
    "DOCUMENT": 25,
    "DOCUMENT_ACCOMPAGNEMENT": 30,
    "TP": 25,
    "ANNALE": 10,
    "SUJET": 8,
    "CORRIGE": 6,
    "CORRIGÉ": 6,
    "BAC_BLANC": 6,
    "PREPA": 6,
    "TERMINALE": 5,
}

EXAMEN_TYPES = {
    "SUJET": 40,
    "ANNALE": 38,
    "BAC_BLANC": 36,
    "PREPA": 34,
    "TERMINALE": 32,
    "DOCUMENT": 28,
    "CORRIGE": 24,
    "CORRIGÉ": 24,
    "BARÈME": 22,
    "BAREME": 22,
    "SUJET CORRIGÉ": 22,
    "PROGRAMME": 5,
    "PROGRESSION_ANNUELLE": 5,
    "DOCUMENT_ACCOMPAGNEMENT": 4,
    "PROGRESSION_2NDE": 5,
    "PROGRESSION_1ERE": 5,
    "PROGRESSION_TLE": 5,
    "GUIDE": 4,
}

def normaliser_mode(mode, question=""):
    txt = f"{mode or ''} {question or ''}".lower()
    if any(x in txt for x in ["mode examen", "examen", "sujet type", "sujet d'examen", "entraîne", "entrainer", "corrige-moi", "note-moi", "barème", "bareme"]):
        return "examen"
    return "etude"

def normaliser_examen_requete(type_examen=None, serie=None):
    raw = f"{type_examen or ''} {serie or ''}".upper()
    s = (serie or "").upper().strip()

    if "BEPC" in raw or s == "BEPC":
        return "BEPC"

    if (
        "TECH" in raw
        or s in {"B", "G1", "G2", "G1G2", "BG1", "BG2", "BG1G2", "F", "F1", "F2", "F3", "F4", "STI"}
    ):
        return "BAC_TECHNIQUE"

    return "BAC_GENERAL"


def question_demande_coefficients(question):
    q = (question or "").lower()
    mots = [
        "coefficient", "coefficients", "prioriser", "priorité", "priorite",
        "matière importante", "matières importantes", "planning", "plan de révision",
        "plan de revision", "organiser mes révisions", "organiser mes revisions",
        "moyenne", "viser", "stratégie", "strategie"
    ]
    return any(m in q for m in mots)


def contexte_coefficients_officiels(question, serie, type_examen):
    if not question_demande_coefficients(question):
        return ""

    examen = normaliser_examen_requete(type_examen, serie)
    if examen != "BAC_GENERAL":
        return (
            "COEFFICIENTS OFFICIELS DPFC : Le document de coefficients actuellement structuré "
            "couvre le secondaire général (BEPC et BAC Général). Il ne couvre pas le BAC Technique. "
            "Pour le BAC Technique, ne donne pas de coefficients si tu n'as pas une source officielle dédiée."
        )

    coeffs = get_toutes_matieres_serie(serie, "TERMINALE")
    if not coeffs:
        return ""

    labels = {
        "FRENCH": "Français",
        "MATHS": "Mathématiques",
        "PC": "Physique-Chimie",
        "SVT": "SVT",
        "HG": "Histoire-Géographie",
        "PHILO": "Philosophie",
        "ANGLAIS": "Anglais",
        "ALLEMAND": "Allemand",
        "ESPAGNOL": "Espagnol",
        "EPS": "EPS",
        "ARTS": "Arts Plastiques / Éducation Musicale",
        "EDHC": "EDHC",
        "CONDUITE": "Conduite",
    }

    lignes = []
    for mat, coef in coeffs.items():
        lignes.append(f"- {labels.get(mat, mat)} : coefficient {coef}")

    return (
        "COEFFICIENTS OFFICIELS DPFC STRUCTURÉS "
        "(source : DPFC, Coefficients du 1er et du 2nd cycles de l'enseignement secondaire général, année scolaire 2024-2025). "
        "Utilise ces coefficients comme source prioritaire et ne les modifie pas. "
        f"Série demandée : {serie} / niveau Terminale.\n"
        + "\n".join(lignes)
    )


def type_priority(type_doc, mode):
    t = (type_doc or "").upper().strip()
    table = EXAMEN_TYPES if mode == "examen" else ETUDE_TYPES
    return table.get(t, 0)


def progression_priority(question, doc):
    """Favorise une progression demandee explicitement, surtout sa version exacte."""
    q = (question or "").lower()
    if not any(term in q for term in ["progression", "repartition annuelle", "répartition annuelle"]):
        return 0

    type_doc = (doc.get("type_doc") or "").upper().strip()
    if type_doc == "PROGRESSION_ANNUELLE":
        score = 120
    elif type_doc.startswith("PROGRESSION_"):
        score = 90
    else:
        return 0

    version = str(doc.get("version") or doc.get("annee") or "").lower()
    requested_versions = re.findall(r"\b20\d{2}(?:\s*[-–/]\s*20\d{2})?\b", q)
    if requested_versions:
        normalized_version = re.sub(r"\s+", "", version).replace("–", "-").replace("/", "-")
        if any(
            re.sub(r"\s+", "", item).replace("–", "-").replace("/", "-") == normalized_version
            for item in requested_versions
        ):
            score += 60

    return score

def chercher_contexte(question, matiere=None, serie=None, examen=None, mode="etude", max_docs=5):
    """Filtre les documents par examen/matière/série et recherche par mots-clés."""
    if not documents or not question:
        return []

    mode = normaliser_mode(mode, question)
    filtered_docs = documents

    if examen:
        filtered_docs = [
            d for d in filtered_docs
            if (d.get("examen") or "").upper().strip() in {examen, "TOUS"}
        ]

    if matiere:
        filtered_docs = [d for d in filtered_docs if (d.get("matiere") or "").upper().strip() == matiere]

    if serie:
        filtered_docs = [d for d in filtered_docs if serie_match(d.get("serie"), serie)]

    mots_cles = [m.lower() for m in re.findall(r"\w+", question) if len(m) > 3]

    results = []
    for doc in filtered_docs:
        texte_brut = doc.get("texte", "")
        if isinstance(texte_brut, list):
            texte_brut = " ".join(str(x) for x in texte_brut)
        texte = str(texte_brut).lower()

        keyword_score = sum(1 for mot in mots_cles if mot in texte)
        meta_text = " ".join(str(doc.get(k, "")) for k in ["nom_fichier", "matiere", "serie", "type_doc", "annee"]).lower()
        meta_score = sum(1 for mot in mots_cles if mot in meta_text)

        if keyword_score > 0 or meta_score > 0:
            score = (
                (keyword_score * 10)
                + (meta_score * 4)
                + type_priority(doc.get("type_doc"), mode)
                + progression_priority(question, doc)
            )
            results.append((score, doc))

    results.sort(key=lambda x: x[0], reverse=True)
    return [doc for score, doc in results[:max_docs]]

def instructions_mode(mode, examen):
    if mode == "examen":
        return f"""
MODE EXAMEN ACTIVE.
- Mets l'élève en situation de {examen}.
- Priorise les sujets, annales, bac blanc, prépa, corrigés et barèmes.
- Ne donne pas toute la correction immédiatement si l'élève n'a pas encore essayé.
- Propose une question ou un exercice, puis attends sa tentative.
- Après sa réponse, corrige avec méthode, erreurs, points forts et barème indicatif.
"""
    return f"""
MODE ETUDE ACTIVE.
- Aide l'élève à comprendre progressivement pour le {examen}.
- Priorise programmes, progressions, guides, TP et documents pédagogiques.
- Si la question contient programme, chapitre, cours, notion, comprendre, réviser ou progression :
  1. Utilise directement le CONTEXTE OFFICIEL disponible.
  2. Donne les grands chapitres ou compétences visibles dans ce contexte.
  3. Organise la réponse par niveau, thème ou chapitre si possible.
  4. Ne réponds pas seulement par une question générale.
- Explique en étapes courtes.
- Ne fais pas un cours complet sauf demande explicite.
- Termine par une petite question ou une action simple pour continuer.
"""


@app.post("/question")
async def ask_question(
    question: Optional[str] = Form(None),
    email: str = Form(...),
    matiere: Optional[str] = Form(None),
    serie: Optional[str] = Form(None),
    type_examen: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    mode_oral: Optional[str] = Form(None),
    history: Optional[str] = Form(None),
    mode: Optional[str] = Form("etude")
):
    try:
        if not email:
            return {"error": "L'adresse email est requise pour poser une question."}

        # .strip() permet de nettoyer l'email s'il y a un espace caché au début ou à la fin
        clean_email = email.strip()

        # ─── 1. VÉRIFICATION DU QUOTA DANS FIRESTORE ───
        user_ref = db.collection("users").document(clean_email)
        user_doc = user_ref.get()
        
        today_str = str(date.today())
        is_premium = False
        questions_today = 0

        if user_doc.exists:
            user_data = user_doc.to_dict()
            
            # Alignement avec tes clés existantes : "plan" et "tier"
            statut_plan = user_data.get("plan", "gratuit").lower()
            statut_tier = user_data.get("tier", "FREE").upper()
            
            if statut_plan == "premium" or statut_tier == "PREMIUM":
                is_premium = True
            
            # Alignement avec ta clé de date : last_question_date
            last_q_date = user_data.get("last_question_date", today_str)
            
            if last_q_date == today_str:
                questions_today = user_data.get("questions_today", 0)
            else:
                questions_today = 0
        else:
            # Si l'utilisateur n'existe pas encore dans Firestore, on l'initialise
            user_ref.set({
                "email": clean_email,
                "plan": "gratuit",
                "questions_today": 0,
                "last_question_date": today_str,
                "created_at": datetime.utcnow().isoformat(),
                "matiere": matiere,
                "serie": serie
            })

        # ─── 2. BLOCAGE DU COMPTE GRATUIT SI LIMITE ATTEINTE ───
        # BAC 2026 - Gratuit pour tous
        is_premium = True  # Limite désactivée jusqu'au BAC
        if False and not is_premium and questions_today >= 5:
            return {
                "reponse": "🛑 Tu as atteint ta limite de 5 questions gratuites pour aujourd'hui ! Pour poser des questions en illimité à Akili et réussir ton BAC, rejoins le club Premium d'AfrJigi pour seulement 2 000 FCFA.",
                "sources": [],
                "limit_reached": True
            }

        # ─── 3. SÉLECTION DU PROMPT ET RECHERCHE CONTEXTE ───
        # Normalisation matiere : libelle frontend -> code court du registre
        MAP_MATIERE = {
            "PHYSIQUE-CHIMIE": "PC", "PHYSIQUE": "PC",
            "MATHÉMATIQUES": "MATHS", "MATHEMATIQUES": "MATHS",
            "SCIENCES DE LA VIE ET DE LA TERRE (SVT)": "SVT", "SVT": "SVT",
            "HISTOIRE-GEOGRAPHIE": "HG", "HISTOIRE-GÉOGRAPHIE": "HG",
            "ANGLAIS-ORAL": "ANGLAIS", "ANGLAIS": "ANGLAIS",
            "ALLEMAND": "ALLEMAND", "ESPAGNOL": "ESPAGNOL",
            "PHILO": "PHILO", "PHILOSOPHIE": "PHILO",
            "FRANÇAIS-QRP": "FRENCH", "FRANÇAIS-COMMENTAIRE": "FRENCH",
            "FRANÇAIS-DISSERTATION": "FRENCH", "FRANÇAIS": "FRENCH", "FRANCAIS": "FRENCH",
            "FRANÇAIS-BEPC-COMPOSITION": "FRENCH", "FRANÇAIS-BEPC-ORTHOGRAPHE": "FRENCH",
        }
        matiere_registre = MAP_MATIERE.get((matiere or "").strip().upper(), matiere)
        if matiere_registre:
            matiere_registre = matiere_registre.strip().upper()

        examen_registre = normaliser_examen_requete(type_examen, serie)
        mode_registre = normaliser_mode(mode, question)

        contexte_docs = chercher_contexte(
            question,
            matiere=matiere_registre,
            serie=serie,
            examen=examen_registre,
            mode=mode_registre,
            max_docs=6
        ) if question else []

        contexte_texte = "\n\n".join([str(d.get('texte', ''))[:3500] for d in contexte_docs])
        
        matiere_propre = matiere.strip().upper() if matiere else ""
        
        if matiere_propre == "PHILO":
            system_prompt = """Tu es Akili, tuteur pédagogique de philosophie pour le BAC de Côte d'Ivoire. Tu fonctionnes comme un TUTORIEL INTERACTIF — tu guides l'élève étape par étape sans jamais rédiger à sa place.

TON APPROCHE TUTORIELLE EN 3 ÉTAPES :

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ÉTAPE 1 — ÉTUDE PARCELLAIRE DU SUJET
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quand l'élève donne un sujet, tu commences TOUJOURS par l'étude parcellaire :
1. Décompose chaque mot/notion clé du sujet
2. Donne 2-3 possibilités de définitions pour chaque notion
3. Identifie les tensions et contradictions entre les notions
4. Propose 2-3 possibilités de paradoxes
5. Propose 2-3 possibilités de problématiques
6. DIS À L'ÉLÈVE : "Choisis la problématique qui te semble la plus pertinente et rédige ton introduction."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ÉTAPE 2 — PLAN DÉTAILLÉ ET ARGUMENTS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quand l'élève a rédigé son introduction, tu lui proposes :
1. Un plan en 2 axes (AXE 1 et AXE 2)
2. Pour chaque axe : 3 arguments possibles avec auteurs et citations
3. L'élève CHOISIT et ORDONNE les arguments qui lui conviennent
4. DIS À L'ÉLÈVE : "Sélectionne 2 arguments par axe et rédige ton développement."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ÉTAPE 3 — GUIDE POUR LA CONCLUSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Quand l'élève a rédigé son développement, tu lui donnes :
1. La structure de la conclusion (bilan + point de vue personnel + ouverture)
2. Des pistes pour le bilan selon sa problématique
3. DIS À L'ÉLÈVE : "Rédige maintenant ta conclusion avec tes propres mots."

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
RÈGLES ABSOLUES :
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
- Ne JAMAIS rédiger l'introduction, le développement ou la conclusion à la place de l'élève
- Toujours proposer des OPTIONS et laisser l'élève CHOISIR
- Encourager et valoriser les efforts de l'élève
- Corriger et noter les productions de l'élève quand il les soumet
- Terminer chaque réponse par une question ou une invitation à agir
- Format BAC CI officiel : JAMAIS de plan en 3 parties
"""
        elif matiere_propre in ["MATHS", "PC", "PHYSIQUE", "PHYSIQUE-CHIMIE"]:
            niveau_examen = (type_examen or "BAC Général").strip()
            if niveau_examen == "BEPC":
                niveau_texte = "BEPC (3ème)"
            else:
                niveau_texte = "BAC (" + niveau_examen + ")"
            system_prompt = """Tu es Akili, professeur de Mathématiques et Physique-Chimie pour le NIVEAU_PLACEHOLDER de Côte d'Ivoire. Tu GUIDES l'élève pas à pas — tu ne résous JAMAIS l'exercice entièrement à sa place. L'élève doit participer à chaque étape.

NIVEAU DE L'ÉLÈVE : l'élève prépare le NIVEAU_PLACEHOLDER. Ne mentionne JAMAIS un autre niveau (par exemple ne parle pas du "BAC" a un eleve du BEPC, ni du "BEPC" a un eleve du BAC).

RESPECT DU PROGRAMME OFFICIEL :
- Appuie-toi STRICTEMENT sur le programme officiel ivoirien et les sujets officiels fournis dans le contexte.
- N'introduis JAMAIS une notion, une formule ou une méthode hors du programme ivoirien de la classe concernée.
- Utilise la méthodologie et l'ordre de résolution attendus par le programme officiel.

TA MÉTHODE TUTORIELLE :
1. Transcris brièvement l'énoncé pour confirmer la bonne lecture.
2. Quand tu as besoin qu'il choisisse une formule, une loi ou une méthode, ne lui demande JAMAIS de la TAPER lui-même (la saisie de formules au clavier est très difficile sur smartphone Android, ce qui décourage 90% des élèves). Propose-lui à la place un CHOIX NUMÉROTÉ de 2 à 4 formules/méthodes possibles, écrites en LaTeX, et demande-lui de répondre simplement par la lettre (a, b, c...). Une seule est correcte (ou plusieurs selon le cas). ATTENDS son choix. Exemple : "Quelle équation horaire utiliserais-tu ? (a) $S(t)=v_0 t+S_0$  (b) $S(t)=\frac{1}{2}at^2+v_0 t+S_0$  (c) $S(t)=\frac{1}{2}at^2$. Réponds par a, b ou c." Après son choix, demande-lui BRIÈVEMENT pourquoi ce choix, pour qu'il réfléchisse au lieu de deviner.
3. Selon sa réponse : valide, corrige ou complète, puis oriente vers l'étape suivante.
4. Fais-le avancer étape par étape, en lui demandant de faire les calculs lui-même ("calcule ceci et dis-moi ce que tu trouves").
5. Ne donne la solution complète qu'en DERNIER recours, si l'élève est vraiment bloqué après plusieurs indices.

CONCISION (important) :
- Pour une question DIRECTE (donner une nature de mouvement, une définition, une valeur), réponds de façon COURTE et précise. Pas de longs développements.
- Garde les explications détaillées pour les points réellement difficiles.
- Les élèves lisent peu : va à l'essentiel.

FORMATAGE : Utilise le LaTeX ($inline$ ou $$display$$) pour TOUTES les expressions mathématiques, fractions, puissances et racines, pour un rendu lisible sur smartphone."""
            system_prompt = system_prompt.replace("NIVEAU_PLACEHOLDER", niveau_texte)
        elif matiere_propre == "FRANÇAIS-BEPC-COMPOSITION":
            system_prompt = PROMPT_FR_BEPC_COMPO
        elif matiere_propre == "FRANÇAIS-BEPC-ORTHOGRAPHE":
            system_prompt = PROMPT_FR_BEPC_ORTHO
        elif matiere_propre == "FRANÇAIS-QRP":
            system_prompt = """Tu es Akili, professeur expert de Français Terminale pour le BAC de Côte d'Ivoire (Séries A, B, C, D, E, H). Tu guides l'élève sur le Sujet 1 : Questions - Résumé - Production Écrite (QRP), épreuve de 4 heures notée sur 20 points.

BARÈME OFFICIEL :
- Questions : 04 points | Résumé de texte : 08 points | Production écrite : 08 points

1. QUESTIONS (04 pts) :
- Exige des réponses ENTIÈREMENT RÉDIGÉES avec sujet + verbe + complément.
- Sanctionne le style télégraphique : "Cette réponse serait pénalisée au BAC car non rédigée."

2. RÉSUMÉ DE TEXTE (08 pts) :
- Méthode : analyse PARAGRAPHE PAR PARAGRAPHE pour dégager la visée argumentative de l'auteur.
- Règle absolue : REFORMULATION TOTALE obligatoire. Rappelle : "Toute phrase copiée-collée est sanctionnée."
- Volume : environ 1/4 du texte original sauf consigne contraire.

3. PRODUCTION ÉCRITE (08 pts) :
Structure OBLIGATOIRE :
INTRODUCTION : Accroche (auteur + titre + contexte) → Prise de position → Annonce du plan
DÉVELOPPEMENT : Axé sur les plans social, culturel, économique ou administratif. Chaque argument = exemple obligatoire tiré des œuvres : "Sous l'orage" (Badian), "Les soleils des indépendances" (Kourouma), "Le monde s'effondre" (Achebe), "Une si longue lettre" (Bâ), ou de la vie courante.
CONCLUSION : Bilan clair + Ouverture (facultative mais appréciée).

POSTURE : Encourageant, bienveillant mais rigoureux. Ne jamais rédiger à la place de l'élève sans qu'il ait d'abord essayé."""

        elif matiere_propre == "FRANÇAIS-COMMENTAIRE":
            system_prompt = """Tu es Akili, professeur expert de Français Terminale pour le BAC de Côte d'Ivoire. Tu guides l'élève sur le Sujet 2 : Le Commentaire Composé, noté sur 20 points (Introduction 04 pts / Développement 12 pts / Conclusion 04 pts).

1. INTRODUCTION (04 pts) — UN SEUL BLOC sans saut de ligne :
Ordre strict : Situation du texte (auteur + œuvre + contexte) → Idée générale / thème central → Formulation des 2 Centres d'Intérêt (axes d'étude) → Annonce du plan.

2. DÉVELOPPEMENT (12 pts) — LA RÈGLE FOND + FORME est ABSOLUE :
- Combat principal : si l'élève paraphrase sans relever de procédés, recadre immédiatement.
- Structure d'un paragraphe valide : Idée → Procédé identifié (citation entre guillemets) → Analyse technique → Effet de sens produit.
- Procédés à chercher : figures de style (métaphore, personnification, anaphorèse), champs lexicaux, ponctuation, types de phrases, temps verbaux.
- Transitions obligatoires entre chaque centre d'intérêt.

3. CONCLUSION (04 pts) — UN SEUL BLOC :
Bilan des axes étudiés + Ouverture culturelle ou littéraire obligatoire.

POSTURE : Coach littéraire rigoureux et encourageant. Ne laisse passer aucune paraphrase sans outil stylistique."""

        elif matiere_propre == "FRANÇAIS-DISSERTATION":
            system_prompt = """Tu es Akili, professeur expert de Français Terminale pour le BAC de Côte d'Ivoire. Tu guides l'élève sur le Sujet 3 : La Dissertation Littéraire, notée sur 20 points (Introduction 04 pts / Développement 12 pts / Conclusion 04 pts).

1. INTRODUCTION (04 pts) — UN SEUL PARAGRAPHE FLUIDE :
Ordre strict : Accroche (contexte littéraire ou thématique) → Présentation et explication de la citation/thèse → Problématique (question centrale) → Annonce du plan.

2. DÉVELOPPEMENT (12 pts) :
- Plan dialectique (Thèse / Antithèse / Synthèse) ou thématique selon le sujet.
- Règle d'or : "Un argument sans exemple littéraire précis perd la moitié de sa valeur aux yeux du correcteur."
- Auteurs et œuvres à mobiliser obligatoirement : David Diop (Coups de pilon), Victor Hugo (Les Châtiments), Aimé Césaire, Léopold Sédar Senghor, Bernard Dadié, Camara Laye, Ahmadou Kourouma.
- Chaque partie = argument clair + exemple précis (titre + auteur) + analyse de l'effet.
- Transitions obligatoires entre chaque partie.

3. CONCLUSION (04 pts) :
Bilan qui répond à la problématique (sans répéter le plan) + Ouverture vers un autre débat littéraire ou culturel.

POSTURE : Ton digne, académique, rigoureux mais accessible et motivant. Valorise l'effort de réflexion critique de l'élève.
            """

        elif "HISTOIRE" in matiere_propre or "GEOGRAPHIE" in matiere_propre:
            if (type_examen or "").strip().upper() == "BEPC":
                system_prompt = PROMPT_HIST_GEO_BEPC
            else:
                system_prompt = PROMPT_HIST_GEO
        else:
            system_prompt = """Tu es Akili, un assistant pédagogique expert en préparation au BAC africain (Côte d'Ivoire, UEMOA).
            Tu aides les élèves à comprendre les cours et à réussir leurs examens.
            Tu réponds toujours en français, de façon claire, pédagogique et encourageante."""

        system_prompt = system_prompt + "\n\n" + instructions_mode(mode_registre, examen_registre)

        # ─── 4. PRÉPARATION DU CONTENU MULTIMODAL POUR VERTEX AI ───
        contents = [system_prompt]
        
        if history:
            try:
                history_data = json.loads(history)
                history_text = "\n".join([
                    f"{'Élève' if m['role'] == 'user' else 'Akili'}: {m['content'][:2000]}"
                    for m in history_data[-8:]
                ])
                contents.append(f"HISTORIQUE DE LA CONVERSATION (reste COHERENT avec ce qui a deja ete dit — si un sujet/exercice precis a deja ete presente ou choisi, continue sur CE MEME sujet/exercice, ne le remplace jamais par un autre sans demande explicite de l'eleve) :\n{history_text}")
            except:
                pass

        contexte_coeffs = contexte_coefficients_officiels(question, serie, type_examen)
        if contexte_coeffs:
            contents.append(contexte_coeffs)

        if contexte_texte:
            contents.append(f"CONTEXTE OFFICIEL (extraits de programmes/annales officiels deja dans TA base de reference interne, PAS envoyes par l'eleve. Ne dis JAMAIS 'ton document' ni 'les extraits que tu as fournis/partages' a propos de ce contexte. N'invente et ne cite JAMAIS un nom de professeur, d'auteur d'un manuel scolaire, ou de personne apparaissant dans ce contexte comme source d'autorite -- ce sont des artefacts de scan/numerisation, pas des references academiques valides. Utilise uniquement le CONTENU, jamais les noms de personnes qui y figurent. REGLE ABSOLUE D'HONNETETE : si une information factuelle precise (oeuvres litteraires au programme, dates d'examen, coefficients, references bibliographiques, statistiques, listes officielles) n'apparait PAS explicitement dans ce contexte, tu ne dois JAMAIS l'inventer ni pretendre qu'elle vient d'une source officielle. Dis clairement a l'eleve : \"Je n'ai pas cette information dans mes documents officiels, verifie aupres de ton professeur ou de ton etablissement.\" Il vaut mieux reconnaitre une limite que donner une information fausse a un eleve qui prepare son examen) :\n{contexte_texte}")
            
        # Si un fichier image a été téléversé par l'élève
        if file is not None:
            file_bytes = await file.read()
            img_mime = file.content_type or "image/jpeg"
            if ";" in img_mime:
                img_mime = img_mime.split(";")[0]
            contents.append(Part.from_data(data=file_bytes, mime_type=img_mime))
            # ─── SAUVEGARDE FICHIER DANS GCS + FIRESTORE ───
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                safe_name = (file.filename or "fichier").replace(" ", "_")
                blob_path = f"uploads/{email}/{timestamp}_{safe_name}"
                gcs_client = storage.Client()
                bucket_obj = gcs_client.bucket(BUCKET_NAME)
                blob_obj = bucket_obj.blob(blob_path)
                blob_obj.upload_from_string(file_bytes, content_type=img_mime)
                safe_email = email.replace(".", "_").replace("@", "_at_")
                db.collection("users").document(safe_email).collection("uploads").add({
                    "filename": file.filename or "fichier",
                    "gcs_path": blob_path,
                    "matiere": matiere or "",
                    "timestamp": datetime.now().isoformat(),
                    "mime_type": img_mime
                })
                print(f"✅ Fichier sauvegardé : {blob_path}")
            except Exception as upload_err:
                print(f"⚠️ Erreur sauvegarde fichier : {upload_err}")
            
        if question:
            contents.append(f"QUESTION / EXERCICE DE L'ÉLÈVE :\n{question}")
        else:
            contents.append("Prends en charge cette image, identifie l'exercice, résous-le et explique-moi les étapes.")

        # ─── 5. APPEL GEMINI 2.5 FLASH ───
        response = model.generate_content(contents)

        # ─── 6. MISE À JOUR DU COMPTEUR DE QUESTIONS ───
        new_count = questions_today + 1 if not is_premium else questions_today
        
        user_ref.update({
            "questions_today": new_count,
            "last_question_date": today_str,
            "matiere": matiere if matiere else user_data.get("matiere"),
            "serie": serie if serie else user_data.get("serie")
        })
        
        return {
            "reponse": response.text,
            "mode": mode_registre,
            "examen": examen_registre,
            "sources": [
                {
                    "source": d.get("source", "Source officielle"),
                    "nom_fichier": d.get("nom_fichier") or d.get("storage_path") or d.get("upload_path"),
                    "examen": d.get("examen"),
                    "serie": d.get("serie"),
                    "matiere": d.get("matiere"),
                    "type_doc": d.get("type_doc"),
                }
                for d in contexte_docs
            ],
            "limit_reached": False,
            "questions_remaining": max(0, 5 - new_count) if not is_premium else "Illimité"
        }

    except Exception as e:
        print(f"❌ Erreur détaillée : {e}")
        return {"error": f"Erreur lors de la génération : {str(e)}"}

@app.get("/")
def health_check():
    return {"message": "Akili API opérationnelle 🚀", "documents": len(documents)}


# ─── GESTION DU RECYCLAGE LOGIQUE FREEMIUM & WEBHOOKS ───

def upgrade_to_premium(email: str):
    """Met à jour le statut de l'utilisateur dans Firestore."""
    try:
        ref = db.collection("users").document(email)
        ref.update({
            "tier": "PREMIUM",  
            "upgraded_at": datetime.utcnow().isoformat()
        })
        print(f"✅ {email} est passé au plan PREMIUM avec succès.")
    except Exception as e:
        print(f"❌ Erreur lors de l'upgrade Firestore pour {email}: {e}")

@app.post("/upgrade/premium")
async def upgrade_premium(request: Request):
    body = await request.json()
    email = body.get("email")
    if email:
        upgrade_to_premium(email)
        return {"status": "ok", "message": f"{email} est maintenant Premium !"}
    return {"status": "error", "message": "Email requis"}

@app.post("/webhook/stripe")
async def stripe_webhook(request: Request):
    try:
        body = await request.json()
        if body.get("type") == "checkout.session.completed":
            email = body["data"]["object"].get("customer_email")
            if email:
                upgrade_to_premium(email)
    except Exception as e:
        print(f"Erreur Webhook Stripe : {e}")
    return {"status": "ok"}

@app.post("/webhook/paydunya")
async def paydunya_webhook(request: Request):
    try:
        body = await request.json()
        if body.get("status") == "completed" or body.get("data", {}).get("status") == "completed":
            email = body.get("custom_data", {}).get("email") or body.get("data", {}).get("custom_data", {}).get("email")
            if email:
                upgrade_to_premium(email)
    except Exception as e:
        print(f"Erreur Webhook PayDunya : {e}")
    return {"status": "ok"}
@app.post("/transcribe")
async def transcribe_audio(file: UploadFile = File(...)):
    try:
        audio_bytes = await file.read()
        mime_type = file.content_type or "audio/webm"
        if ";" in mime_type:
            mime_type = mime_type.split(";")[0]
        audio_part = Part.from_data(data=audio_bytes, mime_type=mime_type)
        response = model.generate_content(
            [audio_part, "Transcris exactement ce que dit cette personne en français. Retourne uniquement la transcription brute, sans commentaire ni ponctuation ajoutée."],
            generation_config={"max_output_tokens": 500, "temperature": 0}
        )
        return {"transcript": response.text.strip()}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/run-pipeline")
async def run_pipeline_endpoint():
    """Endpoint pour déclencher le pipeline knowledge base"""
    import subprocess
    try:
        result = subprocess.Popen(
            ["python", "/app/pipeline_knowledge_base.py"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        return {"status": "ok", "message": "Pipeline démarré"}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.post("/impact")
async def generer_impact():
    """Endpoint pour déclencher le rapport d'impact quotidien"""
    try:
        import json
        from collections import Counter
        from google.cloud import storage
        users = list(db.collection("users").stream())
        total = len(users)
        series = Counter()
        matieres = Counter()
        actifs = 0
        total_q = 0
        for u in users:
            d = u.to_dict()
            total_q += d.get("questions_today", 0)
            if d.get("serie", "").strip(): series[d["serie"].strip()] += 1
            if d.get("matiere", "").strip(): matieres[d["matiere"].strip()] += 1
            if d.get("questions_today", 0) > 0: actifs += 1
        rapport = {
            "genere_le": datetime.utcnow().isoformat(),
            "total_utilisateurs": total,
            "questions_aujourdhui": total_q,
            "utilisateurs_actifs": actifs,
            "taux_activation": round(actifs/total*100, 1) if total > 0 else 0,
            "series": dict(series.most_common()),
            "matieres": dict(matieres.most_common()),
        }
        storage.Client().bucket("akili-database-storage-astute-curve-307922").blob("analytics/rapport_impact.json").upload_from_string(
            json.dumps(rapport, ensure_ascii=False, indent=2), content_type="application/json")
        db.collection("analytics").document("rapport_quotidien").set(rapport)
        return {"status": "ok", "rapport": rapport}
    except Exception as e:
        return {"status": "error", "message": str(e)}
