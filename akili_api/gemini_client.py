"""Acces a Gemini par la bibliotheque Google Gen AI (google-genai), sur Vertex AI.

L'ancien module vertexai.generative_models n'est plus fourni depuis le 24 juin 2026 et refusait le point
d'acces mondial (« global ») ; Gemini 2.5 Flash est retire pour les nouveaux projets le 16 oct. 2026.
`ModeleGemini` garde la meme forme d'appel que l'ancien GenerativeModel (generate_content(contents,
generation_config=...)) : le reste de l'API n'a pas change.

Reglages par variables d'environnement du service Cloud Run (aucun nouveau code pour changer) :
  AKILI_MODELE     nom du modele (par defaut gemini-2.5-flash ; essais : gemini-3.6-flash...)
  VERTEX_LOCATION  point d'acces (par defaut global ; us-central1 pour revenir en arriere)
  AKILI_REFLEXION  reflexion du modele : vide (reglage du modele), none, low, medium ou high
"""
import os
import time

PROJECT_ID = "astute-curve-307922"
MODELE = os.environ.get("AKILI_MODELE", "gemini-2.5-flash").strip()
LOCATION = os.environ.get("VERTEX_LOCATION", "global").strip()
REFLEXION = os.environ.get("AKILI_REFLEXION", "").strip().lower()

# Gemini 2.5 regle sa reflexion par un budget de tokens, Gemini 3 par un niveau.
BUDGETS_2_5 = {"none": 0, "low": 512, "medium": 2048, "high": 8192}

_client = None


def client():
    global _client
    if _client is None:
        from google import genai
        _client = genai.Client(vertexai=True, project=PROJECT_ID, location=LOCATION)
    return _client


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
        reponse = client().models.generate_content(
            model=self.nom_modele,
            contents=list(contents) if isinstance(contents, (list, tuple)) else contents,
            config=construire_config(generation_config, self.nom_modele),
        )
        print(ligne_consommation(reponse, time.time() - debut, self.nom_modele), flush=True)
        return reponse
