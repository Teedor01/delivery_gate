import unittest
from tests.helpers import *


class INR(unittest.TestCase):
    def test_01_us_paypal_route_all_requirements_demonstrated(self):
        a = assess(REG, S.inr_case())
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)
        self.assertEqual(a.blocking(), [])
        self.assertEqual(len(a.checks), 9)
        self.assertEqual(a.check("inr.preorder_ship_timing").status, ES.NOT_APPLICABLE)
        self.assertEqual(a.reason_codes, ("MODELED_REQUIREMENTS_DEMONSTRATED",))
        self.assertIn("PayPal determines eligibility in its sole discretion", text(a))
        self.assertIn("SP.discretion", text(a))
        self.assertTrue(any(n["id"] == "signature_confirmation" and "DO NOT MODEL" in n["reason"] for n in a.not_modeled))

    def test_02_us_paypal_route_delivery_evidence_missing(self):
        c = S.inr_case().with_changes(remove_evidence=["delivery_record", "tracking_number", "delivery_date", "delivered_status"])
        a = assess(REG, c)
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        self.assertEqual(blocking_ids(a), ["inr.proof_of_delivery.date_and_status", "inr.proof_of_delivery.record",
                                           "inr.proof_of_delivery.tracking_number"])
        self.assertTrue(all(x.reason_code == "MISSING_FACT" for x in a.blocking()))
        self.assertIn("inr.proof_of_delivery.record", text(a))
        self.assertIn("SP.inr.additional", text(a))

    def test_03_us_issuer_route_card_funded(self):
        a = assess(REG, S.inr_case(route="CARD_ISSUER_CHARGEBACK", funding="CARD"))
        self.assertEqual(a.protection_assessment, PA.NOT_COVERED)
        self.assertEqual(a.reason_codes, ("ROUTE_EXCLUDED",))
        self.assertEqual(a.checks, ())                   
        self.assertIn("SP.excl.inr_issuer", a.gate("inr.gate.route").passage_ids)
        self.assertIn("inr.gate.route", text(a))

    def test_04_us_redirected_shipment(self):
        c = S.inr_case().with_changes(set_evidence=[S.ev("redirect_detected", True)])
        a = assess(REG, c)
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        self.assertEqual(blocking_ids(a), ["inr.no_redirect"])
        self.assertEqual(a.check("inr.no_redirect").status, ES.CONTRADICTED)
        self.assertIn("SP.basic.redirect", text(a))

    def test_05_non_us_merchant(self):
        a = assess(REG, S.inr_case(country="DE"))
        self.assertEqual(a.protection_assessment, PA.UNSUPPORTED_JURISDICTION)
        self.assertEqual(a.reason_codes, ("JURISDICTION_MISMATCH",))
        self.assertEqual(a.checks, ())
        self.assertIn("SP.basic.us_address", text(a))

    def test_06_unknown_jurisdiction(self):
        c = S.inr_case().with_changes(remove_facts=["merchant_account_country"])
        a = assess(REG, c)
        self.assertEqual(a.protection_assessment, PA.UNKNOWN)
        self.assertEqual(a.reason_codes, ("JURISDICTION_UNKNOWN",))
        self.assertEqual(a.checks, ())

    def test_07_missing_transaction_address(self):
        c = S.inr_case().with_changes(remove_facts=["transaction_details_address"])
        a = assess(REG, c)
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        self.assertEqual(blocking_ids(a), ["inr.proof_of_delivery.recipient_address_matches"])
        self.assertEqual(a.check("inr.proof_of_delivery.recipient_address_matches").reason_code, "MISSING_FACT")
        self.assertIn("transaction_details_address", a.check("inr.proof_of_delivery.recipient_address_matches").detail)
        self.assertEqual(a.check("inr.ship_to_transaction_address").reason_code, "ASSERTED_ONLY")

    def test_08_conflicting_delivery_evidence(self):
        base = S.inr_case()
        c = add_evidence(base, S.ev("delivered_status", "RETURNED", ref="fixture:carrier-FX2"))
        a = assess(REG, c)
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        chk = a.check("inr.proof_of_delivery.date_and_status")
        self.assertEqual(chk.status, ES.CONTRADICTED)
        self.assertEqual(chk.reason_code, "CONFLICTING_EVIDENCE")
        self.assertTrue(chk.needs_human_review and a.needs_human_review)
        self.assertIn("conflicting", text(a))


if __name__ == "__main__":
    unittest.main()
