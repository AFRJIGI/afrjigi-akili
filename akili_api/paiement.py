"""Paiement Premium par Paiement Pro (XPAYE) : lien de paiement + notification.

Fonctionnement (documentation « API JavaScript » de Paiement Pro) :
1. creer_paiement() envoie un POST JSON a initialize.php ; la reponse contient « url » (page de paiement
   ou l'eleve choisit Orange, MTN, Moov, Wave ou carte) et « success ».
2. Paiement Pro appelle ensuite notre URL de notification avec referenceNumber, amount et responsecode
   (0 = reussi, -1 = echec).
3. traiter_notification() n'active le Premium que si la reference existe chez nous, n'a pas deja ete
   payee, que le montant est celui attendu et que responsecode vaut 0.

La notification contient aussi un « hashcode » dont la formule n'est pas dans la documentation : en
attendant, l'URL de notification porte un jeton secret (PAIEMENTPRO_NOTIF_TOKEN) que seul Paiement Pro
connait, et la reference ne sert qu'une fois.
"""
import hmac
import json
import re
import time
import urllib.request
from datetime import datetime, timedelta

URL_INITIALISATION = "https://www.paiementpro.net/webservice/onlinepayment/js/initialize/initialize.php"
COLLECTION_PAIEMENTS = "paiements"
PRIX_PREMIUM_FCFA = 2000
DUREE_PREMIUM_JOURS = 30
CODE_DEVISE_FCFA = "952"
# Canaux acceptes par le compte (test du 7 nov. : le canal est obligatoire, CARD n'est pas active).
CANAUX = {"OMCIV2": "Orange Money", "MOMO": "MTN Money", "FLOOZ": "Moov Money"}


class ErreurPaiement(Exception):
    pass


def telephone_depuis_email(email):
    """« 2250712345678@afrjigi.com » -> « 2250712345678 » ; None si ce n'est pas un compte WhatsApp."""
    m = re.fullmatch(r"(\d{6,15})@afrjigi\.com", (email or "").strip())
    return m.group(1) if m else None


def reference_pour(telephone, maintenant=None):
    return f"AKILI-{telephone}-{int(maintenant if maintenant is not None else time.time())}"


def token_valide(recu, attendu):
    if not attendu or not recu:
        return False
    return hmac.compare_digest(str(recu), str(attendu))


def _post_json(url, charge, delai=20):
    requete = urllib.request.Request(
        url, data=json.dumps(charge).encode("utf-8"),
        headers={"Accept": "application/json", "Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(requete, timeout=delai) as reponse:
        return json.loads(reponse.read().decode("utf-8", "replace"))


def initialiser_paiement(merchant_id, montant, reference, telephone, email, notification_url, return_url,
                         canal, description="Akili Premium - 1 mois", post=None):
    """Retourne l'adresse de la page de paiement ; leve ErreurPaiement sinon."""
    charge = {
        "merchantId": merchant_id,
        "amount": int(montant),
        "description": description,
        "channel": canal,  # obligatoire : OMCIV2 (Orange), MOMO (MTN), FLOOZ (Moov)
        "countryCurrencyCode": CODE_DEVISE_FCFA,
        "referenceNumber": reference,
        "customerEmail": email,
        "customerFirstName": "Eleve",
        "customerLastname": "Akili",
        "customerPhoneNumber": telephone,
        "notificationURL": notification_url,
        "returnURL": return_url,
        "returnContext": "",
        "url": "",
        "success": False,
    }
    try:
        donnees = (post or _post_json)(URL_INITIALISATION, charge)
    except Exception as e:
        raise ErreurPaiement(f"Paiement Pro injoignable : {type(e).__name__}") from e
    if not isinstance(donnees, dict) or not donnees.get("success") or not donnees.get("url"):
        raise ErreurPaiement(f"Paiement Pro a refuse l'initialisation : {str(donnees)[:200]}")
    return donnees["url"]


def creer_paiement(db, email, merchant_id, base_api, token, canal, montant=PRIX_PREMIUM_FCFA, post=None,
                   maintenant=None):
    """Cree la reference, obtient le lien et enregistre le paiement « en_attente »."""
    canal = (canal or "").strip().upper()
    if canal not in CANAUX:
        raise ErreurPaiement(f"Canal de paiement inconnu : {canal!r}")
    telephone = telephone_depuis_email(email)
    if not telephone:
        raise ErreurPaiement("Seuls les comptes WhatsApp peuvent payer par ce chemin.")
    if not merchant_id or not token:
        raise ErreurPaiement("Paiement non configure (PAIEMENTPRO_MERCHANT_ID / PAIEMENTPRO_NOTIF_TOKEN).")
    reference = reference_pour(telephone, maintenant)
    base = base_api.rstrip("/")
    url = initialiser_paiement(
        merchant_id, montant, reference, telephone, email,
        notification_url=f"{base}/webhook/paiementpro/{token}",
        return_url=f"{base}/paiement/retour", canal=canal, post=post)
    db.collection(COLLECTION_PAIEMENTS).document(reference).set({
        "reference": reference, "email": email, "telephone": telephone, "montant": int(montant), "canal": canal,
        "statut": "en_attente", "cree_le": datetime.utcnow().isoformat(),
    })
    return {"url": url, "reference": reference}


def _entier(valeur):
    try:
        return int(float(str(valeur).strip().replace(",", ".")))
    except (TypeError, ValueError):
        return None


def traiter_notification(db, params, activer, merchant_id=None):
    """Retourne le resultat : « active », « deja_paye », « echec », « inconnue », « montant_incorrect »,
    « ignoree ». `activer(email, jours)` passe l'eleve en Premium."""
    reference = str(params.get("referenceNumber") or "").strip()
    if not reference:
        return "ignoree"
    ref = db.collection(COLLECTION_PAIEMENTS).document(reference)
    doc = ref.get()
    if not doc.exists:
        return "inconnue"
    fiche = doc.to_dict() or {}
    if fiche.get("statut") == "paye":
        return "deja_paye"
    if merchant_id and params.get("merchantId") and str(params.get("merchantId")) != str(merchant_id):
        return "ignoree"
    code = str(params.get("responsecode") if params.get("responsecode") is not None else "").strip()
    if code != "0":
        if code:
            ref.update({"statut": "echec", "responsecode": code})
        return "echec"
    if _entier(params.get("amount")) != _entier(fiche.get("montant")):
        ref.update({"statut": "montant_incorrect", "montant_recu": str(params.get("amount"))})
        return "montant_incorrect"
    activer(fiche["email"], DUREE_PREMIUM_JOURS)
    ref.update({"statut": "paye", "paye_le": datetime.utcnow().isoformat(), "responsecode": code})
    return "active"


def nouvelle_expiration(expiration_actuelle, jours, maintenant=None):
    """Prolonge a partir de l'echeance en cours si elle n'est pas passee, sinon a partir de maintenant."""
    maintenant = maintenant or datetime.utcnow()
    depart = maintenant
    if expiration_actuelle:
        try:
            actuelle = datetime.fromisoformat(str(expiration_actuelle))
            if actuelle > maintenant:
                depart = actuelle
        except ValueError:
            pass
    return (depart + timedelta(days=jours)).isoformat()
