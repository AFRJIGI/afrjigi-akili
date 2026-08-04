import os
import requests
from fastapi import FastAPI, Request
from fastapi.responses import PlainTextResponse
from collections import defaultdict

app = FastAPI(title="AfrJigi WhatsApp Bot")

WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
VERIFY_TOKEN = "afrjigi2026"
AKILI_API_URL = "https://akili-api-598190730734.us-central1.run.app/question"

conversations = defaultdict(list)
user_profiles = defaultdict(dict)
processed_messages = set()

def format_whatsapp_message(message, limit=1400):
    message = message.strip()

    if len(message) <= limit:
        return message

    cut = message[:limit]
    last_break = max(cut.rfind("\n"), cut.rfind(". "), cut.rfind("? "), cut.rfind("! "))

    if last_break > 500:
        cut = cut[:last_break + 1]

    return cut.strip() + "\n\nDis-moi si tu veux la suite."

def send_whatsapp(to, message):
    message = format_whatsapp_message(message)

    url = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    res = requests.post(url, headers=headers, json=data)
    print(f"DEBUG SEND: Status {res.status_code} - Response: {res.text}", flush=True)


def update_profile_from_text(profile, message):
    msg = message.upper()

    if "BEPC" in msg or "3EME" in msg or "3ÈME" in msg or "TROISIEME" in msg or "TROISIÈME" in msg:
        profile["serie"] = "BEPC"
        profile["type_examen"] = "BEPC"

    for serie in ["A1", "A2", "G1", "G2", "F1", "F2", "F3", "F4", "A", "B", "C", "D", "E"]:
        if (
            f"SERIE {serie}" in msg
            or f"SÉRIE {serie}" in msg
            or f"SERIE-{serie}" in msg
            or f"SÉRIE-{serie}" in msg
        ):
            profile["serie"] = serie
            break

    matieres = {
        "MATH": "MATHS",
        "MATHS": "MATHS",
        "MATHEMATIQUES": "MATHS",
        "MATHÉMATIQUES": "MATHS",
        "PHILO": "PHILO",
        "PC": "PC",
        "PHYSIQUE": "PC",
        "CHIMIE": "PC",
        "SVT": "SVT",
        "HG": "HG",
        "HISTOIRE": "HG",
        "GEOGRAPHIE": "HG",
        "GÉOGRAPHIE": "HG",
        "ANGLAIS": "ANGLAIS",
        "FRANCAIS": "FRANCAIS",
        "FRANÇAIS": "FRANCAIS",

        # Matières BAC Technique
        "COMPTABILITE": "COMPTA",
        "COMPTABILITÉ": "COMPTA",
        "COMPTA": "COMPTA",
        "ECONOMIE": "ECO",
        "ÉCONOMIE": "ECO",
        "ECO": "ECO",
        "DROIT": "DROIT",
        "ETUDE DE CAS": "ETUDE-CAS",
        "ÉTUDE DE CAS": "ETUDE-CAS",
        "ETUDE-CAS": "ETUDE-CAS",
        "TQG": "TQG",
        "ORGANISATION COMMERCIALE": "OC",
        "OC": "OC",
        "ESTI": "ESTI",
    }

    for key, value in matieres.items():
        if key in msg:
            profile["matiere"] = value
            break

    return profile


def infer_type_examen(serie, message):
    msg = (message or "").upper()
    serie = (serie or "").upper().strip()

    if serie == "BEPC" or "BEPC" in msg or "3EME" in msg or "3ÈME" in msg or "TROISIEME" in msg or "TROISIÈME" in msg:
        return "BEPC"

    if serie in {"B", "G1", "G2", "F1", "F2", "F3", "F4", "STI"}:
        return "BAC_TECHNIQUE"

    if any(x in msg for x in ["BAC TECH", "BAC TECHNIQUE", "TECHNIQUE", "TERMINALE G", "TERMINALE B"]):
        return "BAC_TECHNIQUE"

    return "BAC_GENERAL"


def infer_mode(message):
    msg = (message or "").upper()
    examen_keywords = [
        "MODE EXAMEN", "SUJET", "EXERCICE", "ENTRAINE", "ENTRAÎNE",
        "ENTRAINEMENT", "ENTRAÎNEMENT", "CORRIGE", "CORRIGÉ",
        "CORRIGE-MOI", "NOTE-MOI", "BAREME", "BARÈME", "EPREUVE", "ÉPREUVE"
    ]

    if any(k in msg for k in examen_keywords):
        return "examen"

    return "etude"


def get_akili_response(question, matiere, serie, history, phone="whatsapp_user", type_examen=None, mode=None):
    try:
        contexte = "\n".join([
            f"{'Élève' if m['role'] == 'user' else 'Akili'}: {m['content']}"
            for m in history[-6:]
        ])

        question_whatsapp = (
            "IMPORTANT: Tu réponds dans WhatsApp. "
            "Réponse courte, moins de 900 caractères. "
            "Ne transcris pas l'énoncé complet. "
            "Ne donne pas un long corrigé d'annales. "
            "Si c'est en Maths, donne seulement un petit exercice simple ou la première étape. "
            "Structure: idée clé, 3 points maximum, puis une question pour continuer.\n\n"
            f"Question élève: {question}"
       )

        payload = {
            "email": f"{phone}@afrjigi.com",
            "question": f"{contexte}\nÉlève: {question_whatsapp}" if contexte else question_whatsapp,
            "matiere": matiere,
            "serie": serie,
            "type_examen": type_examen,
            "mode": mode,
            "history": contexte,
        }
        

        print(f"AKILI_API payload: {payload}", flush=True)
        res = requests.post(AKILI_API_URL, files={k: (None, str(v)) for k, v in payload.items() if v is not None}, timeout=60)
        print(f"AKILI_API status: {res.status_code}", flush=True)
        print(f"AKILI_API body: {res.text}", flush=True)

        data = res.json()
        return (
            data.get("reponse")
            or data.get("response")
            or data.get("answer")
            or data.get("message")
            or "Désolé, je n'ai pas pu répondre."
        )

    except Exception as e:
        import traceback
        print(f"Erreur AKILI_API: {repr(e)}", flush=True)
        traceback.print_exc()
        return "Désolé, je rencontre une petite difficulté technique, réessaie dans un instant."


@app.get("/")
def health():
    return {"status": "AfrJigi WhatsApp Bot actif"}


@app.get("/whatsapp/webhook")
async def verify_webhook(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    print(f"Webhook verify: mode={mode} token={token} challenge={challenge}", flush=True)

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)

    return PlainTextResponse("Forbidden", status_code=403)


@app.post("/whatsapp/webhook")
async def receive_message(request: Request):
    body = await request.json()

    try:
        messages = body["entry"][0]["changes"][0]["value"].get("messages", [])
        if not messages:
            return {"status": "ok"}

        msg = messages[0]
        phone = msg["from"]
        text = msg.get("text", {}).get("body", "").strip()
        message_id = msg.get("id")

        if message_id in processed_messages:
            print(f"Message déjà traité: {message_id}", flush=True)
            return {"status": "ok"}

        if message_id:
            processed_messages.add(message_id)

        if len(processed_messages) > 1000:
            processed_messages.clear()

        if not text:
            return {"status": "ok"}

        print(f"Message de {phone}: {text}", flush=True)

        profile = user_profiles[phone] or {"serie": "TOUTES", "matiere": "MATHS"}
        profile = update_profile_from_text(profile, text)

        type_examen = infer_type_examen(profile.get("serie", "TOUTES"), text)
        mode = infer_mode(text)
        profile["type_examen"] = type_examen
        profile["mode"] = mode
        user_profiles[phone] = profile

        matiere = profile.get("matiere", "MATHS")
        serie = profile.get("serie", "TOUTES")
        conversation_key = f"{phone}:{type_examen}:{serie}:{matiere}:{mode}"

        print(f"Profil WhatsApp: {profile}", flush=True)
        print(f"Conversation key: {conversation_key}", flush=True)

        reponse = get_akili_response(
            text,
            matiere,
            serie,
            conversations[conversation_key],
            phone,
            type_examen,
            mode,
        )

        conversations[conversation_key].append({"role": "user", "content": text})
        conversations[conversation_key].append({"role": "assistant", "content": reponse})
        conversations[conversation_key] = conversations[conversation_key][-10:]

        send_whatsapp(phone, reponse)

    except Exception as e:
        import traceback
        print(f"Erreur webhook WhatsApp: {repr(e)}", flush=True)
        traceback.print_exc()

    return {"status": "ok"}


@app.get("/instagram/webhook")
async def verify_instagram(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return PlainTextResponse(content=challenge, status_code=200)

    return PlainTextResponse("Forbidden", status_code=403)


@app.post("/instagram/webhook")
async def instagram_message(request: Request):
    body = await request.json()

    try:
        entries = body.get("entry", [])
        for entry in entries:
            messaging = entry.get("messaging", [])
            for event in messaging:
                sender_id = event["sender"]["id"]
                message = event.get("message", {})
                text = message.get("text", "")

                if text:
                    print(f"Instagram DM de {sender_id}: {text}", flush=True)
                    reponse = get_akili_response(
                        question=text,
                        matiere="MATHS",
                        serie="TOUTES",
                        history=[],
                    )
                    send_instagram_dm(sender_id, reponse)

    except Exception as e:
        import traceback
        print(f"Erreur Instagram: {repr(e)}", flush=True)
        traceback.print_exc()

    return {"status": "ok"}


def send_instagram_dm(recipient_id: str, message: str):
    if len(message) > 1000:
        message = message[:1000] + "..."

    url = "https://graph.facebook.com/v25.0/me/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    data = {
        "recipient": {"id": recipient_id},
        "message": {"text": message},
    }

    res = requests.post(url, headers=headers, json=data)
    print(f"Instagram SEND: {res.status_code} - {res.text}", flush=True)