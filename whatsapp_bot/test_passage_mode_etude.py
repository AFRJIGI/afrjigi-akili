import unittest
from unittest import mock

import main


def msg(role, texte):
    return {"role": role, "content": texte}


class CopierHistoriqueTests(unittest.TestCase):
    def appeler(self, ancien, nouveau, memoire=None):
        memoire = memoire if memoire is not None else {}
        chargements = {"EXAMEN": ancien, "ETUDE": nouveau}
        sauvegardes = []
        with mock.patch.object(main, "charger_historique_conv", side_effect=lambda cle: chargements.get(cle, [])), \
                mock.patch.object(main, "sauver_historique_conv", side_effect=lambda cle, h: sauvegardes.append((cle, h))), \
                mock.patch.object(main, "conversations", memoire):
            main.copier_historique("EXAMEN", "ETUDE")
        return memoire, sauvegardes

    def test_historique_etude_vide_recoit_tout_l_examen(self):
        ancien = [msg("user", "propose-moi un exercice"), msg("assistant", "Exercice (Probabilités) urne")]
        memoire, sauvegardes = self.appeler(ancien, [])
        self.assertEqual(memoire["ETUDE"], ancien)
        self.assertEqual(len(sauvegardes), 1)

    def test_ancien_exercice_d_etude_ne_masque_plus_le_sujet_d_examen(self):
        etude = [msg("user", "dérivées"), msg("assistant", "Exercice dérivées f(x) = x³")]
        examen = [msg("user", "propose-moi un exercice"), msg("assistant", "Exercice (Probabilités) urne")]
        memoire, _ = self.appeler(examen, etude)
        self.assertEqual(memoire["ETUDE"][-1]["content"], "Exercice (Probabilités) urne")
        self.assertEqual(memoire["ETUDE"][0]["content"], "dérivées")

    def test_pas_de_doublon_si_deja_copie(self):
        examen = [msg("user", "propose-moi un exercice"), msg("assistant", "Exercice (Probabilités) urne")]
        memoire, sauvegardes = self.appeler(examen, list(examen))
        self.assertEqual(sauvegardes, [])

    def test_historique_limite(self):
        etude = [msg("user", f"q{i}") for i in range(main.HISTORIQUE_MAX)]
        examen = [msg("assistant", "Exercice (Probabilités) urne")]
        memoire, _ = self.appeler(examen, etude)
        self.assertEqual(len(memoire["ETUDE"]), main.HISTORIQUE_MAX)
        self.assertEqual(memoire["ETUDE"][-1]["content"], "Exercice (Probabilités) urne")


if __name__ == "__main__":
    unittest.main()
