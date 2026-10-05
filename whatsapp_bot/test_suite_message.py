"""Message coupe par WhatsApp : l'historique garde ce qui est parti, "suite" envoie le reste."""
import unittest
from unittest import mock

import main
from test_qualite_corrections import PHONE, PRET, Base, texte

LONG = ("La loi de Hooke relie la contrainte normale σ et l'allongement relatif ε. " * 14
        + "Quand cette loi cesse-t-elle d'être applicable ?")


class DecoupageTests(unittest.TestCase):
    def test_reste_et_texte_envoye(self):
        envoye = main.texte_envoye(LONG)
        reste = main.reste_non_envoye(LONG)
        self.assertLessEqual(len(envoye), 850)
        self.assertTrue(envoye.endswith(main.CONTINUATION_WHATSAPP))
        self.assertIn("cesse-t-elle", reste)
        self.assertNotIn("cesse-t-elle", envoye)
        debut = envoye[:-len(main.CONTINUATION_WHATSAPP)].rstrip()
        complet = main.clean_whatsapp_response(LONG)
        self.assertEqual(" ".join((debut + " " + reste).split()), " ".join(complet.split()))
        self.assertEqual(main.reste_non_envoye("Court message ?"), "")
        self.assertEqual(main.split_whatsapp_message(LONG)[0], envoye)

    def test_demandes_de_suite(self):
        for t in ["suite", "La suite stp", "oui", "Oui, continue !", "vas-y", "ok", "continue svp", "et après ?"]:
            self.assertTrue(main.est_demande_de_suite(t), t)
        for t in ["b", "non", "la contrainte vaut 20 MPa", "oui c'est σ = E × ε", "suite de Fibonacci"]:
            self.assertFalse(main.est_demande_de_suite(t), t)


class SuiteTests(Base):
    def setUp(self):
        super().setUp()
        self.etat = dict(PRET, matiere="MECANIQUE_APPLIQUEE", serie="F2", type_examen="BAC_TECHNIQUE", mode="etude")
        self.historiques = {}
        self.extra = [
            mock.patch.object(main, "send_whatsapp",
                              side_effect=lambda phone, msg, *a, **k: self.envoyes.append(msg) or True),
            mock.patch.object(main, "sauver_historique_conv",
                              side_effect=lambda cle, h: self.historiques.__setitem__(cle, list(h))),
            mock.patch.object(main, "journal_session_ajouter", side_effect=lambda *a, **k: None),
        ]
        for p in self.extra:
            p.start()

    def tearDown(self):
        for p in self.extra:
            p.stop()
        super().tearDown()

    def test_suite_envoyee_sans_akili(self):
        with mock.patch.object(main, "charger_suite_en_attente", return_value="Quand cette loi cesse-t-elle ?"):
            resultat = self.envoyer(texte("suite", "s1"))
        self.assertEqual(resultat["reason"], "suite_reponse")
        self.assertEqual(self.envoyes, ["Quand cette loi cesse-t-elle ?"])
        self.assertEqual(self.akili, [])
        historique = next(iter(self.historiques.values()))
        self.assertEqual(historique[-1], {"role": "assistant", "content": main.texte_envoye("Quand cette loi cesse-t-elle ?")})

    def test_sans_suite_le_message_va_a_akili(self):
        with mock.patch.object(main, "charger_suite_en_attente", return_value=""):
            resultat = self.envoyer(texte("ok", "s2"))
        self.assertNotEqual(resultat.get("reason"), "suite_reponse")
        self.assertNotIn("Quand cette loi", " ".join(self.envoyes))


class HistoriqueTests(unittest.TestCase):
    def test_historique_garde_ce_qui_est_parti(self):
        profil = dict(PRET)
        cle = None
        with mock.patch.object(main, "get_akili_response", return_value=LONG), \
             mock.patch.object(main, "send_whatsapp", return_value=True), \
             mock.patch.object(main, "send_whatsapp_typing_indicator"), \
             mock.patch.object(main, "send_vector_formula_if_needed"), \
             mock.patch.object(main, "charger_historique_conv", return_value=[]), \
             mock.patch.object(main, "sauver_historique_conv") as sauver, \
             mock.patch.object(main, "journal_session_ajouter") as journal, \
             mock.patch.object(main, "mark_first_learning_request", side_effect=lambda phone, p: p):
            main.answer_learning_request(PHONE, profil, "explique la loi de Hooke")
        historique = sauver.call_args[0][1]
        self.assertEqual(historique[-1]["content"], main.texte_envoye(LONG))
        self.assertNotIn("cesse-t-elle", historique[-1]["content"])
        self.assertEqual(journal.call_args[0][-1], main.texte_envoye(LONG))
        main.user_profiles.pop(PHONE, None)


if __name__ == "__main__":
    unittest.main()
