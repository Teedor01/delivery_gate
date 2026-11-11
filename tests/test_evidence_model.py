"""Audit corrections 2, 4, 5: artifact fields vs PayPal sufficiency; conservative merchant assertions; strict addresses."""
import json, unittest
from tests.helpers import *

TOKEN = "PAYPAL_ACCEPTS_THIS_ARTIFACT_AS_SUFFICIENT_PROOF"


class ArtifactFieldsVsPayPalAcceptance(unittest.TestCase):
    def test_a_fully_demonstrated_case_establishes_fields_never_acceptance(self):
        a = assess(REG, S.inr_case())
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)
        self.assertEqual(a.evidence_fields_assessment, EFA.REQUIREMENT_FIELDS_DEMONSTRATED)
        self.assertEqual(a.paypal_acceptance, "NOT_ESTABLISHED")
        for c in a.checks:
            self.assertEqual(c.paypal_acceptance, "NOT_ESTABLISHED", c.check_id)
            self.assertIn(TOKEN, c.does_not_establish, c.check_id)
            if c.status == ES.DEMONSTRATED:
                self.assertTrue(c.establishes, c.check_id)         # a field-level statement, e.g. 'carrier_record contains ...'
        self.assertIn("not a finding that PayPal accepts", text(a))

    def test_the_token_is_only_ever_listed_under_does_not_establish(self):
        d = assess(REG, S.inr_case()).to_dict()
        def walk(o, path=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    yield from walk(v, f"{path}.{k}")
            elif isinstance(o, list):
                for v in o:
                    yield from walk(v, path)
            elif isinstance(o, str) and "PAYPAL_ACCEPTS" in o:
                yield path
        self.assertEqual({p for p in walk(d)}, {".checks.does_not_establish"})
        self.assertNotIn("PAYPAL_WILL_ACCEPT_EVIDENCE", json.dumps(d))

    def test_establishes_statements_are_field_level_not_acceptance_claims(self):
        for r in REG.rules.values():
            for c in r.raw["checks"]:
                low = c["establishes"].lower()
                self.assertNotIn("accept", low, c["check_id"])
                self.assertNotIn("sufficient", low, c["check_id"])
                self.assertNotIn("proves", low, c["check_id"])
                self.assertIs(c["sufficiency_stated_by_policy"], False)

    def test_carrier_payload_with_every_field_still_does_not_imply_acceptance(self):
        a = assess(REG, S.inr_case())
        rec = a.check("inr.proof_of_delivery.record")
        self.assertEqual(rec.status, ES.DEMONSTRATED)
        self.assertEqual(rec.establishes, "carrier_record is present from a shipping-company source type")
        self.assertEqual(rec.paypal_acceptance, "NOT_ESTABLISHED")
        self.assertIn("interpretation about what the artifact is", rec.interpretation_note)
        self.assertIn("NOT a finding that PayPal accepts", rec.interpretation_note)

    def test_merchant_statement_is_never_the_carrier_record(self):
        a = assess(REG, S.inr_case().with_changes(set_evidence=[S.merchant("delivery_record", True)]))
        self.assertEqual(a.check("inr.proof_of_delivery.record").reason_code, "SOURCE_TYPE_NOT_CARRIER")
        self.assertEqual(a.evidence_fields_assessment, EFA.REQUIREMENT_FIELDS_NOT_DEMONSTRATED)


class MerchantAssertionsStayConservative(unittest.TestCase):
    def test_asserted_only_is_kept_and_labelled_uncorroborated(self):
        c = S.inr_case().with_changes(remove_facts=["transaction_details_address"])
        a = assess(REG, c)
        ship = a.check("inr.ship_to_transaction_address")
        self.assertEqual((ship.status, ship.reason_code, ship.corroboration), (ES.DEMONSTRATED, "ASSERTED_ONLY", "MERCHANT_ASSERTED_ONLY"))
        self.assertIn("inr.ship_to_transaction_address", a.uncorroborated_requirements)

    def test_assertion_is_not_equivalent_to_corroborated_evidence(self):
        a = assess(REG, S.inr_case())
        self.assertEqual(a.check("inr.ship_to_transaction_address").corroboration, "CORROBORATED")      # derived from the carrier address
        self.assertEqual(a.check("inr.proof_of_delivery.record").corroboration, "CORROBORATED")
        self.assertEqual(a.check("inr.timely_response").corroboration, "MERCHANT_ASSERTED_ONLY")        # merchant-supplied status
        self.assertEqual(a.uncorroborated_requirements, ("inr.timely_response",))

    def test_assertion_cannot_override_a_contradicting_carrier_address(self):
        c = S.inr_case().with_changes(set_evidence=[S.ev("recipient_address", S.WRONG_ADDR)])   # assertion still says True
        ship = assess(REG, c).check("inr.ship_to_transaction_address")
        self.assertEqual((ship.status, ship.reason_code), (ES.CONTRADICTED, "ADDRESS_MISMATCH"))

    def test_merchant_sourced_address_is_not_corroboration(self):
        c = S.inr_case().with_changes(set_evidence=[S.merchant("recipient_address", S.TD_ADDR)])
        a = assess(REG, c)
        self.assertEqual(a.check("inr.proof_of_delivery.recipient_address_matches").corroboration, "MERCHANT_ASSERTED_ONLY")
        self.assertIn("inr.proof_of_delivery.recipient_address_matches", a.uncorroborated_requirements)


class AddressMatchingStaysStrict(unittest.TestCase):
    def with_line1(self, line1):
        addr = dict(S.TD_ADDR, line1=line1)
        return assess(REG, S.inr_case().with_changes(set_evidence=[S.ev("recipient_address", addr)]))

    def test_case_punctuation_and_whitespace_normalise(self):
        a = self.with_line1("  1   MARKET   st. ")
        self.assertEqual(a.check("inr.proof_of_delivery.recipient_address_matches").status, ES.DEMONSTRATED)

    def test_st_and_street_are_not_silently_equated(self):
        a = self.with_line1("1 Market Street")                         # TD address says "1 Market St"
        m = a.check("inr.proof_of_delivery.recipient_address_matches")
        self.assertEqual((m.status, m.reason_code), (ES.CONTRADICTED, "ADDRESS_MISMATCH"))
        self.assertTrue(m.needs_human_review and a.needs_human_review)
        self.assertIn("no fuzzy matching", m.detail)
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)

    def test_abbreviation_in_the_other_direction_also_mismatches(self):
        self.assertEqual(self.with_line1("1 Market Str").check("inr.ship_to_transaction_address").status, ES.CONTRADICTED)


if __name__ == "__main__":
    unittest.main()
