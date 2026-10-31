import unittest
from tests.helpers import *


def all_cases():
    return [S.inr_case(), S.inr_case(country="DE"), S.inr_case(route="CARD_ISSUER_CHARGEBACK"), S.unauth_case(), S.unauth_case(status=None),
            S.snad_case(), S.inr_case().with_changes(remove_facts=["claim_category"]), S.inr_case(route="OTHER_UNKNOWN")]


class PolicyStatus(unittest.TestCase):
    def test_every_assessment_carries_policy_status_and_notice(self):
        for c in all_cases():
            a = assess(REG, c)
            d = a.to_dict()
            self.assertIn(d["policy_status"], ("UNREVIEWED", "NO_RULE_SELECTED"))
            self.assertIn("NOT an officially verified PayPal interpretation", d["display_notice"])
            self.assertTrue(a.explanation[0].startswith("policy_status="))
            if a.rule:
                self.assertEqual(d["policy_status"], "UNREVIEWED")
                self.assertEqual(a.rule["status"], "UNREVIEWED")
                self.assertTrue(all(s["source_hash"] is None and s["hash_status"] == "NOT_OBTAINED_RAW_BYTES" for s in a.rule["sources"]))

    def test_counterfactual_carries_policy_status_too(self):
        r = counterfactual(REG, S.inr_case(), Changes("noop"))
        self.assertEqual((r.current.policy_status, r.counterfactual.policy_status), ("UNREVIEWED", "UNREVIEWED"))
        self.assertIn("policy_status stays UNREVIEWED", "\n".join(r.explanation))

    def test_the_engine_runs_on_unreviewed_rules_without_source_hashes(self):
        self.assertTrue(all(r.status == "UNREVIEWED" for r in REG.rules.values()))
        self.assertEqual(assess(REG, S.inr_case()).protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)

    def test_no_output_describes_the_rules_as_verified(self):
        for c in all_cases():
            blob = json.dumps(assess(REG, c).to_dict()).lower()
            self.assertNotIn("officially verified paypal interpretation", blob.replace("not an officially verified paypal interpretation", ""))
            self.assertNotIn('"policy_status": "verified"', blob)


if __name__ == "__main__":
    unittest.main()
