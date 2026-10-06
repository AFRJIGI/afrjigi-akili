"""L'enonce de l'exercice reste envoye a Akili meme quand il sort de l'historique (test compta
du 6 oct. : apres 3 echanges, Akili redemandait les montants et calculait la TVA sur le TTC)."""
import unittest
from unittest import mock

import main

ENONCE = "Le 5 octobre, achat de marchandises à crédit pour 500 000 F HT, TVA 18 %. Passe l'écriture."
CLE = "22500000082:BAC_TECHNIQUE:G2:COMPTA_FIN:etude"


class Reponse:
    status_code = 200
    text = ""

    def json(self):
        return {"reponse": "Quel est le montant de la TVA ?"}


class RetenirEnonceTests(unittest.TestCase):
    def test_premier_message_retenu(self):
        self.assertTrue(main.doit_retenir_enonce(ENONCE, True))
        self.assertTrue(main.doit_retenir_enonce("Je veux réviser la comptabilité", True))
        self.assertFalse(main.doit_retenir_enonce("b", True))

    def test_reponses_de_l_eleve_ne_remplacent_pas_l_enonce(self):
        for reponse in ["90000", "a", "TTC = HT + TVA", "J'obtiens 590 000 pour le TTC",
                        "Débit 601 : 500 000, Débit 4452 : 90 000, Crédit 401 : 590 000 et c'est équilibré"]:
            self.assertFalse(main.doit_retenir_enonce(reponse, False, ENONCE), reponse)

    def test_nouvel_exercice_retenu(self):
        nouveau = "Nouvel exercice : le 8 octobre, vente de marchandises au comptant pour 300 000 F HT, TVA 18 %."
        self.assertTrue(main.doit_retenir_enonce(nouveau, False, ENONCE))
        # apres une simple demande sans chiffres, le premier message chiffre devient l'enonce
        chiffre = "Le 5 octobre, achat de marchandises à crédit pour 500 000 F HT avec une TVA de 18 %"
        self.assertTrue(main.doit_retenir_enonce(chiffre, False, "Je veux réviser la comptabilité"))

    def test_enonce_par_conversation(self):
        profil = {"enonce_en_cours": {"cle": CLE, "texte": ENONCE}}
        self.assertEqual(main.enonce_en_cours(profil, CLE), ENONCE)
        self.assertEqual(main.enonce_en_cours(profil, CLE.replace("COMPTA_FIN", "MATHS_FIN")), "")


class ExerciceProposeParAkiliTests(unittest.TestCase):
    def test_nouvel_exercice_retenu_depuis_le_marqueur(self):
        reponse = ("C'est une écriture parfaite ! Bravo !\n\nPassons à un nouvel exercice. Le 7 octobre, "
                   "l'entreprise vend des marchandises à crédit pour 800 000 F HT. Quels comptes ?")
        extrait = main.exercice_propose_par_akili(reponse)
        self.assertTrue(extrait.startswith("Passons à un nouvel exercice."))
        self.assertIn("800 000 F HT", extrait)
        self.assertNotIn("Bravo", extrait)

    def test_question_d_une_etape_ignoree(self):
        self.assertEqual(main.exercice_propose_par_akili("Exercice 1, question 2 : quel est le montant de la TVA ?"), "")
        self.assertIn("Voici un exercice", main.exercice_propose_par_akili("Voici un exercice : résous 2x + 3 = 7."))


class EnvoiEnonceTests(unittest.TestCase):
    def envoyer(self, historique, enonce):
        envoye = {}

        def faux_post(url, files=None, timeout=None, **k):
            envoye.update({k2: v[1] for k2, v in (files or {}).items()})
            return Reponse()

        with mock.patch.object(main.requests, "post", side_effect=faux_post):
            main.get_akili_response("90000", "COMPTA_FIN", "G2", historique, phone="225",
                                    type_examen="BAC_TECHNIQUE", mode="etude", enonce=enonce)
        return envoye["question"]

    def test_enonce_sorti_de_l_historique_est_renvoye(self):
        historique = []
        for i in range(5):
            historique += [{"role": "user", "content": f"réponse {i}"},
                           {"role": "assistant", "content": f"question {i} ?"}]
        question = self.envoyer(historique, ENONCE)
        self.assertIn("ENONCE DE L'EXERCICE EN COURS", question)
        self.assertIn("500 000 F HT", question)
        self.assertLess(question.index("ENONCE DE L'EXERCICE"), question.index("HISTORIQUE RECENT"))

    def test_exercice_d_akili_pas_en_double(self):
        reponse = "Bravo ! Passons à un nouvel exercice. Le 7 octobre, vente à crédit pour 800 000 F HT."
        enonce = "Exercice proposé par Akili : " + main.exercice_propose_par_akili(reponse)
        historique = [{"role": "user", "content": "Débit 601..."}, {"role": "assistant", "content": reponse}]
        self.assertNotIn("ENONCE DE L'EXERCICE EN COURS", self.envoyer(historique, enonce))
        self.assertIn("ENONCE DE L'EXERCICE EN COURS", self.envoyer(historique[:1] * 6, enonce))

    def test_pas_de_doublon_si_l_enonce_est_encore_dans_l_historique(self):
        historique = [{"role": "user", "content": ENONCE}, {"role": "assistant", "content": "Quels comptes ?"}]
        self.assertNotIn("ENONCE DE L'EXERCICE EN COURS", self.envoyer(historique, ENONCE))


if __name__ == "__main__":
    unittest.main()
