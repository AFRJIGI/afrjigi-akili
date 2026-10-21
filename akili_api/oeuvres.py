"""Oeuvres litteraires agreees (francais), d'apres la circulaire n° 3272/MENAET/CAB/DPFC du 21 sept. 2026.

« Seules les oeuvres litteraires figurant sur la liste annexee sont retenues pour utilisation dans les
etablissements » (annee scolaire 2026-2027, secondaire general). La liste a ete recopiee depuis le PDF
envoye par M. Dosso (21 oct.) : 6e a Terminale, titres, auteurs et editeurs. Le BAC Technique n'est pas
couvert par la circulaire : rien n'est ajoute pour lui."""
import json
from pathlib import Path

FICHIER = Path(__file__).with_name("oeuvres_agreees_2026_2027.json")
LIBELLES = {"6E": "6e", "5E": "5e", "4E": "4e", "3E": "3e", "SECONDE": "Seconde", "PREMIERE": "Première",
            "TERMINALE": "Terminale"}

try:
    DONNEES = json.loads(FICHIER.read_text(encoding="utf-8"))
except (OSError, ValueError) as exc:  # jamais bloquant : Akili repond sans la liste
    print(f"OEUVRES liste illisible : {exc!r}", flush=True)
    DONNEES = {"niveaux": {}}


def _liste(oeuvres):
    return " ; ".join(f"{titre} ({auteur})" for titre, auteur, _ in oeuvres)


def consigne_oeuvres(code_classe, enseignant=False):
    """Bloc de prompt pour le cours de francais d'une classe (6E ... TERMINALE) ; "" si inconnue."""
    niveau = (DONNEES.get("niveaux") or {}).get(str(code_classe or "").upper())
    if not niveau:
        return ""
    libelle = LIBELLES.get(str(code_classe).upper(), str(code_classe))
    entete = (f"ŒUVRES LITTÉRAIRES AGRÉÉES 2026-2027 – {libelle} (circulaire n° 3272/MENAET/CAB/DPFC du "
              "21 septembre 2026 : seules ces œuvres peuvent être étudiées en classe cette année).\n"
              f"Auteurs africains : {_liste(niveau.get('auteurs_africains', []))}.\n"
              f"Autres auteurs : {_liste(niveau.get('autres_auteurs', []))}.\n")
    if enseignant:
        return entete + (
            "Pour les lectures, les fiches et les devoirs de cette classe, propose uniquement des œuvres de "
            "cette liste. Si l'enseignant cite une œuvre absente de la liste, signale-le-lui en une phrase. "
            "N'invente jamais le contenu d'une œuvre que tu ne connais pas bien : demande-lui un extrait.")
    return entete + (
        "Si l'élève demande quelles œuvres réviser ou veut travailler un roman, une pièce ou un recueil, "
        "appuie-toi sur cette liste. S'il cite une œuvre de la liste, travaille-la avec lui. S'il cite une "
        "œuvre absente de la liste, aide-le quand même, mais dis-lui en une phrase qu'elle ne figure pas sur "
        "la liste officielle 2026-2027 de sa classe et propose-lui une œuvre de la liste. "
        "N'invente jamais l'intrigue, les personnages ou des citations d'une œuvre que tu ne connais pas bien "
        "(beaucoup sont des œuvres ivoiriennes récentes) : demande à l'élève ce qu'il en a vu en classe ou de "
        "t'envoyer un extrait en photo.")
