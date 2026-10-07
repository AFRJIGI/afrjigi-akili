"""Classe les anciens utilisateurs WhatsApp d'Akili pour preparer une relance par vagues.

Lecture seule : rien n'est envoye, rien n'est modifie dans Firestore.

  python3 segmenter_anciens_utilisateurs.py                # depuis le lancement, inactifs depuis 7 jours
  python3 segmenter_anciens_utilisateurs.py --inactif 14   # inactifs depuis 14 jours

Segments (enseignants et numeros actifs ces derniers jours exclus) :
  habitues    : au moins 3 jours de travail avec Akili, puis plus de nouvelles (a relancer en premier)
  une_seance  : 1 ou 2 jours de travail
  inscription : inscription commencee, jamais de question a Akili

Seuls les eleves qui ont accepte les rappels pedagogiques (bouton « Oui, je souhaite ») et qui n'ont
jamais ecrit STOP sont « relancables ».

Le detail par numero est ecrit dans ~/relance/segments_AAAA-MM-JJ.csv, HORS du depot : il contient
des numeros de telephone d'eleves. Ne jamais l'ajouter a Git.
"""
import argparse
import csv
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ICI = Path(__file__).parent
sys.path.insert(0, str(ICI / "whatsapp_bot"))
import marketing_consent as marketing  # noqa: E402
import pedagogical_consent as pedagogique  # noqa: E402

PROJET = "astute-curve-307922"
DEBUT_PILOTE = "2026-09-01"
# Etapes du bot qui correspondent a un vrai travail avec Akili (comme le tableau de bord).
ETAPES_APPRENTISSAGE = {"akili_api", "suite_reponse", "pending_question_answered", "teacher_direct_request"}
CHAMPS = ["phone", "direction", "created_at", "processing_stage", "matiere", "serie", "type_examen",
          "user_type", "enseignant_verifie"]
SEGMENTS = ["habitues", "une_seance", "inscription"]
LIBELLES = {"habitues": "Habitués partis (3 jours de travail ou plus)",
            "une_seance": "Une ou deux séances",
            "inscription": "Inscription sans question à Akili"}


def resumer(messages):
    """{numero: infos} a partir des messages (entrants surtout) de chaque numero."""
    infos = defaultdict(lambda: {"jours": set(), "jours_travail": set(), "entrants": 0, "premier": "",
                                 "dernier": "", "matiere": "", "serie": "", "type_examen": "", "enseignant": False})
    for m in sorted(messages, key=lambda m: str(m.get("created_at") or "")):
        phone, quand = m.get("phone"), str(m.get("created_at") or "")
        if not phone or not quand:
            continue
        info = infos[phone]
        if m.get("enseignant_verifie") or str(m.get("user_type") or "").upper() == "ENSEIGNANT":
            info["enseignant"] = True
        if m.get("direction") != "inbound":
            continue
        info["entrants"] += 1
        info["jours"].add(quand[:10])
        if m.get("processing_stage") in ETAPES_APPRENTISSAGE:
            info["jours_travail"].add(quand[:10])
        info["premier"] = info["premier"] or quand
        info["dernier"] = quand
        for champ in ("matiere", "serie", "type_examen"):
            if m.get(champ):
                info[champ] = m[champ]  # profil le plus recent
    return dict(infos)


def segment(info, limite_inactivite):
    """Segment d'un numero, ou la raison de l'exclure."""
    if info["enseignant"]:
        return "exclu_enseignant"
    if info["dernier"] >= limite_inactivite:
        return "exclu_actif"
    if len(info["jours_travail"]) >= 3:
        return "habitues"
    if info["jours_travail"]:
        return "une_seance"
    return "inscription"


def consentement(pedago, promo):
    """relancable / stop / sans_accord a partir des documents de consentement (ou None)."""
    if marketing.classify_marketing_consent(promo) == marketing.OPTED_OUT or \
            pedagogique.classify(pedago) == marketing.OPTED_OUT:
        return "stop"
    # Accord aux rappels pedagogiques (bouton) ou aux messages d'Akili (« OUI MARKETING ») : les deux sont
    # des accords explicites ; un STOP sur l'un ou l'autre l'emporte (teste juste au-dessus).
    if pedagogique.classify(pedago) == marketing.OPTED_IN or \
            marketing.classify_marketing_consent(promo) == marketing.OPTED_IN:
        return "relancable"
    return "sans_accord"


def lire_page(requete, essais=5, attente=None):
    """Une page de resultats, avec nouvel essai : Firestore coupe parfois la lecture (« 503 Stream
    removed (ping timeout) »), et la reprise automatique plante dans Cloud Shell (conflit de versions)."""
    import time
    attente = attente or time.sleep
    for essai in range(essais):
        try:
            return list(requete.stream())
        except Exception as exc:  # 503, ou AttributeError '_retry' de la bibliotheque
            if essai == essais - 1:
                raise
            print(f"  lecture interrompue ({type(exc).__name__}), nouvel essai {essai + 2}/{essais}...")
            attente(3 * (essai + 1))


def lire_messages(db, debut, taille_page=500):
    messages, dernier = [], None
    while True:
        requete = (db.collection("whatsapp_messages").where("created_at", ">=", debut)
                   .order_by("created_at").select(CHAMPS).limit(taille_page))
        if dernier is not None:
            requete = requete.start_after(dernier)
        page = lire_page(requete)
        messages += [d.to_dict() or {} for d in page]
        if len(page) < taille_page:
            return messages
        dernier = page[-1]
        if len(messages) % 20000 == 0:
            print(f"  {len(messages)} messages lus...")


def lire_consentements(db, phones, taille=300):
    """{numero: (doc rappels pedagogiques, doc promotions)} ; documents sous un identifiant hache."""
    resultats = {}
    for i in range(0, len(phones), taille):
        lot = phones[i:i + taille]
        ids = {marketing.consent_document_id(p): p for p in lot}
        pedago = {d.id: d.to_dict() for d in db.get_all(
            [db.collection(pedagogique.COLLECTION).document(x) for x in ids]) if d.exists}
        promo = {d.id: d.to_dict() for d in db.get_all(
            [db.collection(marketing.CONSENT_COLLECTION).document(x) for x in ids]) if d.exists}
        for x, phone in ids.items():
            resultats[phone] = (pedago.get(x), promo.get(x))
    return resultats


def rapport(lignes):
    total = Counter(l["segment"] for l in lignes)
    accords_actifs = sum(1 for l in lignes if l["segment"] == "exclu_actif" and l["consentement"] == "relancable")
    lignes_txt = [f"{len(lignes)} numéros", f"  exclus : {total['exclu_actif']} actifs récemment "
                                            f"(dont {accords_actifs} ont déjà accepté les rappels), "
                                            f"{total['exclu_enseignant']} enseignants", ""]
    for seg in SEGMENTS:
        groupe = [l for l in lignes if l["segment"] == seg]
        acc = Counter(l["consentement"] for l in groupe)
        lignes_txt.append(f"{LIBELLES[seg]} : {len(groupe)}  -> relançables {acc['relancable']}, "
                          f"sans accord {acc['sans_accord']}, STOP {acc['stop']}")
        relancables = [l for l in groupe if l["consentement"] == "relancable"]
        if relancables:
            matieres = Counter(l["matiere"] or "?" for l in relancables).most_common(6)
            niveaux = Counter(l["type_examen"] or "?" for l in relancables).most_common()
            lignes_txt.append("    matières : " + ", ".join(f"{m} {n}" for m, n in matieres))
            lignes_txt.append("    niveaux  : " + ", ".join(f"{m} {n}" for m, n in niveaux))
    return "\n".join(lignes_txt)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--inactif", type=int, default=7, help="jours sans message pour etre relance")
    parser.add_argument("--depuis", default=DEBUT_PILOTE, help="date de debut (AAAA-MM-JJ)")
    args = parser.parse_args()

    from google.cloud import firestore
    db = firestore.Client(project=PROJET)
    maintenant = datetime.now(timezone.utc)
    limite = (maintenant - timedelta(days=args.inactif)).isoformat()

    print(f"Lecture des messages depuis le {args.depuis}...")
    infos = resumer(lire_messages(db, args.depuis))
    candidats = sorted(p for p, i in infos.items() if segment(i, limite) in SEGMENTS + ["exclu_actif"])
    print(f"{len(infos)} numéros, lecture des consentements de {len(candidats)} candidats...")
    accords = lire_consentements(db, candidats)

    lignes = []
    for phone, info in infos.items():
        seg = segment(info, limite)
        lignes.append({
            "phone": phone, "segment": seg,
            "consentement": (consentement(*accords.get(phone, (None, None)))
                             if seg in SEGMENTS + ["exclu_actif"] else ""),
            "matiere": info["matiere"], "serie": info["serie"], "type_examen": info["type_examen"],
            "jours_travail": len(info["jours_travail"]), "messages_eleve": info["entrants"],
            "premier_message": info["premier"][:10], "dernier_message": info["dernier"][:10],
        })

    dossier = Path.home() / "relance"
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"segments_{maintenant:%Y-%m-%d}.csv"
    with fichier.open("w", newline="", encoding="utf-8") as f:
        ecrivain = csv.DictWriter(f, fieldnames=list(lignes[0]) if lignes else ["phone"])
        ecrivain.writeheader()
        ordre = {s: i for i, s in enumerate(SEGMENTS)}
        ecrivain.writerows(sorted(lignes, key=lambda l: (ordre.get(l["segment"], 9), l["dernier_message"])))
    print("\n" + rapport(lignes))
    print(f"\nDétail par numéro : {fichier}  (contient des numéros d'élèves : ne pas l'ajouter à Git)")


if __name__ == "__main__":
    main()
