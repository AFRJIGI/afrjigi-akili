import unittest
from template_replies import retention_template_text
from marketing_consent import detect_marketing_consent_command, OPTED_OUT


class TemplateRepliesTests(unittest.TestCase):
    def reply(self, text, payload="opaque-meta-payload"):
        return retention_template_text({"type": "button", "button": {"text": text, "payload": payload}})

    def test_unsubscribe_routes_to_persisted_consent_command(self):
        self.assertEqual(detect_marketing_consent_command(self.reply("Se désinscrire")), OPTED_OUT)

    def test_subject_routes(self):
        self.assertEqual(self.reply("Maths"), "Maths")
        self.assertEqual(self.reply("Autre matière"), "changer de matiere")

    def test_unknown_payload_cannot_grant_consent(self):
        self.assertIsNone(self.reply("Oui", "OUI MARKETING"))
        self.assertIsNone(retention_template_text({"type": "button"}))

    def test_existing_interactive_buttons_are_untouched(self):
        self.assertIsNone(retention_template_text({"type": "interactive", "interactive": {"button_reply": {"id": "avis_oui"}}}))


if __name__ == "__main__":
    unittest.main()
