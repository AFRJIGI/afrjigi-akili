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
import os
import hashlib
import json
import random
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ID = "astute-curve-307922"
LOCATION = os.environ.get("VERTEX_LOCATION", "global")  # moins de refus 429 qu'en us-central1 (9 oct.)
MIN_MESSAGES_ELEVE = 3
MAX_MESSAGES = 30
# Avant : 600 caracteres, alors qu'Akili envoie jusqu'a 850 ; le relecteur prenait la coupure
# de la transcription pour un message tronque (7 « bug_technique » sur 20 conversations le 7 oct.).
LONGUEUR_LUE = 1500

# Messages automatiques de l'inscription : une conversation qui n'a que ca n'est pas evaluee.
DEBUTS_AUTOMATIQUES = (
    "Bienvenue sur Akili", "Quel niveau", "Quelle série", "Quelle matière", "Tu veux travailler comment",
    "Dans quelle ville", "Quel est le nom de ton école", "Profil prêt", "C'est note", "C'est noté", "Profil actuel", "Tu es en quelle classe",
    "Que veux-tu faire", "Je n'ai pas compris ton choix", "Akili t'a aidé",
    "Dernière petite question", "Merci, c'est noté", "D'accord, pas de souci",
)

GRILLE = """Tu es inspecteur pedagogique. Tu relis une conversation WhatsApp entre un eleve de Cote d'Ivoire
et Akili, un tuteur IA (BEPC, BAC general, BAC technique). Profil de l'eleve a la fin : {profil}.

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

Important : juge uniquement Akili. Une erreur de l'eleve, corrigee par Akili, n'est pas un probleme.
"[photo]", "[document]" et "[audio]" signalent un fichier reellement envoye par l'eleve.
Les lignes « --- profil a partir d'ici : ... --- » donnent le niveau et la matiere choisis A CE MOMENT :
juge « mauvaise_matiere » d'apres le profil en cours a ce moment-la, jamais d'apres le profil final. Un
changement de matiere ou de niveau demande par l'eleve (menu, liste, « je veux faire francais ») n'est pas
une erreur d'Akili. « Bonjour Akili META-STUDENT » est le message prerempli d'une publicite.
"[liste] ..." est une liste de choix a toucher que l'eleve a bien recue sur WhatsApp.
"[suite non recopiee pour la relecture]" veut dire que la transcription est raccourcie ici : ce n'est pas
un message coupe chez l'eleve. Un vrai message coupe se termine par « Je m'arrete ici. Ecris suite... ».
Les messages automatiques de l'inscription (niveau, serie, matiere, mode, ville, ecole) ne sont pas a juger
sur le fond ; signale seulement une vraie boucle ou un choix de l'eleve mal enregistre.

Gravite : "grave" (l'eleve apprend une erreur ou ne peut pas avancer), "moyenne", "faible".
Reponds UNIQUEMENT en JSON, sans texte autour :
{{"note": <1 a 5, 5 = excellent>, "resume": "<une phrase>",
  "problemes": [{{"type": "...", "gravite": "...", "extrait": "<citation courte>", "explication": "<une phrase>"}}]}}

CONVERSATION :
{transcription}"""


CHAMPS_LUS = ["phone", "direction", "text", "matiere", "serie", "type_examen", "mode", "created_at"]
TAILLE_PAGE = 1000


def lire_messages(db, debut, taille_page=TAILLE_PAGE, essais=3):
    """Messages depuis `debut`, par pages courtes et seulement les champs utiles. Une seule
    requete sur 24 h depassait le delai de Firestore (« 503 Stream removed (ping timeout) »)."""
    import time
    messages, dernier = [], None
    while True:
        requete = (db.collection("whatsapp_messages").where("created_at", ">=", debut)
                   .order_by("created_at").select(CHAMPS_LUS).limit(taille_page))
        if dernier is not None:
            requete = requete.start_after(dernier)
        for essai in range(essais):
            try:
                page = list(requete.stream())
                break
            except Exception as exc:
                if essai == essais - 1:
                    raise
                print(f"  lecture interrompue ({type(exc).__name__}), nouvel essai...")
                time.sleep(2 * (essai + 1))
        messages += [d.to_dict() or {} for d in page]
        if len(page) < taille_page:
            return messages
        dernier = page[-1]
        print(f"  {len(messages)} messages lus...")


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


def profil_du_message(m):
    return ", ".join(str(m.get(k) or "") for k in ("type_examen", "serie", "matiere", "mode") if m.get(k))


def transcription(liste):
    """Transcription lisible. Une ligne « --- profil --- » a chaque changement de matiere ou de niveau :
    sans elle, une seance de SVT suivie d'un passage aux maths etait jugee « mauvaise matiere » d'apres le
    profil final (controle qualite du 7 oct.)."""
    lignes, profil_affiche = [], None
    for m in liste[-MAX_MESSAGES:]:
        profil = profil_du_message(m)
        if profil and profil != profil_affiche:
            lignes.append(f"--- profil a partir d'ici : {profil} ---")
            profil_affiche = profil
        qui = "ELEVE" if m.get("direction") == "inbound" else "AKILI"
        texte = re.sub(r"\s+", " ", str(m.get("text") or ""))
        if len(texte) > LONGUEUR_LUE:
            texte = texte[:LONGUEUR_LUE] + " [suite non recopiee pour la relecture]"
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
    messages = lire_messages(db, debut)
    conversations = regrouper(messages)
    jour = maintenant.strftime("%Y-%m-%d")
    # Heure dans le nom : deux controles le meme jour (UTC) ne s'ecrasent plus (7 oct.).
    etiquette = maintenant.strftime("%Y-%m-%d_%Hh%M")
    choisis = echantillon(conversations, args.n, graine=etiquette)
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
            ident = hashlib.sha256(f"{etiquette}:{phone}".encode()).hexdigest()[:24]
            db.collection("controle_qualite").document(ident).set(dict(resultat, phone=phone, cree_le=maintenant.isoformat()))
        except Exception as exc:
            print(f"  (resultat non sauvegarde : {exc!r})")

    texte = rapport(resultats, jour)
    dossier = Path.home() / "controle_qualite"
    dossier.mkdir(exist_ok=True)
    fichier = dossier / f"{etiquette}.md"
    fichier.write_text(texte, encoding="utf-8")
    print("\n" + texte)
    print(f"\nRapport ecrit dans {fichier}")


if __name__ == "__main__":
    main()
