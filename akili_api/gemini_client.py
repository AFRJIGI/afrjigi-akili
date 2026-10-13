"""Acces a Gemini par la bibliotheque Google Gen AI (google-genai), sur Vertex AI.

L'ancien module vertexai.generative_models n'est plus fourni depuis le 24 juin 2026 et refusait le point
d'acces mondial (« global ») ; Gemini 2.5 Flash est retire pour les nouveaux projets le 16 oct. 2026.
`ModeleGemini` garde la meme forme d'appel que l'ancien GenerativeModel (generate_content(contents,
generation_config=...)) : le reste de l'API n'a pas change.

Reglages par variables d'environnement du service Cloud Run (aucun nouveau code pour changer) :
  AKILI_MODELE     nom du modele (par defaut gemini-2.5-flash ; essais : gemini-3.6-flash...)
  VERTEX_LOCATION  point d'acces (par defaut global ; us-central1 pour revenir en arriere)
  AKILI_REFLEXION  reflexion du modele : vide (reglage du modele), none, low, medium ou high
  VERTEX_LOCATION_SECOURS  points d'acces essayes dans l'ordre quand le premier refuse (429) ou ne repond pas
                   a temps (par defaut us-central1,europe-west1 ; vide pour ne pas en avoir). Le point d'acces
                   « global » partage sa capacite : les 9 et 10 oct., 3 refus 429 de suite ont donne « Beaucoup
                   d'eleves utilisent Akili en ce moment » ; le 12 oct., 28 refus en fin d'apres-midi et deux
                   reponses de plus de 90 s (le bot abandonne a 90 s : « petite difficulte technique »).
  GEMINI_DELAI_S   temps maximal d'un appel a Gemini avant de passer au point d'acces suivant (40 s).
"""
import os
import time

PROJECT_ID = "astute-curve-307922"
MODELE = os.environ.get("AKILI_MODELE", "gemini-2.5-flash").strip()
LOCATION = os.environ.get("VERTEX_LOCATION", "global").strip()
REFLEXION = os.environ.get("AKILI_REFLEXION", "").strip().lower()
LOCATIONS_SECOURS = [l.strip() for l in os.environ.get("VERTEX_LOCATION_SECOURS", "us-central1,europe-west1").split(",")
                     if l.strip() and l.strip() != LOCATION]
LOCATION_SECOURS = LOCATIONS_SECOURS[0] if LOCATIONS_SECOURS else ""
DELAI_APPEL_S = float(os.environ.get("GEMINI_DELAI_S", "40"))
# Pas de nouvel essai sur un autre point d'acces apres ce delai : le bot attend la reponse 90 s au plus.
BUDGET_SECOURS_S = 45

# Gemini 2.5 regle sa reflexion par un budget de tokens, Gemini 3 par un niveau.
BUDGETS_2_5 = {"none": 0, "low": 512, "medium": 2048, "high": 8192}

_clients = {}


def client(location=None):
    location = location or LOCATION
    if location not in _clients:
        from google import genai
        _clients[location] = genai.Client(vertexai=True, project=PROJECT_ID, location=location,
                                          http_options={"timeout": int(DELAI_APPEL_S * 1000)})
    return _clients[location]


def est_refus_de_quota(erreur):
    texte = str(erreur)
    return "429" in texte or "RESOURCE_EXHAUSTED" in texte.upper() or "resource exhausted" in texte.lower()


def est_delai_depasse(erreur):
    """Appel trop long ou service indisponible un instant : un autre point d'acces peut repondre."""
    texte, classe = str(erreur).upper(), type(erreur).__name__.upper()
    return (isinstance(erreur, TimeoutError) or "TIMEOUT" in classe or "TIMED OUT" in texte
            or "DEADLINE_EXCEEDED" in texte or "503" in texte or "UNAVAILABLE" in texte)


def est_temporaire(erreur):
    return est_refus_de_quota(erreur) or est_delai_depasse(erreur)


class Part:
    """Meme appel que l'ancien vertexai Part.from_data (photo, PDF ou audio de l'eleve)."""

    @staticmethod
    def from_data(data, mime_type):
        from google.genai import types
        return types.Part.from_bytes(data=data, mime_type=mime_type)


def reglage_reflexion(modele, reflexion):
    """{"thinking_budget": n} pour Gemini 2.5, {"thinking_level": ...} pour les suivants, {} sinon."""
    if not reflexion:
        return {}
    if modele.startswith("gemini-2.5"):
        budget = BUDGETS_2_5.get(reflexion)
        return {} if budget is None else {"thinking_budget": budget}
    return {"thinking_level": "minimal" if reflexion == "none" else reflexion}


def construire_config(generation_config, modele=MODELE, reflexion=REFLEXION):
    from google.genai import types
    reglages = dict(generation_config or {})
    reflexion_cfg = reglage_reflexion(modele, reflexion)
    if reflexion_cfg:
        reglages["thinking_config"] = types.ThinkingConfig(**reflexion_cfg)
    return types.GenerateContentConfig(**reglages)


def ligne_consommation(reponse, duree, modele):
    """Journal de consommation pour estimer le cout reel par message (lecture, cache, ecriture, reflexion)."""
    u = getattr(reponse, "usage_metadata", None)
    valeur = lambda nom: int(getattr(u, nom, 0) or 0) if u is not None else 0
    return (f"GEMINI_USAGE modele={modele} duree={duree:.1f}s entree={valeur('prompt_token_count')} "
            f"cache={valeur('cached_content_token_count')} sortie={valeur('candidates_token_count')} "
            f"reflexion={valeur('thoughts_token_count')}")


class ModeleGemini:
    def __init__(self, nom_modele=None):
        self.nom_modele = nom_modele or MODELE

    def generate_content(self, contents, generation_config=None):
        debut = time.time()
        demande = dict(model=self.nom_modele,
                       contents=list(contents) if isinstance(contents, (list, tuple)) else contents,
                       config=construire_config(generation_config, self.nom_modele))
        lieux = [LOCATION] + [l for l in LOCATIONS_SECOURS if l != LOCATION]
        premiere_erreur, reponse = None, None
        for i, lieu in enumerate(lieux):
            try:
                reponse = client(lieu).models.generate_content(**demande)
                break
            except Exception as erreur:
                premiere_erreur = premiere_erreur or erreur
                suivant = lieux[i + 1] if i + 1 < len(lieux) else None
                if not (est_temporaire(erreur) and suivant and time.time() - debut < BUDGET_SECOURS_S):
                    raise premiere_erreur
                # Capacite partagee saturee ou reponse trop lente : essai tout de suite sur le point suivant.
                raison = "429" if est_refus_de_quota(erreur) else "delai"
                print(f"GEMINI_SECOURS {raison} sur {lieu}, essai sur {suivant}", flush=True)
        print(ligne_consommation(reponse, time.time() - debut, self.nom_modele), flush=True)
        return reponse
