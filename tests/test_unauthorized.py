import unittest
from tests.helpers import *

CONDITION = "unauth.condition.paypal_mark"


class Unauthorized(unittest.TestCase):
    """Updated for the audit correction: the PayPal status is an opaque observed value; it never satisfies or fails
    the policy condition, so the overall result stays UNKNOWN even when every evidence field is demonstrated."""

    def test_09_eligible_with_evidence(self):
        a = assess(REG, S.unauth_case(status="ELIGIBLE"))
        self.assertEqual(a.evidence_fields_assessment, EFA.REQUIREMENT_FIELDS_DEMONSTRATED)
        self.assertEqual(a.blocking(), [])
        self.assertEqual(a.protection_assessment, PA.UNKNOWN)                 
        self.assertEqual(a.reason_codes, ("POLICY_STATUS_MAPPING_UNKNOWN",))
        c = a.condition(CONDITION)
        self.assertEqual((c["observation"], c["observed_value"]), ("PAYPAL_STATUS_OBSERVED", "ELIGIBLE"))
        self.assertEqual((c["status_semantics"], c["POLICY_STATUS_MAPPING"], c["state"]), ("UNKNOWN", "UNKNOWN", "UNRESOLVED"))
        self.assertEqual(a.timing_requirement, "TIMESTAMPS_MISSING")
        self.assertIn("SP.unauth.marked", text(a))
        self.assertNotIn("STATUS_TOKEN_IN_POLICY_LIST", text(a))

    def test_10_partially_eligible_with_evidence_cannot_satisfy_the_policy_condition(self):
        a = assess(REG, S.unauth_case(status="PARTIALLY_ELIGIBLE"))
        c = a.condition(CONDITION)
        self.assertEqual(c["observed_value"], "PARTIALLY_ELIGIBLE")
        self.assertEqual((c["POLICY_STATUS_MAPPING"], c["state"]), ("UNKNOWN", "UNRESOLVED"))
        self.assertNotEqual(c["state"], "SATISFIED")
        self.assertEqual(a.protection_assessment, PA.UNKNOWN)
        self.assertNotEqual(a.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)
        self.assertEqual(a.evidence_fields_assessment, EFA.REQUIREMENT_FIELDS_DEMONSTRATED)
        self.assertNotIn("STATUS_TOKEN_IN_POLICY_LIST", json.dumps(a.to_dict()))
        self.assertIn("opaque token", text(a))

    def test_11_not_eligible_is_also_opaque(self):
        a = assess(REG, S.unauth_case(status="NOT_ELIGIBLE"))
        self.assertEqual(a.protection_assessment, PA.UNKNOWN)              
        self.assertEqual(a.reason_codes, ("POLICY_STATUS_MAPPING_UNKNOWN",))
        self.assertEqual(a.condition(CONDITION)["observed_value"], "NOT_ELIGIBLE")

    def test_12_missing_eligibility_status(self):
        a = assess(REG, S.unauth_case(status=None))
        self.assertEqual(a.protection_assessment, PA.UNKNOWN)
        self.assertEqual(a.reason_codes, ("POLICY_STATUS_MAPPING_UNKNOWN", "PAYPAL_STATUS_MISSING"))
        c = a.condition(CONDITION)
        self.assertEqual((c["observation"], c["observed_value"], c["POLICY_STATUS_MAPPING"]),
                         ("PAYPAL_STATUS_NOT_SUPPLIED", None, "UNKNOWN"))
        self.assertEqual(a.observed_inputs["paypal_seller_protection_status"],
                         {"state": "NOT_SUPPLIED", "value": None, "status_semantics": "UNKNOWN"})

    def test_13_evidence_missing(self):
        c = S.unauth_case().with_changes(remove_evidence=["shipment_record", "tracking_number", "shipment_date"])
        a = assess(REG, c)
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        self.assertEqual(a.evidence_fields_assessment, EFA.REQUIREMENT_FIELDS_NOT_DEMONSTRATED)
        self.assertEqual(blocking_ids(a), ["unauth.proof.date", "unauth.proof.record", "unauth.proof.tracking_number"])
        self.assertIn("unauth.proof.record", text(a))

    def test_14_timestamps_present_clock_semantics_unknown(self):
        def with_ts(n, s):
            return S.unauth_case().with_changes(
                set_facts=[S.tf("paypal_notification_timestamp", n)],
                set_evidence=[S.merchant("shipment_timestamp", s)])
        a = assess(REG, with_ts("2026-10-19T10:00:00Z", "2026-10-20T09:00:00Z"))
        self.assertEqual(a.timing_requirement, "UNKNOWN_CLOCK")
        self.assertEqual(a.evidence_fields_assessment, EFA.REQUIREMENT_FIELDS_DEMONSTRATED)
        item = next(o for o in a.open_items if o["open_id"] == "unauth.timing_requirement")
        self.assertIn("No comparison is made", item["detail"])
        self.assertIn("SP.unauth.two_days", item["passage_ids"])
        b = assess(REG, with_ts("2026-01-01T00:00:00Z", "2026-12-31T23:59:59Z"))    
        self.assertEqual(b.timing_requirement, "UNKNOWN_CLOCK")
        self.assertEqual((a.protection_assessment, a.open_items, a.explanation), (b.protection_assessment, b.open_items, b.explanation))


if __name__ == "__main__":
    unittest.main()
