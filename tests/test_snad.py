import unittest
from tests.helpers import *


class SNAD(unittest.TestCase):
    def test_15_basic_snad(self):
        a = assess(REG, S.snad_case())
        self.assertEqual(a.protection_assessment, PA.NOT_COVERED)
        self.assertEqual(a.reason_codes, ("CATEGORY_EXCLUDED",))
        self.assertEqual(a.checks, ())                                 # no protection calculation runs
        x = a.exposure
        self.assertEqual(x["exposure_floor"], "480.00")
        self.assertEqual(x["known_lower_bound"], "480.00")
        self.assertEqual(x["total_exposure"], "UNBOUNDED_BY_CURRENT_MODEL")
        self.assertIn("SP.excl.snad", text(a))
        self.assertIn("No protection calculation", text(a))

    def test_16_snad_with_documented_return_shipping(self):
        a = assess(REG, S.snad_case().with_changes(set_facts=[S.tf("return_shipping_cost", "25.00", S.SourceType.MERCHANT_INPUT,
                                                                    "fixture:return-label", S.ProvStatus.MERCHANT_ASSERTED)]))
        x = a.exposure
        rs = next(c for c in x["documented_additional_costs"] if c["cost_id"] == "return_shipping")
        self.assertEqual((rs["amount"], rs["amount_status"]), ("25.00", "PROVIDED"))
        self.assertEqual(x["known_lower_bound"], "505.00")             # floor + additive known cost
        self.assertEqual(x["total_exposure"], "UNBOUNDED_BY_CURRENT_MODEL")
        self.assertNotIn("return_shipping", [u["cost_id"] for u in x["unknown_additional_costs"]])
        self.assertIn("UA.snad.return", rs["passage_ids"])

    def test_17_snad_with_unknown_additional_costs(self):
        a = assess(REG, S.snad_case())
        ids = sorted(u["cost_id"] for u in a.exposure["unknown_additional_costs"])
        self.assertEqual(ids, ["dispute_fee", "other_costs_not_modeled", "paypal_fees_not_refunded", "return_shipping"])
        self.assertEqual(a.exposure["known_lower_bound"], a.exposure["exposure_floor"])
        # a provided PayPal fee is documented but never summed (overlap with the floor is not established)
        fee = a.exposure
        b = assess(REG, S.snad_case().with_changes(set_facts=[S.tf("paypal_fee_amount", "16.00")]))
        self.assertEqual(b.exposure["known_lower_bound"], "480.00")


if __name__ == "__main__":
    unittest.main()
