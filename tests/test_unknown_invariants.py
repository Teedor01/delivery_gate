"""Audit correction 7: UNKNOWN is never transformed into PASS through defaults."""
import unittest
from delivery_gate.models import Provenance, ProvStatus, SourceType
from tests.helpers import *

UNKNOWN_PROV = dict(st=S.SourceType.UNKNOWN, ref="unknown", ps=S.ProvStatus.UNKNOWN)


class UnknownNeverBecomesPass(unittest.TestCase):
    def test_missing_paypal_status(self):
        a = assess(REG, S.unauth_case(status=None))
        self.assertEqual(a.protection_assessment, PA.UNKNOWN)
        self.assertEqual(a.observed_inputs["paypal_seller_protection_status"]["state"], "NOT_SUPPLIED")

    def test_unknown_status_semantics(self):
        a = assess(REG, S.unauth_case(status="ELIGIBLE"))
        self.assertEqual(a.protection_assessment, PA.UNKNOWN)
        self.assertEqual(a.observed_inputs["paypal_seller_protection_status"]["status_semantics"], "UNKNOWN")
        self.assertEqual(a.condition("unauth.condition.paypal_mark")["POLICY_STATUS_MAPPING"], "UNKNOWN")

    def test_missing_funding_source_is_explicit_and_not_defaulted(self):
        a = assess(REG, S.inr_case(route="CARD_ISSUER_CHARGEBACK", funding=None))
        self.assertEqual(a.observed_inputs["funding_source"], {"state": "NOT_SUPPLIED", "value": None})
        self.assertEqual(a.protection_assessment, PA.NOT_COVERED)             # excluded route; funding stays visibly unknown
        oi = next(o for o in a.open_items if o["open_id"].endswith("funding_source_not_supplied"))
        self.assertEqual(oi["state"], "UNKNOWN")
        self.assertIn("inference", oi["detail"])
        b = assess(REG, S.inr_case(funding=None))                             # PayPal route: still not defaulted to CARD
        self.assertEqual(b.observed_inputs["funding_source"]["state"], "NOT_SUPPLIED")
        self.assertNotEqual(b.observed_inputs["funding_source"]["value"], "CARD")

    def test_unknown_funding_value_is_not_treated_as_card(self):
        a = assess(REG, S.inr_case(route="CARD_ISSUER_CHARGEBACK", funding="UNKNOWN"))
        self.assertTrue(any(o["open_id"].endswith("funding_source_not_supplied") for o in a.open_items))

    def test_unknown_route(self):
        self.assertEqual(assess(REG, S.inr_case(route="OTHER_UNKNOWN")).protection_assessment, PA.UNKNOWN)
        b = assess(REG, S.inr_case().with_changes(remove_facts=["route"]))
        self.assertEqual((b.protection_assessment, b.reason_codes), (PA.UNKNOWN, ("ROUTE_MISSING",)))
        self.assertEqual(b.observed_inputs["route"]["state"], "NOT_SUPPLIED")

    def test_unknown_jurisdiction(self):
        a = assess(REG, S.inr_case().with_changes(remove_facts=["merchant_account_country"]))
        self.assertEqual(a.protection_assessment, PA.UNKNOWN)
        self.assertEqual(a.observed_inputs["merchant_account_country"]["state"], "NOT_SUPPLIED")

    def test_unknown_provenance_on_a_gating_fact_is_treated_as_not_supplied(self):
        f = S.tf("merchant_account_country", "US", **{"st": S.SourceType.UNKNOWN, "ref": "unknown", "ps": S.ProvStatus.UNKNOWN})
        a = assess(REG, S.inr_case().with_changes(set_facts=[f]))
        self.assertEqual((a.protection_assessment, a.reason_codes), (PA.UNKNOWN, ("JURISDICTION_UNKNOWN",)))
        self.assertEqual(a.observed_inputs["merchant_account_country"], {"state": "PROVENANCE_UNKNOWN", "value": None})

    def test_unknown_provenance_on_evidence_cannot_demonstrate(self):
        c = S.inr_case().with_changes(set_evidence=[S.ev("delivery_record", True, **UNKNOWN_PROV)])
        a = assess(REG, c)
        chk = a.check("inr.proof_of_delivery.record")
        self.assertEqual((chk.status, chk.reason_code), (ES.NEEDS_HUMAN_REVIEW, "UNKNOWN_PROVENANCE"))
        self.assertTrue(a.needs_human_review)
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)

    def test_unresolved_exclusion_is_not_defaulted_to_cleared(self):
        a = assess(REG, S.inr_case().with_changes(remove_evidence=["shipped_after_advised_not_to_release"]))
        self.assertEqual(a.evidence_fields_assessment, EFA.REQUIREMENT_FIELDS_DEMONSTRATED)
        self.assertEqual((a.protection_assessment, a.reason_codes), (PA.UNKNOWN, ("UNRESOLVED_EXCLUSION",)))
        self.assertEqual(a.exclusions[0]["state"], "NOT_EVALUATED")
        b = assess(REG, S.inr_case().with_changes(set_evidence=[S.ev("shipped_after_advised_not_to_release", False, **UNKNOWN_PROV)]))
        self.assertEqual(b.protection_assessment, PA.UNKNOWN)

    def test_every_single_input_removal_never_yields_a_pass_unless_the_input_is_irrelevant(self):
        case = S.inr_case()
        irrelevant = {"funding_source", "transaction_amount", "currency", "shipped_to_transaction_address"}
        names = [("fact", f.name) for f in case.transaction_facts] + [("ev", e.name) for e in case.evidence]
        for kind, n in names:
            c = case.with_changes(remove_facts=[n]) if kind == "fact" else case.with_changes(remove_evidence=[n])
            a = assess(REG, c)
            if n in irrelevant:
                self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES, n)
            else:
                self.assertNotEqual(a.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES, f"removing {n} became a pass")

    def test_unauthorized_never_passes_while_the_mapping_is_unknown(self):
        case = S.unauth_case()
        self.assertNotEqual(assess(REG, case).protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)
        for n in [f.name for f in case.transaction_facts] + [e.name for e in case.evidence]:
            for c in (case.with_changes(remove_facts=[n]), case.with_changes(remove_evidence=[n])):
                self.assertNotEqual(assess(REG, c).protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES, n)

    def test_removing_an_evidence_requirement_input_flips_the_field_assessment(self):
        case = S.unauth_case()
        self.assertEqual(assess(REG, case).evidence_fields_assessment, EFA.REQUIREMENT_FIELDS_DEMONSTRATED)
        for n in ("shipment_record", "tracking_number", "shipment_date", "recipient_address", "redirect_detected", "response_to_paypal"):
            self.assertEqual(assess(REG, case.with_changes(remove_evidence=[n])).evidence_fields_assessment,
                             EFA.REQUIREMENT_FIELDS_NOT_DEMONSTRATED, n)

    def test_snad_without_amount_keeps_the_amount_unknown(self):
        a = assess(REG, S.snad_case().with_changes(remove_facts=["transaction_amount"]))
        self.assertIsNone(a.exposure["exposure_floor"])
        self.assertIsNone(a.exposure["known_lower_bound"])
        self.assertIn("transaction_amount", [u["cost_id"] for u in a.exposure["unknown_additional_costs"]])


if __name__ == "__main__":
    unittest.main()
