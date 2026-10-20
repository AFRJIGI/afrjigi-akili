"""Un seul message a la fois par eleve, toutes copies Cloud Run confondues (19 oct.).

Deux messages tres rapproches du meme eleve (« bonjour » puis la photo de l'exercice) etaient traites en
parallele par deux copies du bot : la session P0 de la copie la plus lente avait change entre-temps
(« conflit de revision ») et sa reponse etait jetee sans etre envoyee, 156 fois en 48 h ; l'historique
ecrit en dernier effacait aussi l'echange de l'autre copie. Le second message attend maintenant que le
premier soit fini, puis il est traite avec l'historique a jour.

Verrou = document Firestore cree de facon atomique (create echoue s'il existe). Il expire tout seul si la
copie qui le tient s'arrete ; une attente trop longue laisse passer le message (ancien comportement) plutot
que de ne jamais repondre."""
import asyncio
import uuid
from datetime import datetime, timedelta, timezone

COLLECTION = "verrous_eleves"
DUREE_BAIL = timedelta(seconds=120)   # traitement le plus long : Akili + nouvel essai apres 8 s + envoi
ATTENTE_MAX = 45.0                     # secondes avant de traiter quand meme le message
PAS = 0.5


def _deja_existant(exc):
    return any(c.__name__ in {"AlreadyExists", "Conflict"} for c in type(exc).__mro__)


def _maintenant():
    return datetime.now(timezone.utc)


def _date(valeur):
    if isinstance(valeur, datetime):
        return valeur if valeur.tzinfo else valeur.replace(tzinfo=timezone.utc)
    try:
        d = datetime.fromisoformat(str(valeur))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def prendre(db, phone, jeton, maintenant=None):
    """Vrai si ce jeton tient maintenant le verrou de l'eleve."""
    maintenant = maintenant or _maintenant()
    ref = db.collection(COLLECTION).document(str(phone))
    donnees = {"jeton": jeton, "expire_at": maintenant + DUREE_BAIL, "pris_le": maintenant}
    try:
        ref.create(donnees)
        return True
    except Exception as exc:
        if not _deja_existant(exc):
            raise
    instantane = ref.get()
    actuel = (instantane.to_dict() or {}) if instantane.exists else {}
    expire = _date(actuel.get("expire_at"))
    if instantane.exists and expire is not None and expire > maintenant:
        return False
    # Verrou expire (copie arretee) : reprise seulement si personne ne l'a modifie depuis la lecture.
    try:
        if instantane.exists:
            ref.update(donnees, option=db.write_option(last_update_time=instantane.update_time))
        else:
            ref.create(donnees)
        return True
    except Exception:
        return False


def liberer(db, phone, jeton):
    """Supprime le verrou s'il est encore a ce jeton (jamais celui d'une autre copie apres expiration)."""
    try:
        ref = db.collection(COLLECTION).document(str(phone))
        instantane = ref.get()
        if instantane.exists and (instantane.to_dict() or {}).get("jeton") == jeton:
            ref.delete(option=db.write_option(last_update_time=instantane.update_time))
    except Exception as exc:
        print(f"VERROU liberation impossible : {exc!r}", flush=True)


async def attendre(db, phone, attente_max=ATTENTE_MAX, pas=PAS, dormir=asyncio.sleep):
    """Jeton du verrou une fois obtenu ; None si Firestore repond mal ou apres `attente_max` secondes."""
    jeton = uuid.uuid4().hex
    attendu = 0.0
    while True:
        try:
            if prendre(db, phone, jeton):
                if attendu:
                    print(f"VERROU obtenu apres {attendu:.1f} s d'attente", flush=True)
                return jeton
        except Exception as exc:
            print(f"VERROU indisponible, message traite sans attendre : {exc!r}", flush=True)
            return None
        if attendu >= attente_max:
            print(f"VERROU toujours pris apres {attente_max:.0f} s : message traite quand meme", flush=True)
            return None
        await dormir(pas)
        attendu += pas
