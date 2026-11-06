"""0130 : la reprise de debut de journee ne s'ajoute plus a une reponse d'Akili qui finit deja par une question."""
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main

PHONE = "+2250700000000"
NOW = datetime.now(timezone.utc)
HIER = (NOW - timedelta(days=1)).isoformat()


def profil():
    return {"matiere": "MATHS", "serie": "D", "type_examen": "BAC", "profile_ready": True,
            "onboarding_completed_at": NOW.isoformat()}


def seance():
    return {"nb_echanges": 1, "precedente_fin": HIER, "precedente_matiere": "MATHS"}


class RepriseSurQuestionTests(unittest.TestCase):
    def setUp(self):
        main._reprise_notee.clear()
        for nom, kw in (("mini_test_eligible", {"return_value": True}), ("sauver_etat_mini_test", {}),
                        ("save_whatsapp_event", {})):
            p = mock.patch.object(main, nom, **kw)
            p.start()
            self.addCleanup(p.stop)

    def _reprise(self, reponse):
        etat = {"mini_tests": {"MATHS": {"propositions_debut": 3}}}
        with mock.patch.object(main, "charger_etat_mini_test", return_value=etat), \
             mock.patch.object(main, "send_whatsapp") as envoi:
            return main.reprise_debut_de_seance(PHONE, profil(), seance(), reponse=reponse), envoi

    def test_detecte_une_question_ou_un_qcm(self):
        self.assertTrue(main.reponse_attend_une_reponse("Combien vaut C(7, 4)? a) 21 b) 28"))
        self.assertTrue(main.reponse_attend_une_reponse("Quelle est la bonne option ? a, b ou c. Réponds par une lettre"))
        self.assertTrue(main.reponse_attend_une_reponse("Calcule f(2) et dis-moi ce que tu trouves. Réponds ici."))
        self.assertFalse(main.reponse_attend_une_reponse("Bonjour ! Content de te revoir."))
        self.assertFalse(main.reponse_attend_une_reponse(""))
        self.assertFalse(main.reponse_attend_une_reponse(None))

    def test_pas_de_reprise_apres_une_question(self):
        envoye, envoi = self._reprise("Dans ton exercice, quelle est la dérivée de x² ?")
        self.assertFalse(envoye)
        envoi.assert_not_called()

    def test_reprise_apres_un_simple_bonjour(self):
        envoye, envoi = self._reprise("Bonjour ! Content de te revoir.")
        self.assertTrue(envoye)
        envoi.assert_called_once()

    def test_sans_reponse_fournie_comportement_inchange(self):
        envoye, _ = self._reprise("")
        self.assertTrue(envoye)


if __name__ == "__main__":
    unittest.main()
