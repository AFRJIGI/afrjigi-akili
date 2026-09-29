"""Regression : une reponse courte ("b") ne doit jamais etre prise pour une
demande sur un fichier, et l'historique doit garder "b", pas le prompt reecrit."""
import unittest
from unittest import mock

import main


class ReponseCourteTests(unittest.TestCase):
    def setUp(self):
        self.phone = "22500000001"
        self.profile = {
            "type_examen": "BAC_TECHNIQUE", "serie": "G1", "matiere": "ECO",
            "mode": "etude", "first_learning_request_at": "2026-09-29T12:00:00+00:00",
        }
        main.conversations.clear()
        # Contexte recent qui contient des mots "document" (photo, PDF, Exercice 1).
        main.conversations[f"{self.phone}:ANCIEN:G1:MATHS:examen"] = [
            {"role": "assistant", "content": "Envoie une photo de ta copie pour l'Exercice 1 du PDF."},
            {"role": "assistant", "content": "Quel type de croissance ? A. interne B. externe C. conjointe"},
        ]
        self.envoyes = []
        self.patches = [
            mock.patch.object(main, "p0_enabled", return_value=False),
            mock.patch.object(main, "send_whatsapp", side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg)),
            mock.patch.object(main, "send_whatsapp_typing_indicator", return_value=None),
            mock.patch.object(main, "charger_historique_conv", return_value=[]),
            mock.patch.object(main, "sauver_historique_conv", return_value=None),
            mock.patch.object(main, "mark_first_learning_request", side_effect=lambda phone, profile: profile),
        ]
        for p in self.patches:
            p.start()
        self.akili = mock.patch.object(main, "get_akili_response", return_value="Oui, c'est la croissance externe.")
        self.akili_mock = self.akili.start()

    def tearDown(self):
        self.akili.stop()
        for p in self.patches:
            p.stop()
        main.conversations.clear()

    def test_lettre_seule_appelle_akili_et_garde_b_dans_historique(self):
        texte = main.build_short_answer_prompt(self.phone, "B")
        self.assertTrue(main.mentions_user_document_without_content(texte),
                        "le prompt reecrit contient bien des mots 'document' (condition du bug)")
        main.answer_learning_request(self.phone, dict(self.profile), texte)
        self.assertTrue(self.akili_mock.called, "Akili doit etre appele")
        self.assertFalse(any("lire clairement le contenu du fichier" in m for m in self.envoyes))
        cle = f"{self.phone}:BAC_TECHNIQUE:G1:ECO:etude"
        self.assertEqual(main.conversations[cle][-2], {"role": "user", "content": "B"})

    def test_vraie_demande_sur_un_fichier_absent_reste_bloquee(self):
        main.answer_learning_request(self.phone, dict(self.profile), "corrige l'exercice 1 du PDF")
        self.assertFalse(self.akili_mock.called)
        self.assertTrue(any("lire clairement le contenu du fichier" in m for m in self.envoyes))


if __name__ == "__main__":
    unittest.main()
