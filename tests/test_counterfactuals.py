import unittest
from tests.helpers import *

DELIVERY = ("delivery_record", "tracking_number", "delivery_date", "delivered_status")


class Counterfactuals(unittest.TestCase):
    def test_18_missing_delivery_evidence_then_added(self):
        current = S.inr_case().with_changes(remove_evidence=list(DELIVERY))
        cf = Changes("merchant supplies carrier delivery record", set_evidence=(
            S.ev("delivery_record", True), S.ev("tracking_number", "1Z999AA10123456784"),
            S.ev("delivery_date", "2026-10-20"), S.ev("delivered_status", "DELIVERED")))
        r = counterfactual(REG, current, cf)
        self.assertEqual(r.current.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        self.assertEqual(r.counterfactual.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)
        self.assertTrue(r.result_changed)
        self.assertEqual(sorted(c["check_id"] for c in r.changed_requirements),
                         ["inr.proof_of_delivery.date_and_status", "inr.proof_of_delivery.record",
                          "inr.proof_of_delivery.tracking_number"])
        for c in r.changed_requirements:
            self.assertEqual(c["before"][0], "NOT_DEMONSTRATED")
            self.assertEqual(c["after"][0], "DEMONSTRATED")
        self.assertEqual(r.still_blocking, ())
        ex = "\n".join(r.explanation)
        self.assertIn("RESULT CHANGE: protection_assessment REQUIREMENTS_NOT_DEMONSTRATED -> REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES", ex)
        self.assertIn("policy requirement inr.proof_of_delivery.record", ex)
        self.assertIn("inr.proof_of_delivery.record", ex)
        self.assertIn("SP.inr.additional", ex)

    def test_19_wrong_shipping_address_then_corrected(self):
        current = S.inr_case().with_changes(set_evidence=[S.ev("recipient_address", S.WRONG_ADDR)])
        a = assess(REG, current)
        self.assertEqual(blocking_ids(a), ["inr.proof_of_delivery.recipient_address_matches", "inr.ship_to_transaction_address"])
        self.assertTrue(all(c.status == ES.CONTRADICTED for c in a.blocking()))
        cf = Changes("recipient address corrected to the Transaction Details address",
                     set_evidence=(S.ev("recipient_address", S.TD_ADDR),))
        r = counterfactual(REG, current, cf)
        self.assertEqual(r.counterfactual.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)
        self.assertEqual(sorted(c["check_id"] for c in r.changed_requirements),
                         ["inr.proof_of_delivery.recipient_address_matches", "inr.ship_to_transaction_address"])
        self.assertIn("SP.proof.address_match", "\n".join(r.explanation))
        self.assertIn("SP.basic.ship_to_txn_address", "\n".join(r.explanation))

    def test_20_issuer_route_to_paypal_route(self):
        current = S.inr_case(route="CARD_ISSUER_CHARGEBACK", funding="CARD")
        cf = Changes("buyer disputes through PayPal instead of the card issuer",
                     set_facts=(S.tf("route", "PAYPAL_DISPUTE"),))
        r = counterfactual(REG, current, cf)
        self.assertEqual(r.current.protection_assessment, PA.NOT_COVERED)
        self.assertEqual(r.counterfactual.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)
        g = next(g for g in r.changed_gates if g["gate_id"] == "inr.gate.route")
        self.assertEqual((g["before"][0], g["after"][0]), ("NOT_COVERED", "PASS"))
        self.assertTrue(all(c["before"][0] == "NOT_EVALUATED" for c in r.changed_requirements))
        self.assertEqual(len(r.changed_requirements), 9)
        ex = "\n".join(r.explanation)
        self.assertIn("CHANGED GATE inr.gate.route: NOT_COVERED (ROUTE_EXCLUDED) -> PASS (ROUTE_EVALUATED)", ex)
        self.assertIn("SP.discretion", ex)


if __name__ == "__main__":
    unittest.main()


class CounterfactualStructure(unittest.TestCase):
    """CURRENT_FACTS / COUNTERFACTUAL_FACTS / CHANGED_REQUIREMENTS / RESULT_CHANGE are separate, not a generic diff."""
    def setUp(self):
        self.cur = S.inr_case().with_changes(remove_evidence=list(DELIVERY))
        self.cf = Changes("add carrier record", set_evidence=(
            S.ev("delivery_record", True), S.ev("tracking_number", "1Z999AA10123456784"),
            S.ev("delivery_date", "2026-10-20"), S.ev("delivered_status", "DELIVERED")))
        self.r = counterfactual(REG, self.cur, self.cf)

    def test_four_distinct_parts(self):
        d = self.r.to_dict()
        for k in ("CURRENT_FACTS", "COUNTERFACTUAL_FACTS", "CHANGED_REQUIREMENTS", "RESULT_CHANGE"):
            self.assertIn(k, d)
        self.assertNotIn("EVIDENCE:delivery_record", d["CURRENT_FACTS"])
        self.assertIn("EVIDENCE:delivery_record", d["COUNTERFACTUAL_FACTS"])
        self.assertEqual(sorted(f["key"] for f in d["changed_facts"]),
                         ["EVIDENCE:delivered_status", "EVIDENCE:delivery_date", "EVIDENCE:delivery_record", "EVIDENCE:tracking_number"])
        self.assertEqual(d["RESULT_CHANGE"]["protection_assessment"],
                         {"before": "REQUIREMENTS_NOT_DEMONSTRATED", "after": "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES"})
        self.assertEqual(d["RESULT_CHANGE"]["evidence_fields_assessment"],
                         {"before": "REQUIREMENT_FIELDS_NOT_DEMONSTRATED", "after": "REQUIREMENT_FIELDS_DEMONSTRATED"})

    def test_names_the_policy_requirement_that_changed(self):
        req = next(c for c in self.r.changed_requirements if c["check_id"] == "inr.proof_of_delivery.record")
        self.assertEqual(req["kind"], "EXPLICIT_REQUIREMENT")
        self.assertIn("Proof of delivery is required", req["requirement"])
        self.assertIn("SP.inr.additional", req["passage_ids"])
        ex = "\n".join(self.r.explanation)
        self.assertIn('CHANGED REQUIREMENT - policy requirement inr.proof_of_delivery.record', ex)
        self.assertIn("Proof of delivery is required", ex)

    def test_no_op_counterfactual_reports_no_requirement_change(self):
        r = counterfactual(REG, S.inr_case(), Changes("no-op"))
        self.assertEqual(r.changed_requirements, ())
        self.assertFalse(r.result_changed)
        self.assertIn("CHANGED REQUIREMENTS: none", "\n".join(r.explanation))

    def test_unauthorized_counterfactual_changes_fields_but_not_the_unresolved_overall_result(self):
        cur = S.unauth_case(status="PARTIALLY_ELIGIBLE").with_changes(
            remove_evidence=["shipment_record", "tracking_number", "shipment_date"])
        cf = Changes("add carrier shipment record", set_evidence=(
            S.ev("shipment_record", True), S.ev("tracking_number", "1Z999AA10123456785"), S.ev("shipment_date", "2026-10-18")))
        r = counterfactual(REG, cur, cf)
        self.assertEqual(r.result_change["protection_assessment"], {"before": "REQUIREMENTS_NOT_DEMONSTRATED", "after": "UNKNOWN"})
        self.assertEqual(r.result_change["evidence_fields_assessment"],
                         {"before": "REQUIREMENT_FIELDS_NOT_DEMONSTRATED", "after": "REQUIREMENT_FIELDS_DEMONSTRATED"})
        self.assertEqual(sorted(c["check_id"] for c in r.changed_requirements),
                         ["unauth.proof.date", "unauth.proof.record", "unauth.proof.tracking_number"])
        self.assertEqual(r.counterfactual.reason_codes, ("POLICY_STATUS_MAPPING_UNKNOWN",))
        ex = "\n".join(r.explanation)
        self.assertIn("STILL UNRESOLVED after the change: POLICY_STATUS_MAPPING_UNKNOWN", ex)
        self.assertEqual(r.counterfactual.condition("unauth.condition.paypal_mark")["state"], "UNRESOLVED")
