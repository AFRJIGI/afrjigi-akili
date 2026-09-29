"""Regression : les listes numerotees et les puces doivent rester sur leur propre ligne."""
import unittest

import main


def envoye(texte_akili):
    """Ce que l'eleve voit : post-traitement Akili puis nettoyage WhatsApp."""
    return main.clean_whatsapp_response(main.strip_filler_opening(texte_akili))


class FormatageListesTests(unittest.TestCase):
    def test_liste_numerotee_garde_ses_retours_a_la_ligne(self):
        texte = (
            "Une conclusion de dissertation se construit en trois parties :\n\n"
            "1.  **Bilan**\n    Tu rappelles les idées principales des parties précédentes.\n"
            "2.  **Réponse finale**\n    Tu réponds à la problématique.\n"
            "3.  **Ouverture**\n    Tu élargis la réflexion."
        )
        sortie = envoye(texte)
        self.assertIn("précédentes.\n2. *Réponse finale*", sortie)
        self.assertIn("problématique.\n3. *Ouverture*", sortie)

    def test_puces_apres_un_point_d_interrogation(self):
        texte = 'Dans A = (x - 1)² - 4², dis-moi :\n*   Qui joue le rôle de "a" ?\n*   Qui joue le rôle de "b" ?'
        sortie = envoye(texte)
        self.assertEqual(sortie.count("• "), 2)
        self.assertNotIn(" * Qui", sortie)

    def test_liste_apres_une_phrase_simple(self):
        sortie = envoye("Deux notions clés. 1. Croissance économique\nAugmentation du PIB.\n2. Chômage\nSans emploi.")
        self.assertIn("PIB.\n2. Chômage", sortie)

    def test_accroche_retiree_mais_liste_intacte(self):
        texte = "Bonjour ! Excellente initiative de vouloir t'exercer. Voici l'exercice :\n1. Calcule A.\n2. Factorise A."
        self.assertEqual(main.strip_filler_opening(texte), "Voici l'exercice :\n1. Calcule A.\n2. Factorise A.")

    def test_message_entierement_accroche_garde(self):
        self.assertEqual(main.strip_filler_opening("Très bien !"), "Très bien !")

    def test_validation_de_reponse_conservee(self):
        texte = "C'est une très bonne réponse ! La méthode (b) est efficace ici."
        self.assertEqual(main.strip_filler_opening(texte), texte)

    def test_texte_sans_ponctuation_inchange(self):
        self.assertEqual(main.strip_filler_opening("Voici la suite\n1. a\n2. b"), "Voici la suite\n1. a\n2. b")



class TutoiementTests(unittest.TestCase):
    def test_consigne_de_tutoiement_envoyee_a_akili(self):
        from unittest import mock
        envoye = {}

        class Reponse:
            status_code = 200
            text = '{"reponse": "ok"}'

            def json(self):
                return {"reponse": "ok"}

            def raise_for_status(self):
                pass

        def faux_post(url, files=None, timeout=None, **k):
            envoye["files"] = files
            return Reponse()

        with mock.patch.object(main.requests, "post", side_effect=faux_post):
            main.get_akili_response("Explique le PIB", "ECO", "B", [], phone="22500000009",
                                    type_examen="BAC_TECHNIQUE", mode="etude")
        self.assertIn("Tutoie TOUJOURS", str(envoye["files"]))


if __name__ == "__main__":
    unittest.main()
