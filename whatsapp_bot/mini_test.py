"""Mini-test de progression : 3 questions a choix au debut d'un chapitre, 3 questions de meme niveau
quelques jours plus tard. La difference des scores mesure la progression (oct. 2026 : les indicateurs
tires des conversations ne pouvaient pas la montrer, la difficulte des exercices changeant en meme temps).

Ce module ne contient que la logique (calendrier, messages, correction) ; l'envoi et l'appel a l'API
sont dans main.py. Les fonctions recoivent un « etat » : {"matiere", "mini_test" (test en cours),
"mini_tests" (calendrier par matiere)}, garde dans la collection mini_tests_etat et non plus dans le profil.
Les resultats vont dans la collection mini_tests (identifiant pseudonyme, jamais le numero).
Depuis le 9 oct., le test est propose a la fin d'une seance (apres le bilan), plus au milieu d'un exercice.
"""
import re
from datetime import date, datetime, timedelta, timezone

COLLECTION = "mini_tests"
# Etat du test en cours et calendrier par matiere, hors du profil (identifiant pseudonyme) : le profil est
# remplace en entier a chaque message, et un message traite en parallele effacait le test (9 oct.).
COLLECTION_ETAT = "mini_tests_etat"
ECHANGES_AVANT_PROPOSITION = 4      # propose a la fin d'une seance d'au moins 4 echanges
JOURS_ACTIFS_AVANT_FIN = 3          # jours d'activite dans la matiere apres le test de debut
DELAI_ENTRE_PROPOSITIONS = timedelta(days=2)
MAX_PROPOSITIONS_DEBUT = 3          # apres 3 « plus tard », on ne propose plus le test de debut
DELAI_NOUVEAU_CYCLE = timedelta(days=14)
NB_QUESTIONS = 3
LETTRES = ("a", "b", "c")

OUI, PLUS_TARD = "minitest_oui", "minitest_plus_tard"
BOUTONS_PROPOSITION = [(OUI, "Oui, on y va"), (PLUS_TARD, "Plus tard")]
BOUTONS_REPONSE = [(f"minitest_{l}", l) for l in LETTRES]

PROPOSITION_DEBUT = ("Pour finir : 3 questions rapides sur ce que tu viens de travailler, pour voir où tu en es "
                     "(1 minute, ce n'est pas noté). On y va ?")
PROPOSITION_FIN = ("Tu as travaillé « {chapitre} » il y a quelques jours. 3 questions rapides pour voir tes "
                   "progrès (1 minute, pas noté). On y va ?")
PREPARATION = "Je prépare tes 3 questions…"
ECHEC = "Je n'arrive pas à préparer les questions maintenant. On continue ton travail !"
PLUS_TARD_OK = "D'accord, on continue ton travail."
INDISPONIBLE = "Ce petit test n'est plus disponible. On continue ton travail !"
INTERROMPU = "(Petit test arrêté. On reprend.)"


def aujourd_hui(now=None):
    return (now or datetime.now(timezone.utc)).date().isoformat()


def _jour(texte):
    try:
        return date.fromisoformat(str(texte)[:10])
    except ValueError:
        return None


def noter_jour_actif(profile, matiere, now=None):
    """Compte les jours d'activite dans la matiere apres le test de debut. Vrai si le profil a change."""
    cycle = (profile.get("mini_tests") or {}).get(matiere)
    if not cycle or not cycle.get("debut_le") or cycle.get("fin_le"):
        return False
    jour = aujourd_hui(now)
    jours = list(cycle.get("jours") or [])
    if jour <= cycle["debut_le"][:10] or jour in jours:
        return False
    cycle["jours"] = (jours + [jour])[-30:]
    return True


def phase_a_proposer(profile, nb_echanges, now=None):
    """'debut', 'fin' ou None : faut-il proposer un mini-test apres cette reponse d'Akili ?"""
    if profile.get("mini_test") or nb_echanges < ECHANGES_AVANT_PROPOSITION:
        return None
    matiere = profile.get("matiere")
    if not matiere:
        return None
    now = now or datetime.now(timezone.utc)
    cycle = (profile.get("mini_tests") or {}).get(matiere) or {}
    propose_le = _jour(cycle.get("propose_le"))
    if propose_le and now.date() - propose_le < DELAI_ENTRE_PROPOSITIONS:
        return None
    if cycle.get("debut_le") and not cycle.get("fin_le"):
        return "fin" if len(cycle.get("jours") or []) >= JOURS_ACTIFS_AVANT_FIN else None
    fin_le = _jour(cycle.get("fin_le"))
    if fin_le and now.date() - fin_le < DELAI_NOUVEAU_CYCLE:
        return None
    if not fin_le and int(cycle.get("propositions_debut", 0)) >= MAX_PROPOSITIONS_DEBUT:
        return None
    return "debut"


def derniere_question(texte):
    """Derniere question posee par Akili (« Peux-tu me dire la derivee de f(x) = x² + 3x + 5 ? »), a reposer
    apres le test : sans elle, l'eleve ne savait plus ou il en etait (test du 8 oct.)."""
    morceaux = [m.strip() for m in re.split(r"(?<=[.!?:])\s+|\n+", str(texte or "")) if m.strip()]
    questions = [m for m in morceaux if m.endswith("?")]
    return questions[-1][:300] if questions else ""


def proposer(profile, phase, now=None, reprise=""):
    """Enregistre la proposition dans le profil et renvoie le texte a envoyer avec les boutons."""
    matiere = profile["matiere"]
    cycles = profile.setdefault("mini_tests", {})
    cycle = cycles.setdefault(matiere, {})
    if phase == "debut" and cycle.get("fin_le"):
        cycle.clear()  # nouveau cycle, sur un nouveau chapitre
    cycle["propose_le"] = aujourd_hui(now)
    if phase == "debut":
        cycle["propositions_debut"] = int(cycle.get("propositions_debut", 0)) + 1
    profile["mini_test"] = {"etat": "propose", "phase": phase, "matiere": matiere, "reprise": reprise,
                            "cree_le": (now or datetime.now(timezone.utc)).isoformat()}
    if phase == "fin":
        return PROPOSITION_FIN.format(chapitre=cycle.get("chapitre") or "ce chapitre")
    return PROPOSITION_DEBUT


def questions_valides(donnees):
    """Controle la reponse de l'API : un chapitre et 3 questions a 3 choix avec une bonne lettre."""
    if not isinstance(donnees, dict) or not str(donnees.get("chapitre") or "").strip():
        return None
    questions = []
    for q in donnees.get("questions") or []:
        if not isinstance(q, dict):
            return None
        bonne = str(q.get("bonne") or "").strip().lower()[:1]
        champs = [str(q.get(k) or "").strip() for k in ("question",) + LETTRES]
        if bonne not in LETTRES or not all(champs):
            return None
        questions.append({"question": champs[0][:300], "a": champs[1][:120], "b": champs[2][:120],
                          "c": champs[3][:120], "bonne": bonne,
                          "explication": str(q.get("explication") or "").strip()[:200]})
    if len(questions) != NB_QUESTIONS:
        return None
    return {"chapitre": str(donnees["chapitre"]).strip()[:80], "questions": questions}


def demarrer(profile, donnees):
    test = profile["mini_test"]
    test.update({"etat": "en_cours", "chapitre": donnees["chapitre"], "questions": donnees["questions"],
                 "index": 0, "reponses": []})


def texte_question(test):
    i = test["index"]
    q = test["questions"][i]
    entete = f"Question {i + 1}/{NB_QUESTIONS}"
    if i == 0:
        entete = f"*{test['chapitre']}*\n\n{entete}"
    elif test.get("reponses"):
        # Controle qualite du 9 oct. : un eleve corrigeait sa reponse en tapant une autre lettre, qui partait
        # a la question suivante. Il voit maintenant ce qui a ete note.
        entete = f"Réponse {test['reponses'][-1]} notée.\n\n{entete}"
    return f"{entete} : {q['question']}\n\na. {q['a']}\nb. {q['b']}\nc. {q['c']}"


def boutons_reponse(index):
    """Boutons lies a la question : un ancien bouton touche plus tard ne repond plus a la question suivante."""
    return [(f"minitest_q{index + 1}_{l}", l) for l in LETTRES]


def lire_reponse(texte):
    """(numero de question ou None, lettre ou None) : « b », « B. », minitest_b, minitest_q2_b -> (2, 'b')."""
    t = str(texte or "").strip().lower()
    numero = None
    m = re.fullmatch(r"minitest_q(\d)_([a-z])", t)
    if m:
        return int(m.group(1)), (m.group(2) if m.group(2) in LETTRES else None)
    if t.startswith("minitest_"):
        t = t[len("minitest_"):]
    t = t.rstrip(".)")
    return numero, (t if t in LETTRES else None)


def lettre_de(texte):
    """« b », « B », « b. » ou un bouton de reponse -> 'b' ; sinon None."""
    return lire_reponse(texte)[1]


def enregistrer_reponse(test, lettre):
    """Ajoute la reponse ; vrai si le test est termine."""
    test["reponses"].append(lettre)
    test["index"] += 1
    return test["index"] >= NB_QUESTIONS


def score(test):
    return sum(1 for q, r in zip(test["questions"], test["reponses"]) if q["bonne"] == r)


def terminer(profile, now=None):
    """Clot le test : met a jour le calendrier de la matiere, renvoie (message, resultat a enregistrer)."""
    test = profile.pop("mini_test")
    note = score(test)
    cycle = profile.setdefault("mini_tests", {}).setdefault(test["matiere"], {})
    if test["phase"] == "debut":
        cycle.update({"debut_le": aujourd_hui(now), "chapitre": test["chapitre"], "score_debut": note, "jours": [],
                      "questions_debut": [q["question"] for q in test["questions"]]})
        cycle.pop("fin_le", None)
        suite = "Je te reposerai 3 questions dans quelques jours pour voir tes progrès."
        bilan = f"Merci ! Tu as {note}/{NB_QUESTIONS}."
    else:
        debut = int(cycle.get("score_debut", 0))
        cycle["fin_le"] = aujourd_hui(now)
        cycle["score_fin"] = note
        if note > debut:
            avis = "Bravo, tu as progressé !"
        elif note == debut == NB_QUESTIONS:
            avis = "Parfait : tu maîtrises ce chapitre."
        elif note == debut:
            avis = "Même score qu'au début : continue à t'entraîner sur ce chapitre."
        else:
            avis = "Ce chapitre mérite d'être revu : demande-moi un exercice dessus."
        bilan = f"Tu as {note}/{NB_QUESTIONS} (au début : {debut}/{NB_QUESTIONS}). {avis}"
        suite = ""
    corrections = []
    for i, (q, r) in enumerate(zip(test["questions"], test["reponses"]), 1):
        if q["bonne"] != r:
            ligne = f"Question {i} : la bonne réponse était {q['bonne']} ({q[q['bonne']]})."
            if q.get("explication"):
                ligne += f" {q['explication']}"
            corrections.append(ligne)
    reprise = test.get("reprise")
    retour = (f"On reprend ton travail. {reprise}" if reprise
              else "Bon travail ! Envoie ton exercice ou ta question quand tu veux.")
    message = "\n\n".join([bilan] + corrections + [x for x in (suite, retour) if x])
    resultat = {"phase": test["phase"], "matiere": test["matiere"], "chapitre": test["chapitre"],
                "score": note, "total": NB_QUESTIONS, "reponses": test["reponses"],
                "bonnes": [q["bonne"] for q in test["questions"]],
                "questions": [q["question"] for q in test["questions"]],
                "debut_le": cycle.get("debut_le"), "score_debut": cycle.get("score_debut"),
                "cree_le": (now or datetime.now(timezone.utc)).isoformat()}
    return message, resultat
