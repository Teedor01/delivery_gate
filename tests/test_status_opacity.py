import json, shutil, tempfile, unittest
from pathlib import Path
from delivery_gate.engine import ALL_EVALUATOR_NAMES
from delivery_gate.registry import PolicyRegistry, RegistryError, POLICY_DIR
from tests.helpers import *

COND = "unauth.condition.paypal_mark"


def registry_with_condition(mutator):
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(POLICY_DIR, tmp / "policy")
    p = tmp / "policy" / "rules" / "us.sp.unauthorized.json"
    d = json.loads(p.read_text())
    mutator(d["policy_conditions"][0])
    p.write_text(json.dumps(d))
    return PolicyRegistry(tmp / "policy", ALL_EVALUATOR_NAMES)


class StatusIsOpaque(unittest.TestCase):
    TOKENS = ["ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE", "SOMETHING_NEW"]

    def normalised(self, token):
        d = assess(REG, S.unauth_case(status=token)).core_dict()
        for c in d["policy_conditions"]:
            c["observed_value"] = "<token>"
        d["observed_inputs"]["paypal_seller_protection_status"]["value"] = "<token>"
        d["explanation"] = [e.replace(repr(token), "<token>") for e in d["explanation"]]
        return d

    def test_every_token_produces_the_identical_assessment(self):
        base = self.normalised(self.TOKENS[0])
        for t in self.TOKENS[1:]:
            self.assertEqual(self.normalised(t), base, t)      

    def test_no_token_satisfies_or_fails_the_policy_condition(self):
        for t in self.TOKENS:
            a = assess(REG, S.unauth_case(status=t))
            c = a.condition(COND)
            self.assertEqual((c["state"], c["POLICY_STATUS_MAPPING"], c["status_semantics"]), ("UNRESOLVED", "UNKNOWN", "UNKNOWN"), t)
            self.assertEqual(c["observation"], "PAYPAL_STATUS_OBSERVED")
            self.assertNotEqual(a.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES, t)
            self.assertNotEqual(a.protection_assessment, PA.NOT_COVERED, t)

    def test_status_never_affects_other_categories(self):
        a = assess(REG, S.inr_case().with_changes(set_facts=[S.tf("paypal_seller_protection_status", "PARTIALLY_ELIGIBLE")]))
        b = assess(REG, S.inr_case())
        self.assertEqual(a.protection_assessment, b.protection_assessment)
        self.assertEqual(a.observed_inputs["paypal_seller_protection_status"]["status_semantics"], "UNKNOWN")

    def test_rule_data_cannot_smuggle_tokens_without_an_established_mapping(self):
        with self.assertRaises(RegistryError):
            registry_with_condition(lambda c: c["mapping"].update(satisfied_values=["PARTIALLY_ELIGIBLE"]))
        with self.assertRaises(RegistryError):
            registry_with_condition(lambda c: c["mapping"].update(unsatisfied_values=["NOT_ELIGIBLE"]))
        with self.assertRaises(RegistryError):                     
            registry_with_condition(lambda c: c["mapping"].update(established=True, satisfied_values=["ELIGIBLE"]))
        with self.assertRaises(RegistryError):
            registry_with_condition(lambda c: c.update(status_semantics="ESTABLISHED"))

    def test_mapping_only_takes_effect_when_established_by_a_cited_passage(self):
        """The escape hatch the audit allows: only a rule that cites establishing primary documentation can map a token."""
        reg = registry_with_condition(lambda c: c["mapping"].update(
            established=True, establishing_passage_ids=["API.sp.status_desc"], satisfied_values=["ELIGIBLE"],
            unsatisfied_values=["NOT_ELIGIBLE"]))
        self.assertEqual(assess(reg, S.unauth_case(status="ELIGIBLE")).condition(COND)["state"], "SATISFIED")
        self.assertEqual(assess(reg, S.unauth_case(status="NOT_ELIGIBLE")).protection_assessment, PA.NOT_COVERED)
        self.assertEqual(assess(reg, S.unauth_case(status="PARTIALLY_ELIGIBLE")).condition(COND)["state"], "UNRESOLVED")
        self.assertFalse(REG.rules["us.sp.unauthorized"].raw["policy_conditions"][0]["mapping"]["established"])


if __name__ == "__main__":
    unittest.main()
