"""Controle qualite quotidien d'Akili sur WhatsApp.

Tire au hasard des conversations des dernieres 24 h, les fait relire par Gemini
avec une grille (bonne matiere, contenu juste, une etape a la fois, eleve bloque,
bug technique...) et affiche un rapport. Les enseignants n'ont a relire que les
conversations signalees.

  python3 controle_qualite.py                 # 20 conversations des dernieres 24 h
  python3 controle_qualite.py --n 40 --heures 48

Le rapport est aussi ecrit dans ~/controle_qualite/AAAA-MM-JJ.md (hors du depot :
il contient des extraits de conversations d'eleves) et chaque resultat est garde
dans la collection Firestore controle_qualite.
"""

import argparse
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ID = "astute-curve-307922"
LOCATION = "us-central1"
MIN_MESSAGES_ELEVE = 3
MAX_MESSAGES = 30

# Messages automatiques de l'inscription : une conversation qui n'a que ca n'est pas evaluee.
DEBUTS_AUTOMATIQUES = (
    "Bienvenue sur Akili", "Quel niveau", "Quelle série", "Quelle matière", "Tu veux travailler comment",
    "Dans quelle ville", "Quel est le nom de ton école", "Profil prêt", "C'est note", "Tu es en quelle classe",
    "Que veux-tu faire", "Je n'ai pas compris ton choix", "Akili t'a aidé",
)

GRILLE = """Tu es inspecteur pedagogique. Tu relis une conversation WhatsApp entre un eleve de Cote d'Ivoire
et Akili, un tuteur IA (BEPC, BAC general, BAC technique). Profil de l'eleve : {profil}.

Akili doit : rester dans la matiere choisie ; donner un contenu juste (aucune erreur de calcul, de fait,
de definition ; ne jamais valider une mauvaise reponse) ; guider une etape a la fois et finir par une
question courte ; reponses courtes adaptees a WhatsApp ; tutoyer l'eleve ; aucune syntaxe LaTeX ;
comprendre les reponses courtes de l'eleve (a, b, 3, oui...) dans le contexte de l'exercice.

Signale chaque probleme avec un de ces types :
- mauvaise_matiere : exercice ou explication d'une autre matiere que celle du profil
- erreur_contenu : erreur de calcul, de fait, de definition, ou mauvaise reponse validee
- mauvaise_comprehension : Akili ne comprend pas la reponse ou la demande de l'eleve, ou change de sujet
- trop_long : reponse trop longue ou plusieurs etapes a la fois
- eleve_bloque : l'eleve tourne en rond, se plaint, abandonne ou repete sa demande sans etre aide
- bug_technique : message d'erreur, "je n'arrive pas a lire le fichier" sans fichier, message en double, boucle d'inscription
- format : LaTeX, vouvoiement, mise en forme cassee
- autre

Gravite : "grave" (l'eleve apprend une erreur ou ne peut pas avancer), "moyenne", "faible".
Reponds UNIQUEMENT en JSON, sans texte autour :
{{"note": <1 a 5, 5 = excellent>, "resume": "<une phrase>",
  "problemes": [{{"type": "...", "gravite": "...", "extrait": "<citation courte>", "explication": "<une phrase>"}}]}}

CONVERSATION :
{transcription}"""


def masquer(phone):
    phone = str(phone or "")
    return "..." + phone[-4:] if len(phone) > 4 else phone


def est_automatique(texte):
    return str(texte or "").strip().startswith(DEBUTS_AUTOMATIQUES)


def regrouper(messages):
    """{phone: [messages tries par date]} pour les conversations avec un vrai travail."""
    par_phone = defaultdict(list)
    for m in messages:
        if m.get("phone"):
            par_phone[m["phone"]].append(m)
    retenues = {}
    for phone, liste in par_phone.items():
        liste.sort(key=lambda m: m.get("created_at", ""))
        eleve = [m for m in liste if m.get("direction") == "inbound"]
        akili = [m for m in liste if m.get("direction") == "outbound" and not est_automatique(m.get("text"))]
        if len(eleve) >= MIN_MESSAGES_ELEVE and akili:
            retenues[phone] = liste
    return retenues


def echantillon(conversations, n, graine):
    phones = sorted(conversations)
    random.Random(graine).shuffle(phones)
    return phones[:n]


def transcription(liste):
    lignes = []
    for m in liste[-MAX_MESSAGES:]:
        qui = "ELEVE" if m.get("direction") == "inbound" else "AKILI"
        texte = re.sub(r"\s+", " ", str(m.get("text") or ""))[:600]
        lignes.append(f"[{str(m.get('created_at', ''))[11:16]}] {qui} : {texte}")
    return "\n".join(lignes)


def profil_de(liste):
    dernier = liste[-1]
    return ", ".join(str(dernier.get(k) or "") for k in ("type_examen", "serie", "matiere", "mode") if dernier.get(k))


def lire_resultat(texte):
    """JSON de Gemini, meme entoure de ```json ... ```. None si illisible."""
    texte = (texte or "").strip()
    texte = re.sub(r"^```(?:json)?\s*|\s*```$", "", texte)
    try:
        resultat = json.loads(texte)
    except ValueError:
        m = re.search(r"\{.*\}", texte, flags=re.S)
        if not m:
            return None
        try:
            resultat = json.loads(m.group(0))
        except ValueError:
            return None
    resultat.setdefault("problemes", [])
    return resultat


def rapport(resultats, jour):
    notes = [r["note"] for r in resultats if isinstance(r.get("note"), (int, float))]
    types = Counter(p.get("type") for r in resultats for p in r.get("problemes", []))
    graves = [(r, p) for r in resultats for p in r.get("problemes", []) if p.get("gravite") == "grave"]
    lignes = [
        f"# Controle qualite Akili du {jour}",
        "",
        f"Conversations relues : {len(resultats)}",
        f"Note moyenne : {sum(notes) / len(notes):.1f} / 5" if notes else "Note moyenne : -",
        f"Conversations sans probleme : {sum(1 for r in resultats if not r.get('problemes'))}",
        "",
        "## Problemes par type",
    ]
    lignes += [f"- {t} : {k}" for t, k in types.most_common()] or ["- aucun"]
    lignes += ["", f"## Problemes graves a relire ({len(graves)})"]
    for r, p in graves:
        lignes.append(f"- {r['eleve']} ({r['profil']}) — {p.get('type')} : {p.get('explication', '')}")
        if p.get("extrait"):
            lignes.append(f"  > {p['extrait'][:300]}")
    lignes += ["", "## Toutes les conversations"]
    for r in sorted(resultats, key=lambda r: r.get("note", 5)):
        lignes.append(f"- {r.get('note', '?')}/5 {r['eleve']} ({r['profil']}) : {r.get('resume', '')}")
    return "\n".join(lignes)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=20, help="nombre de conversations a relire")
    parser.add_argument("--heures", type=int, default=24, help="periode couverte")
    args = parser.parse_args()

    from google.cloud import firestore
    import vertexai
    from vertexai.generative_models import GenerativeModel, GenerationConfig

    db = firestore.Client(project=PROJECT_ID)
    maintenant = datetime.now(timezone.utc)
    debut = (maintenant - timedelta(hours=args.heures)).isoformat()
    messages = [d.to_dict() for d in db.collection("whatsapp_messages").where("created_at", ">=", debut).stream()]
    conversations = regrouper(messages)
    jour = maintenant.strftime("%Y-%m-%d")
    choisis = echantillon(conversations, args.n, graine=jour)
    print(f"{len(messages)} messages, {len(conversations)} conversations de travail, {len(choisis)} relues.")

    vertexai.init(project=PROJECT_ID, location=LOCATION)
    modele = GenerativeModel("gemini-2.5-flash")
    config = GenerationConfig(response_mime_type="application/json", temperature=0.1)
    resultats = []
    for phone in choisis:
        liste = conversations[phone]
        prompt = GRILLE.format(profil=profil_de(liste) or "inconnu", transcription=transcription(liste))
        try:
            reponse = modele.generate_content([prompt], generation_config=config)
            resultat = lire_resultat(reponse.text)
        except Exception as exc:
            print(f"  {masquer(phone)} : echec de la relecture ({exc!r})")
            continue
        if not resultat:
            print(f"  {masquer(phone)} : reponse illisible")
            continue
        resultat.update({"eleve": masquer(phone), "profil": profil_de(liste), "jour": jour})
        resultats.append(resultat)
        print(f"  {masquer(phone)} : {resultat.get('note')}/5, {len(resultat['problemes'])} probleme(s)")
        try:
            ident = hashlib.sha256(f"{jour}:{phone}".encode()).hexdigest()[:24]
            db.collection("controle_qualite").document(ident).set(dict(resultat, phone=phone, cree_le=maintenant.isoformat()))
        except Exception as exc:
            print(f"  (resultat non sauvegarde : {exc!r})")

    texte = rapport(resultats, jour)
    dossier = Path.home() / "controle_qualite"
    dossier.mkdir(exist_ok=True)
    (dossier / f"{jour}.md").write_text(texte, encoding="utf-8")
    print("\n" + texte)
    print(f"\nRapport ecrit dans {dossier / (jour + '.md')}")


if __name__ == "__main__":
    main()
