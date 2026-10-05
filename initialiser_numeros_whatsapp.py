"""Remplit whatsapp_numeros (un document par numero, avec la date du premier message) a partir
de tout l'historique whatsapp_messages. A lancer une fois apres le deploiement du bot qui
note les nouveaux numeros ; le tableau de bord et la page /impact comptent ensuite les eleves
avec une simple requete count.

  python3 initialiser_numeros_whatsapp.py           # audit : compte, n'ecrit rien
  python3 initialiser_numeros_whatsapp.py --apply   # cree les documents manquants

Les numeros deja presents (crees par le bot) ne sont pas modifies, sauf si l'historique
montre un premier message plus ancien.
"""
import argparse
import time

COLLECTION = "whatsapp_numeros"


def premiers_contacts(messages):
    """{numero: date ISO du premier message recu} ; les messages sortants ne comptent pas."""
    premiers = {}
    for m in messages:
        phone, quand = m.get("phone"), str(m.get("created_at") or "")
        if not phone or not quand or m.get("direction") != "inbound":
            continue
        if phone not in premiers or quand < premiers[phone]:
            premiers[phone] = quand
    return premiers


def a_ecrire(premiers, existants):
    """Documents a creer, ou a avancer si l'historique est plus ancien que la date connue."""
    return {p: q for p, q in premiers.items() if p not in existants or q < (existants[p] or q)}


def lire_messages(db, taille=2000):
    from google.api_core.exceptions import ServiceUnavailable
    dernier, lus = None, 0
    while True:
        requete = db.collection("whatsapp_messages").select(["phone", "direction", "created_at"]) \
            .order_by("__name__").limit(taille)
        if dernier is not None:
            requete = requete.start_after(dernier)
        for essai in range(5):
            try:
                docs = list(requete.stream())
                break
            except ServiceUnavailable:
                time.sleep(2 * (essai + 1))
        else:
            raise SystemExit("Firestore indisponible, réessaie plus tard.")
        if not docs:
            return
        for doc in docs:
            yield doc.to_dict() or {}
        lus += len(docs)
        print(f"  … {lus} messages lus", flush=True)
        dernier = docs[-1]
        if len(docs) < taille:
            return


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    from google.cloud import firestore
    db = firestore.Client(project="astute-curve-307922")

    premiers = premiers_contacts(lire_messages(db))
    existants = {d.id: (d.to_dict() or {}).get("premier_contact") for d in db.collection(COLLECTION).stream()}
    ecritures = a_ecrire(premiers, existants)
    print(f"Numéros distincts dans l'historique : {len(premiers)}")
    print(f"Déjà dans {COLLECTION} : {len(existants)} ; à créer ou corriger : {len(ecritures)}")
    if not args.apply:
        print("Audit terminé, aucune écriture.")
        return
    lot, n = db.batch(), 0
    for phone, quand in ecritures.items():
        lot.set(db.collection(COLLECTION).document(str(phone)), {"premier_contact": quand}, merge=True)
        n += 1
        if n % 400 == 0:
            lot.commit()
            lot = db.batch()
    lot.commit()
    print(f"Terminé : {n} documents écrits. Total : {len(set(existants) | set(premiers))} numéros.")


if __name__ == "__main__":
    main()
