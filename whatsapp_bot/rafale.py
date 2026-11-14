"""Messages et photos envoyes en rafale : une seule reponse (0155, controle qualite du 14 nov. : 4894, 2338, 7788, 0775).

Avant, chaque message d'un eleve etait traite a part : deux photos lancaient deux exercices, « a » puis « merci » deux
reponses. Le message qui obtient le verrou regarde maintenant les messages plus recents du meme eleve deja arrives :
les textes sont joints, les photos empilees en une seule image, et les messages absorbes ne recoivent aucune
reponse. Seuls les messages « text » et « image » sont regroupes ; tout autre type (audio, bouton, document, liste)
passe seul, comme avant."""
import copy
import hashlib
import json
from pathlib import Path

MAX_MESSAGES = 5
MAX_IMAGES = 4
LARGEUR_MAX = 1600
HAUTEUR_MAX = 6000
ATTENTE_PHOTO = 1.5      # secondes d'attente apres une photo : une autre arrive souvent juste apres
ATTENTE_PHOTO_MAX = 6.0
TYPES_FUSIONNABLES = {"text", "image"}


def _message(corps):
    try:
        return corps["entry"][0]["changes"][0]["value"]["messages"][0]
    except (KeyError, IndexError, TypeError):
        return None


def texte_du_message(msg):
    if msg.get("type") == "image":
        return (msg.get("image", {}).get("caption") or "").strip()
    return (msg.get("text", {}).get("body") or "").strip()


def peut_fusionner(messages):
    return (bool(messages) and 1 < len(messages) <= MAX_MESSAGES
            and all(isinstance(m, dict) and m.get("type") in TYPES_FUSIONNABLES for m in messages)
            and len({m.get("from") for m in messages}) == 1)


def empiler_images(chemins, sortie):
    """Une seule image JPEG : les photos l'une sous l'autre, a la meme largeur. Renvoie le chemin, ou None."""
    from PIL import Image, ImageOps
    images = []
    try:
        for chemin in chemins[:MAX_IMAGES]:
            im = ImageOps.exif_transpose(Image.open(chemin)).convert("RGB")
            images.append(im)
        if not images:
            return None
        largeur = min(LARGEUR_MAX, max(im.width for im in images))
        redim = []
        for im in images:
            h = max(1, round(im.height * largeur / im.width))
            redim.append(im.resize((largeur, h)))
        hauteur = sum(im.height for im in redim)
        if hauteur > HAUTEUR_MAX:  # trop haute pour rester lisible : on reduit tout
            facteur = HAUTEUR_MAX / hauteur
            largeur = max(1, round(largeur * facteur))
            redim = [im.resize((largeur, max(1, round(im.height * facteur)))) for im in redim]
            hauteur = sum(im.height for im in redim)
        toile = Image.new("RGB", (largeur, hauteur), (255, 255, 255))
        y = 0
        for im in redim:
            toile.paste(im, (0, y))
            y += im.height
        Path(sortie).parent.mkdir(parents=True, exist_ok=True)
        toile.save(sortie, "JPEG", quality=85)
        return str(sortie)
    except Exception as exc:
        print(f"RAFALE empilement impossible : {exc!r}", flush=True)
        return None


def construire_corps(corps_chef, messages, chemin_image=None):
    """Corps de webhook equivalent a un seul message : le premier message, avec tous les textes joints et, s'il y a
    des photos, l'identifiant de la premiere (l'image envoyee au modele est l'image empilee)."""
    textes = [t for t in (texte_du_message(m) for m in messages) if t]
    images = [m for m in messages if m.get("type") == "image"]
    chef = copy.deepcopy(messages[0])
    if images:
        base = copy.deepcopy(images[0].get("image") or {})
        base["caption"] = "\n".join(textes)
        chef["type"] = "image"
        chef.pop("text", None)
        chef["image"] = base
    else:
        chef["type"] = "text"
        chef["text"] = {"body": "\n".join(textes)}
    corps = copy.deepcopy(corps_chef)
    corps["entry"][0]["changes"][0]["value"]["messages"] = [chef]
    return corps


async def regrouper(db, file_attente, corps, phone, message_id, ts_meta, recu_a, telecharger, dormir):
    """(corps_fusionne, {media_id: chemin_image_empilee}) ou (None, {}) si rien a regrouper.
    telecharger(media_id, nom, mime) -> chemin local ; dormir : asyncio.sleep (remplacable dans les tests)."""
    chef = _message(corps)
    if not chef or chef.get("type") not in TYPES_FUSIONNABLES:
        return None, {}
    suivants = file_attente.suivants_en_attente(db, phone, message_id, ts_meta, recu_a)
    if chef.get("type") == "image":
        # Une photo est souvent suivie d'une autre : on laisse un court instant avant de repondre.
        attendu, vus = 0.0, len(suivants)
        while attendu < ATTENTE_PHOTO_MAX:
            await dormir(ATTENTE_PHOTO)
            attendu += ATTENTE_PHOTO
            suivants = file_attente.suivants_en_attente(db, phone, message_id, ts_meta, recu_a)
            if len(suivants) == vus:
                break
            vus = len(suivants)
    if not suivants:
        return None, {}
    messages, ids = [chef], []
    for i, texte_json in suivants[:MAX_MESSAGES - 1]:
        try:
            m = _message(json.loads(texte_json)) if texte_json else None
        except ValueError:
            m = None
        if m is None:
            break  # corps absent : on s'arrete la, le reste passera a la suite
        messages.append(m)
        ids.append(i)
    if len(messages) > 1 and not peut_fusionner(messages):
        # Un message d'un autre type (audio, bouton...) coupe la rafale : on ne garde que ce qui precede.
        gardes = [messages[0]]
        ids_gardes = []
        for m, i in zip(messages[1:], ids):
            if m.get("type") not in TYPES_FUSIONNABLES:
                break
            gardes.append(m)
            ids_gardes.append(i)
        messages, ids = gardes, ids_gardes
    if not peut_fusionner(messages):
        return None, {}
    chemin, medias = None, {}
    images = [m for m in messages if m.get("type") == "image"]
    if images:
        chemins = []
        for m in images:
            infos = m.get("image") or {}
            if not infos.get("id"):
                return None, {}
            c = telecharger(infos["id"], "whatsapp_image", infos.get("mime_type") or "image/jpeg")
            if not c:
                return None, {}
            chemins.append(c)
        if len(chemins) > 1:
            chemin = empiler_images(chemins, f"/tmp/whatsapp_media/fusion_{hashlib.sha1(str(message_id).encode()).hexdigest()[:12]}.jpg")
            if not chemin:
                return None, {}
        else:
            chemin = chemins[0]
        medias[images[0]["image"]["id"]] = chemin
    file_attente.marquer_fusionnes(db, ids)
    print(f"RAFALE {len(messages)} messages regroupes ({len(images)} photo(s))", flush=True)
    return construire_corps(corps, messages, chemin), medias
