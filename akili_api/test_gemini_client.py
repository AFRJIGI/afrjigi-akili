"""Acces a Gemini par google-genai (migration du 9 oct.) : meme forme d'appel qu'avant, modele et
reflexion reglables, consommation journalisee."""
import io
import pathlib
import sys
import types as pytypes
import unittest
from contextlib import redirect_stdout
from unittest import mock

import gemini_client

SOURCE = (pathlib.Path(__file__).parent / "main.py").read_text(encoding="utf-8")


class _Objet:
    def __init__(self, **kw):
        self.__dict__.update(kw)


def faux_genai(appels):
    types_mod = pytypes.ModuleType("google.genai.types")
    types_mod.GenerateContentConfig = lambda **kw: _Objet(**kw)
    types_mod.ThinkingConfig = lambda **kw: _Objet(**kw)
    types_mod.Part = _Objet(from_bytes=lambda data, mime_type: ("part", data, mime_type))

    class Modeles:
        def generate_content(self, model, contents, config):
            appels.append((model, contents, config))
            usage = _Objet(prompt_token_count=1200, cached_content_token_count=800, candidates_token_count=90,
                           thoughts_token_count=40)
            return _Objet(text="Bonjour", candidates=[], usage_metadata=usage)

    genai_mod = pytypes.ModuleType("google.genai")
    genai_mod.Client = lambda **kw: _Objet(models=Modeles(), reglages=kw)
    genai_mod.types = types_mod
    return genai_mod, types_mod


class GeminiClientTests(unittest.TestCase):
    def setUp(self):
        import google
        self.appels = []
        genai_mod, types_mod = faux_genai(self.appels)
        self.patches = [mock.patch.dict(sys.modules, {"google.genai": genai_mod, "google.genai.types": types_mod}),
                        mock.patch.object(google, "genai", genai_mod, create=True),
                        mock.patch.object(gemini_client, "_clients", {})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()

    def test_meme_appel_qu_avant(self):
        modele = gemini_client.ModeleGemini("gemini-2.5-flash")
        sortie = io.StringIO()
        with redirect_stdout(sortie):
            reponse = modele.generate_content(["consigne", gemini_client.Part.from_data(b"img", "image/jpeg")],
                                              generation_config={"temperature": 0.3})
        self.assertEqual(reponse.text, "Bonjour")
        nom, contenus, config = self.appels[0]
        self.assertEqual(nom, "gemini-2.5-flash")
        self.assertEqual(contenus, ["consigne", ("part", b"img", "image/jpeg")])
        self.assertEqual(config.temperature, 0.3)
        self.assertIn("GEMINI_USAGE modele=gemini-2.5-flash", sortie.getvalue())
        self.assertIn("entree=1200 cache=800 sortie=90 reflexion=40", sortie.getvalue())

    def test_secours_regional_sur_refus_429(self):
        import google
        lieux = []

        class Modeles:
            def __init__(self, lieu):
                self.lieu = lieu

            def generate_content(self, model, contents, config):
                lieux.append(self.lieu)
                if self.lieu == "global":
                    raise RuntimeError("429 RESOURCE_EXHAUSTED")
                return _Objet(text="ok", candidates=[], usage_metadata=None)

        google.genai.Client = lambda **kw: _Objet(models=Modeles(kw["location"]))
        with mock.patch.object(gemini_client, "LOCATION", "global"), \
                mock.patch.object(gemini_client, "LOCATIONS_SECOURS", ["us-central1"]), redirect_stdout(io.StringIO()) as sortie:
            reponse = gemini_client.ModeleGemini("gemini-2.5-flash").generate_content("q")
        self.assertEqual((reponse.text, lieux), ("ok", ["global", "us-central1"]))
        self.assertIn("GEMINI_SECOURS 429 sur global", sortie.getvalue())

    def test_pas_de_secours_pour_une_autre_erreur(self):
        import google

        class Modeles:
            def generate_content(self, model, contents, config):
                raise ValueError("400 INVALID_ARGUMENT")

        google.genai.Client = lambda **kw: _Objet(models=Modeles())
        with mock.patch.object(gemini_client, "LOCATION", "global"), self.assertRaises(ValueError):
            gemini_client.ModeleGemini("gemini-2.5-flash").generate_content("q")

    def test_reflexion(self):
        self.assertEqual(gemini_client.reglage_reflexion("gemini-2.5-flash", ""), {})
        self.assertEqual(gemini_client.reglage_reflexion("gemini-2.5-flash", "low"), {"thinking_budget": 512})
        self.assertEqual(gemini_client.reglage_reflexion("gemini-3.6-flash", "low"), {"thinking_level": "low"})
        self.assertEqual(gemini_client.reglage_reflexion("gemini-3.6-flash", "none"), {"thinking_level": "minimal"})
        config = gemini_client.construire_config({"temperature": 0.7}, "gemini-3.6-flash", "low")
        self.assertEqual(config.thinking_config.thinking_level, "low")

    def test_point_d_acces_et_modele_par_defaut(self):
        self.assertEqual(gemini_client.LOCATION, "global")
        self.assertEqual(gemini_client.MODELE, "gemini-2.5-flash")
        self.assertEqual(gemini_client.LOCATION_SECOURS, "us-central1")
        self.assertEqual(gemini_client.LOCATIONS_SECOURS, ["us-central1", "europe-west1"])
        self.assertEqual(gemini_client.client().reglages,
                         {"vertexai": True, "project": "astute-curve-307922", "location": "global",
                          "http_options": {"timeout": 40000}})

    def _lieux_qui_echouent(self, echecs):
        import google
        lieux = []

        class Modeles:
            def __init__(self, lieu):
                self.lieu = lieu

            def generate_content(self, model, contents, config):
                lieux.append(self.lieu)
                if self.lieu in echecs:
                    raise echecs[self.lieu]
                return _Objet(text="ok " + self.lieu, candidates=[], usage_metadata=None)

        google.genai.Client = lambda **kw: _Objet(models=Modeles(kw["location"]))
        return lieux

    def test_deuxieme_point_de_secours(self):
        # 12 oct. : 28 refus 429 sur « global » en fin d'apres-midi.
        lieux = self._lieux_qui_echouent({"global": RuntimeError("429 RESOURCE_EXHAUSTED"),
                                          "us-central1": RuntimeError("429 RESOURCE_EXHAUSTED")})
        with mock.patch.object(gemini_client, "LOCATIONS_SECOURS", ["us-central1", "europe-west1"]), \
                redirect_stdout(io.StringIO()) as sortie:
            reponse = gemini_client.ModeleGemini("gemini-2.5-flash").generate_content("q")
        self.assertEqual((reponse.text, lieux), ("ok europe-west1", ["global", "us-central1", "europe-west1"]))
        self.assertIn("GEMINI_SECOURS 429 sur us-central1, essai sur europe-west1", sortie.getvalue())

    def test_appel_trop_long(self):
        class ReadTimeout(Exception):
            pass
        lieux = self._lieux_qui_echouent({"global": ReadTimeout("The read operation timed out")})
        with mock.patch.object(gemini_client, "LOCATIONS_SECOURS", ["us-central1"]), redirect_stdout(io.StringIO()) as sortie:
            reponse = gemini_client.ModeleGemini("gemini-2.5-flash").generate_content("q")
        self.assertEqual(lieux, ["global", "us-central1"])
        self.assertIn("GEMINI_SECOURS delai sur global", sortie.getvalue())

    def test_tous_refusent(self):
        erreur = RuntimeError("429 RESOURCE_EXHAUSTED")
        self._lieux_qui_echouent({"global": erreur, "us-central1": RuntimeError("503 UNAVAILABLE")})
        with mock.patch.object(gemini_client, "LOCATIONS_SECOURS", ["us-central1"]), redirect_stdout(io.StringIO()), \
                self.assertRaises(RuntimeError) as ctx:
            gemini_client.ModeleGemini("gemini-2.5-flash").generate_content("q")
        self.assertIs(ctx.exception, erreur)  # la premiere erreur, pour le message « Beaucoup d'eleves »

    def test_pas_de_secours_apres_le_budget(self):
        lieux = self._lieux_qui_echouent({"global": RuntimeError("429")})
        with mock.patch.object(gemini_client, "LOCATIONS_SECOURS", ["us-central1"]), \
                mock.patch.object(gemini_client, "BUDGET_SECOURS_S", -1), self.assertRaises(RuntimeError):
            gemini_client.ModeleGemini("gemini-2.5-flash").generate_content("q")
        self.assertEqual(lieux, ["global"])


class SourceTests(unittest.TestCase):
    def test_l_api_n_utilise_plus_l_ancien_sdk(self):
        self.assertNotIn("import vertexai", SOURCE)
        self.assertNotIn("vertexai.init", SOURCE)
        self.assertIn("model = ModeleGemini()", SOURCE)


if __name__ == "__main__":
    unittest.main()
