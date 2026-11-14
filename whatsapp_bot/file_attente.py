"""Ordre d'arrivee des messages d'un meme eleve (0151, controle qualite du 12 nov. : 2423, 7849, 6216, 7698, 0357).

Le verrou (verrou_eleve.py) fait passer les messages un par un, mais dans l'ordre ou chaque copie Cloud Run
obtient le verrou, pas dans l'ordre ou l'eleve les a ecrits : la photo de l'exercice pouvait etre traitee apres
le « merci » ecrit juste apres. Chaque message est donc note dans Firestore des son arrivee ; une fois le
verrou pris, un message qui a un predecesseur encore en attente rend le verrou, patiente un instant, puis
repasse. Un predecesseur trop ancien (copie arretee) est ignore : on prefere repondre dans le desordre que
ne jamais repondre."""
from datetime import datetime, timedelta, timezone

COLLECTION = "messages_en_attente"
AGE_MAX = timedelta(seconds=60)   # au-dela, le predecesseur est considere comme perdu
ATTENTE_MAX = 8.0                 # secondes cumulees d'attente d'un predecesseur
PAS = 1.0


def _maintenant():
    return datetime.now(timezone.utc)


def _date(valeur):
    if isinstance(valeur, datetime):
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=timezone.utc)
    return None


def enregistrer(db, phone, message_id, ts_meta, maintenant=None, corps=None):
    """Note l'arrivee du message. ts_meta : horodatage WhatsApp (secondes) ou 0 s'il manque.
    corps : texte JSON du webhook, gardé pour qu'un message précédent puisse le regrouper (0155)."""
    maintenant = maintenant or _maintenant()
    donnees = {"phone": str(phone), "ts": int(ts_meta or 0), "recu_a": maintenant, "fusionne": False}
    if corps:
        donnees["corps"] = corps
    db.collection(COLLECTION).document(str(message_id)).set(donnees)


def retirer(db, message_id):
    try:
        db.collection(COLLECTION).document(str(message_id)).delete()
    except Exception as exc:
        print(f"FILE_ATTENTE retrait impossible : {exc!r}", flush=True)


def predecesseur_en_attente(db, phone, message_id, ts_meta, recu_a, maintenant=None):
    """Vrai si un message plus ancien du meme eleve attend encore (ts WhatsApp, puis heure d'arrivee)."""
    maintenant = maintenant or _maintenant()
    moi = (int(ts_meta or 0), _date(recu_a) or maintenant)
    for doc in db.collection(COLLECTION).where("phone", "==", str(phone)).stream():
        if doc.id == str(message_id):
            continue
        d = doc.to_dict() or {}
        arrive = _date(d.get("recu_a"))
        if arrive is None or maintenant - arrive > AGE_MAX:
            continue
        if (int(d.get("ts") or 0), arrive) < moi:
            return True
    return False


def suivants_en_attente(db, phone, message_id, ts_meta, recu_a, maintenant=None):
    """Messages PLUS RECENTS du meme eleve, deja arrives et pas encore traites ni fusionnes, du plus ancien au plus
    recent : liste de (message_id, corps JSON)."""
    maintenant = maintenant or _maintenant()
    moi = (int(ts_meta or 0), _date(recu_a) or maintenant)
    trouves = []
    for doc in db.collection(COLLECTION).where("phone", "==", str(phone)).stream():
        if doc.id == str(message_id):
            continue
        d = doc.to_dict() or {}
        arrive = _date(d.get("recu_a"))
        if arrive is None or maintenant - arrive > AGE_MAX or d.get("fusionne"):
            continue
        cle = (int(d.get("ts") or 0), arrive)
        if cle > moi:
            trouves.append((cle, doc.id, d.get("corps")))
    trouves.sort(key=lambda t: t[0])
    return [(i, c) for _, i, c in trouves]


def marquer_fusionnes(db, ids):
    for i in ids:
        db.collection(COLLECTION).document(str(i)).update({"fusionne": True})


def est_fusionne(db, message_id):
    """Vrai si un message plus ancien a deja traite celui-ci (il ne doit plus recevoir de reponse)."""
    doc = db.collection(COLLECTION).document(str(message_id)).get()
    return bool(doc.exists and (doc.to_dict() or {}).get("fusionne"))
