import ast, copy, itertools, json, unittest
from pathlib import Path
from delivery_gate.adapters import PayPalSandboxSource
from delivery_gate.models import ProtectionAssessment, TransactionFact, Provenance, SourceType, ProvStatus
from paypal_adapter import adapter, inventory
from paypal_adapter.handoff import ALLOWED_FACTS, DISPUTE_HANDOFF_PLAN, HANDOFF_PLAN, PayPalFixtureSource, to_case
from paypal_adapter.inventory import Handoff, Semantics
from tests.paypal_helpers import *

FIXTURE_NAMES = sorted(p.stem for p in FIXTURES.glob("*.json") if p.stem not in ("09_malformed", "11_multi_capture"))
CAP = "purchase_units[0].payments.captures[0]"


class Inventory(unittest.TestCase):
    def test_every_engine_fact_comes_from_a_documented_field(self):
        rows = [f for f in inventory.INVENTORY if f.handoff == Handoff.ENGINE_FACT]
        self.assertTrue(rows)
        for f in rows:
            self.assertEqual(f.semantics, Semantics.OBSERVED_AND_DOCUMENTED, f.path)
            self.assertTrue(f.doc_ref.startswith("https://developer.paypal.com/") and f.documented_meaning and f.engine_consumer, f.path)

    def test_handoff_plan_equals_inventory_engine_facts(self):
        self.assertEqual({f for f, _ in HANDOFF_PLAN + DISPUTE_HANDOFF_PLAN},
                         {f.delivery_gate_fact for f in inventory.INVENTORY if f.handoff == Handoff.ENGINE_FACT})

    def test_no_legal_policy_equivalence_is_established_anywhere(self):
        self.assertFalse([f.path for f in inventory.INVENTORY if f.policy_equivalence == "ESTABLISHED"])
        status = next(f for f in inventory.INVENTORY if f.path == "capture.seller_protection.status")
        self.assertEqual(status.policy_equivalence, "NOT_ESTABLISHED")
        self.assertEqual(status.semantics, Semantics.OBSERVED_AND_DOCUMENTED)      
        self.assertIn("Transaction Details", status.note)                           

    def test_unverified_or_unknown_fields_are_never_engine_facts(self):
        for f in inventory.INVENTORY:
            if f.semantics in (Semantics.OBSERVED_SEMANTICS_UNKNOWN, Semantics.NOT_VERIFIED, Semantics.NOT_AVAILABLE):
                self.assertNotEqual(f.handoff, Handoff.ENGINE_FACT, f.path)

    def test_chains_cover_exactly_the_engine_facts(self):
        self.assertEqual({c["delivery_gate_fact"] for c in inventory.engine_fact_chains()}, ALLOWED_FACTS)


class Provenance_(unittest.TestCase):
    def test_every_observation_carries_full_provenance(self):
        for n in FIXTURE_NAMES:
            resp = response(n)
            sha = adapter.sha256_hex(adapter.canonical(resp))
            for o in observe(resp).select_capture().observations:
                self.assertEqual((o.source, o.origin, o.api), ("PAYPAL_API", "FIXTURE", "PayPal Orders v2"), n)
                self.assertTrue(o.observation_id.startswith("fixture:paypal-capture:") and o.field_path and o.local_path, n)
                self.assertTrue(o.doc_ref.startswith("https://"), n)
                self.assertEqual(o.response_sha256, sha, n)
                self.assertIsNone(o.observed_at, n)                     
                self.assertIn(o.semantics, {s.value for s in Semantics})

    def test_raw_values_are_exactly_what_the_response_held(self):
        for n in FIXTURE_NAMES:
            resp = response(n)
            for o in observe(resp).select_capture().observations:
                if o.local_path.startswith(("unit.", "order.")):
                    continue
                self.assertEqual(o.raw_value, at_path(resp, o.field_path) if o.field_path.startswith("purchase_units") else o.raw_value, n)
        o = observe(response("01_normal")).select_capture().find("amount.value")
        self.assertEqual(o.raw_value, "1200.00")

    def test_observed_at_is_only_what_the_caller_supplied(self):
        h = handoff(response("01_normal"), observed_at="2026-10-31T09:00:00Z")
        self.assertTrue(all(f.provenance.timestamp == "2026-10-31T09:00:00Z" for f in h.case.transaction_facts))
        self.assertTrue(all(f.provenance.timestamp is None for f in handoff(response("01_normal")).case.transaction_facts))

    def test_handed_facts_resolve_to_full_observation_records(self):
        order = observe(response("01_normal"))
        cap = order.select_capture()
        h = to_case(cap)
        ids = {o.observation_id: o for o in cap.observations}
        for f in h.case.transaction_facts:
            self.assertEqual((f.provenance.source_type, f.provenance.status), (SourceType.PAYPAL_API, ProvStatus.SYSTEM_RECORD))
            self.assertIn(f.provenance.source_ref, ids)
            self.assertEqual(ids[f.provenance.source_ref].response_sha256, order.response_sha256)

    def test_fixtures_are_labelled_as_fixtures_everywhere(self):
        for p in FIXTURES.glob("*.json"):
            self.assertTrue(json.loads(p.read_text())["_fixture"]["not_a_live_response"], p.name)
        self.assertTrue(all(f.provenance.source_ref.startswith("fixture:")
            PayPalSandboxSource().load_case("x")


class SellerProtectionObservations(unittest.TestCase):
    def test_tokens_pass_through_verbatim_and_unchanged(self):
        for n, tok in (("01_normal", "ELIGIBLE"), ("02_sp_eligible", "ELIGIBLE"), ("03_sp_partially_eligible", "PARTIALLY_ELIGIBLE"),
                       ("04_sp_not_eligible", "NOT_ELIGIBLE"), ("10_unexpected_enum", "ELIGIBLE_V2")):
            h = handoff(response(n))
            self.assertEqual(h.case.fact("paypal_seller_protection_status").value, tok, n)

    def test_token_and_categories_are_recorded_independently(self):
        c = observe(response("02_sp_eligible")).select_capture()
        self.assertEqual(c.find("seller_protection.status").normalized_value, "ELIGIBLE")
        self.assertEqual(c.find("seller_protection.dispute_categories").normalized_value, ["UNAUTHORIZED_TRANSACTION"])
        c = observe(response("03_sp_partially_eligible")).select_capture()
        self.assertEqual(c.find("seller_protection.dispute_categories").normalized_value, ["ITEM_NOT_RECEIVED"])

    def test_dispute_categories_never_reach_the_engine(self):
        h = handoff(response("01_normal"))
        self.assertNotIn("dispute_categories", " ".join(f.name for f in h.case.transaction_facts))
        r2 = response("01_normal")
        r2["purchase_units"][0]["payments"]["captures"][0]["seller_protection"]["dispute_categories"] = ["ITEM_NOT_RECEIVED"]
        self.assertEqual(handoff(r2).case.snapshot()["transaction_facts"][0]["value"], h.case.snapshot()["transaction_facts"][0]["value"])
        for cat in CATEGORIES:
            self.assertEqual(assessment(r2, cat).digest.split(":")[-1] != "", True)
            self.assertEqual(policy_view(assessment(r2, cat)), policy_view(assessment(response("01_normal"), cat)), cat)

    def test_missing_seller_protection_is_absent_and_never_defaulted(self):
        c = observe(response("05_sp_missing")).select_capture()
        self.assertIsNone(c.find("seller_protection.status"))
        self.assertIn("seller_protection", [a.local_path for a in c.absent])
        h = to_case(c)
        self.assertIsNone(h.case.fact("paypal_seller_protection_status"))
        a = assessment(response("05_sp_missing"), "UNAUTHORIZED_TRANSACTION")
        self.assertEqual(a.observed_inputs["paypal_seller_protection_status"], {"state": "NOT_SUPPLIED", "value": None, "status_semantics": "UNKNOWN"})
        self.assertIn("PAYPAL_STATUS_MISSING", a.reason_codes)

    def test_undocumented_enum_values_are_flagged_verbatim_and_not_normalised(self):
        c = observe(response("10_unexpected_enum")).select_capture()
        st = c.find("seller_protection.status")
        self.assertEqual((st.raw_value, st.normalized_value, st.enum_state), ("ELIGIBLE_V2", "ELIGIBLE_V2", "UNDOCUMENTED_TOKEN"))
        cats = c.find("seller_protection.dispute_categories")
        self.assertEqual(cats.raw_value, ["UNAUTHORIZED_TRANSACTION", "NEW_CATEGORY"])
        self.assertIsNone(cats.normalized_value)
        self.assertEqual(c.find("status").enum_state, "UNDOCUMENTED_TOKEN")
        self.assertEqual(c.find("status_details.reason").enum_state, "UNDOCUMENTED_TOKEN")
        self.assertEqual({a.kind for a in c.anomalies}, {"UNDOCUMENTED_ENUM_VALUE"})
        self.assertEqual(len(c.anomalies), 4)
        self.assertTrue(any("not a documented token" in x for x in to_case(c).cautions))


class MissingAndMalformed(unittest.TestCase):
    def test_missing_fields_receive_no_defaults(self):
        r = response("01_normal")
        cap = r["purchase_units"][0]["payments"]["captures"][0]
        del cap["amount"]
        h = handoff(r)
        names = {f.name for f in h.case.transaction_facts}
        self.assertEqual(names, {"paypal_seller_protection_status"})
        self.assertIn("amount", [a["local_path"] for a in h.absent])
        del cap["seller_protection"]["status"]
        self.assertEqual({f.name for f in handoff(r).case.transaction_facts}, set())

    def test_no_shipping_address_is_absent_not_empty(self):
        c = observe(response("08_without_address")).select_capture()
        self.assertIsNone(c.find("unit.shipping.address"))
        self.assertIn("unit.shipping.address", [a.local_path for a in c.absent])

    def test_unusable_field_values_become_anomalies_and_are_not_handed_over(self):
        for bad, kind in (("abc", "PATTERN_MISMATCH"), (12.5, "TYPE_NOT_STRING"), ("-5.00", "NOT_POSITIVE"), ("0", "NOT_POSITIVE"), ("1e3", "PATTERN_MISMATCH")):
            r = response("01_normal")
            r["purchase_units"][0]["payments"]["captures"][0]["amount"]["value"] = bad
            c = observe(r).select_capture()
            self.assertEqual(c.find("amount.value").raw_value, bad)
            self.assertIsNone(c.find("amount.value").normalized_value)
            self.assertIn(kind, [a.kind for a in c.anomalies], bad)
            self.assertIsNone(to_case(c).case.fact("transaction_amount"), bad)
        r = response("01_normal"); r["purchase_units"][0]["payments"]["captures"][0]["amount"]["currency_code"] = "usd"
        self.assertIsNone(handoff(r).case.fact("currency"))
        r = response("01_normal"); r["purchase_units"][0]["payments"]["captures"][0]["seller_protection"]["status"] = ""
        self.assertIsNone(handoff(r).case.fact("paypal_seller_protection_status"))
        r["purchase_units"][0]["payments"]["captures"][0]["seller_protection"] = "oops"
        c = observe(r).select_capture()
        self.assertIn("TYPE_NOT_OBJECT", [a.kind for a in c.anomalies])

    def test_malformed_responses_fail_safely_with_no_partial_output(self):
        base = response("01_normal")
        def mut(f):
            r = copy.deepcopy(base); f(r); return r
        cases = {
            "not an object": [1, 2], "string": "x", "none": None,
            "missing order id": mut(lambda r: r.pop("id")),
            "empty order id": mut(lambda r: r.update(id="")),
            "purchase_units not array": mut(lambda r: r.update(purchase_units="x")),
            "unit not object": mut(lambda r: r.update(purchase_units=["x"])),
            "payments not object": mut(lambda r: r["purchase_units"][0].update(payments=[])),
            "captures not array": response("09_malformed"),
            "capture not object": mut(lambda r: r["purchase_units"][0]["payments"].update(captures=["x"])),
            "capture missing id": mut(lambda r: r["purchase_units"][0]["payments"]["captures"][0].pop("id")),
            "capture id not string": mut(lambda r: r["purchase_units"][0]["payments"]["captures"][0].update(id=7)),
            "duplicate capture id": mut(lambda r: r["purchase_units"][0]["payments"]["captures"].append(copy.deepcopy(r["purchase_units"][0]["payments"]["captures"][0]))),
            "not serialisable": mut(lambda r: r.update(x=object())),
        }
        for label, resp in cases.items():
            with self.assertRaises(adapter.MalformedPayPalResponse, msg=label):
                adapter.observe_order(resp, origin="FIXTURE")
        with self.assertRaises(adapter.MalformedPayPalResponse):
            adapter.observe_order(base, origin="LIVE")
        with self.assertRaises(adapter.MalformedPayPalResponse):
            adapter.observe_order(base, origin="FIXTURE", observed_at="")
        with self.assertRaises(adapter.MalformedPayPalResponse):
            adapter.observe_capture_resource({"status": "COMPLETED"}, origin="FIXTURE")

    def test_an_order_with_no_captures_yields_no_captures_not_a_fabricated_one(self):
        o = adapter.observe_order({"id": "FXORDER000099", "status": "CREATED"}, origin="FIXTURE")
        self.assertEqual(o.captures, ())
        with self.assertRaises(adapter.MalformedPayPalResponse):
            o.select_capture()

    def test_multiple_captures_are_never_guessed(self):
        o = observe(response("11_multi_capture"))
        self.assertEqual(len(o.captures), 2)
        with self.assertRaises(adapter.MalformedPayPalResponse):
            o.select_capture()
        self.assertEqual(o.select_capture("FXCAP0000000011b").find("amount.value").normalized_value, "300.00")
        with self.assertRaises(KeyError):
            o.select_capture("nope")

    def test_standalone_capture_resource(self):
        c = response("01_normal")["purchase_units"][0]["payments"]["captures"][0]
        co = adapter.observe_capture_resource(c, origin="FIXTURE")
        self.assertEqual(co.find("amount.value").normalized_value, "1200.00")
        self.assertEqual(to_case(co).case.fact("currency").value, "USD")
        self.assertIsNone(co.find("unit.shipping.address"))                  


class WithheldFields(unittest.TestCase):
    def test_address_funding_and_fee_are_observed_but_never_handed_over(self):
        for n in ("01_normal", "07_with_address", "06_unknown_funding_source"):
            h = handoff(response(n))
            names = {f.name for f in h.case.transaction_facts}
            self.assertFalse(names - ALLOWED_FACTS, n)
            self.assertFalse({"transaction_details_address", "funding_source", "paypal_fee_amount", "physical_goods", "transaction_amount"} & names, n)
        h = handoff(response("07_with_address"))
        w = {x["would_feed"] for x in h.withheld}
        self.assertEqual(w, {"transaction_details_address", "funding_source", "paypal_fee_amount", "transaction_amount"})
        self.assertTrue(all(x["note"] for x in h.withheld))
        by = {x["would_feed"]: x["reason"] for x in h.withheld}
        self.assertEqual(by["transaction_amount"], "ENGINE_TREATS_AMOUNT_AS_AN_EXPOSURE_BOUND_BUT_DISPUTED_AMOUNT_MAY_BE_LOWER")
        self.assertEqual(by["transaction_details_address"], "MAPPING_NOT_ESTABLISHED_BY_PRIMARY_DOCUMENTATION")

    def test_address_candidate_keeps_raw_and_is_labelled_unverified(self):
        o = observe(response("07_with_address")).select_capture().find("unit.shipping.address")
        self.assertEqual(o.raw_value["address_line_2"], "Suite 4")
        self.assertEqual(o.normalized_value, {"line1": "1 Market St", "line2": "Suite 4", "city": "San Francisco", "region": "CA",
                                              "postal_code": "94105", "country": "US"})
        self.assertEqual((o.normalization, o.semantics), ("KEY_RENAME_CANDIDATE_UNVERIFIED", "NOT_VERIFIED"))

    def test_payment_source_records_type_keys_only(self):
        o = observe(response("06_unknown_funding_source")).select_capture().find("order.payment_source.types")
        self.assertEqual(o.raw_value, ["novel_wallet"])
        self.assertNotIn("FXPAYER", json.dumps(o.to_dict()))                 
        a = assessment(response("06_unknown_funding_source"), "ITEM_NOT_RECEIVED", route="CARD_ISSUER_CHARGEBACK")
        self.assertTrue(any("funding_source_not_supplied" in x["open_id"] for x in a.open_items))  

    def test_engine_never_receives_a_policy_fact_from_the_adapter(self):
        for n in FIXTURE_NAMES:
            names = {f.name for f in handoff(response(n)).case.transaction_facts}
            self.assertFalse(names - ALLOWED_FACTS)
        with self.assertRaises(ValueError):
            TransactionFact("protected", True, Provenance(SourceType.PAYPAL_API, "x", ProvStatus.SYSTEM_RECORD))
        with self.assertRaises(ValueError):
            TransactionFact("seller_protection_applies", True, Provenance(SourceType.PAYPAL_API, "x", ProvStatus.SYSTEM_RECORD))

    def test_cautions_flag_non_completed_captures(self):
        h = handoff(response("12_partially_refunded"))
        self.assertTrue(any("PARTIALLY_REFUNDED" in c for c in h.cautions))
        self.assertIsNone(h.case.fact("transaction_amount"))
        self.assertFalse(handoff(response("01_normal")).cautions)


class CriticalTokenTest(unittest.TestCase):
    """Same transaction, only the seller-protection token changes: the policy assessment must not change."""
    TOKENS = ["ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE", "ELIGIBLE_V2", "eligible", "Not_Eligible", "UNKNOWN", "PROTECTED", "0", "01"]

    def test_policy_assessment_is_identical_for_every_token_in_every_category(self):
        for cat in CATEGORIES:
            base = policy_view(assessment(with_status(response("01_normal"), "ELIGIBLE"), cat), "ELIGIBLE")
            for t in self.TOKENS:
                a = assessment(with_status(response("01_normal"), t), cat)
                self.assertEqual(policy_view(a, t), base, (cat, t))
                self.assertNotEqual(a.protection_assessment.value, "PROTECTED")
                self.assertNotIn("PROTECTED", {m.value for m in ProtectionAssessment})

    def test_unauthorized_stays_unknown_whatever_the_token(self):
        for t in self.TOKENS:
            a = assessment(with_status(response("01_normal"), t), "UNAUTHORIZED_TRANSACTION")
            self.assertEqual(a.protection_assessment, ProtectionAssessment.UNKNOWN, t)
            self.assertEqual(a.reason_codes, ("POLICY_STATUS_MAPPING_UNKNOWN",), t)
            c = a.condition("unauth.condition.paypal_mark")
            self.assertEqual((c["state"], c["POLICY_STATUS_MAPPING"], c["status_semantics"]), ("UNRESOLVED", "UNKNOWN", "UNKNOWN"), t)

    def test_the_only_difference_between_tokens_is_the_echoed_observation(self):
        a = assessment(with_status(response("01_normal"), "ELIGIBLE"), "UNAUTHORIZED_TRANSACTION")
        b = assessment(with_status(response("01_normal"), "NOT_ELIGIBLE"), "UNAUTHORIZED_TRANSACTION")
        self.assertNotEqual(a.digest, b.digest)                               
        self.assertEqual(policy_view(a, "ELIGIBLE"), policy_view(b, "NOT_ELIGIBLE"))   

    def test_missing_token_differs_only_by_the_missing_marker(self):
        have = assessment(response("01_normal"), "UNAUTHORIZED_TRANSACTION")
        gone = assessment(response("05_sp_missing"), "UNAUTHORIZED_TRANSACTION")
        self.assertEqual(have.protection_assessment, gone.protection_assessment)
        self.assertEqual(set(gone.reason_codes) - set(have.reason_codes), {"PAYPAL_STATUS_MISSING"})


class EndToEnd(unittest.TestCase):
    def test_every_fixture_reaches_the_engine_with_phase1_invariants_intact(self):
        for n in FIXTURE_NAMES:
            for cat in CATEGORIES:
                a = assessment(response(n), cat)
                self.assertEqual((a.policy_status, a.paypal_acceptance), ("UNREVIEWED", "NOT_ESTABLISHED"), (n, cat))
                self.assertTrue(a.display_notice)
        self.assertEqual(assessment(response("01_normal"), "SIGNIFICANTLY_NOT_AS_DESCRIBED").protection_assessment, ProtectionAssessment.NOT_COVERED)

    def test_engine_snad_exposure_no_longer_receives_the_capture_amount(self):
        a = assessment(response("01_normal"), "SIGNIFICANTLY_NOT_AS_DESCRIBED")
        self.assertIsNone(a.exposure["exposure_floor"])                          
        self.assertIsNone(a.exposure["known_lower_bound"])
        self.assertEqual(a.exposure["currency"], "USD")
        self.assertIn({"cost_id": "transaction_amount", "reason": "AMOUNT_UNKNOWN"}, a.exposure["unknown_additional_costs"])
        self.assertEqual(a.protection_assessment, ProtectionAssessment.NOT_COVERED)   

    def test_fixture_source_implements_the_phase1_interface(self):
        src = PayPalFixtureSource(FIXTURES)
        self.assertEqual(src.load_case("01_normal").fact("currency").value, "USD")
        self.assertIsNone(src.load_case("01_normal").fact("transaction_amount"))
        with self.assertRaises(adapter.MalformedPayPalResponse):
            src.load_case("09_malformed")
        with self.assertRaises(adapter.MalformedPayPalResponse):
            src.load_case("11_multi_capture")


class Deterministic(unittest.TestCase):
    def test_same_response_same_output(self):
        for n in FIXTURE_NAMES:
            self.assertEqual(observe(response(n)).to_dict(), observe(response(n)).to_dict(), n)
            self.assertEqual(handoff(response(n)).to_dict(), handoff(response(n)).to_dict(), n)

    def test_key_order_in_the_response_does_not_matter(self):
        def reverse(o):
            if isinstance(o, dict):
                return {k: reverse(o[k]) for k in reversed(list(o))}
            return [reverse(x) for x in o] if isinstance(o, list) else o
        for n in FIXTURE_NAMES:
            self.assertEqual(observe(response(n)).to_dict(), observe(reverse(response(n))).to_dict(), n)

    def test_category_order_is_normalised_but_raw_order_is_kept(self):
        r = response("01_normal"); caps = r["purchase_units"][0]["payments"]["captures"][0]["seller_protection"]
        caps["dispute_categories"] = ["UNAUTHORIZED_TRANSACTION", "ITEM_NOT_RECEIVED"]
        o = observe(r).select_capture().find("seller_protection.dispute_categories")
        self.assertEqual((o.raw_value, o.normalized_value), (["UNAUTHORIZED_TRANSACTION", "ITEM_NOT_RECEIVED"], ["ITEM_NOT_RECEIVED", "UNAUTHORIZED_TRANSACTION"]))


class Architecture(unittest.TestCase):
    @staticmethod
    def imports(path):
        out = set()
        for node in ast.walk(ast.parse(Path(path).read_text())):
            if isinstance(node, ast.ImportFrom) and node.module:
                out.add(node.module.split(".")[0])
            elif isinstance(node, ast.Import):
                out |= {a.name.split(".")[0] for a in node.names}
        return out

    def test_observation_modules_do_not_import_the_engine(self):
        for f in ("adapter.py", "inventory.py"):
            self.assertNotIn("delivery_gate", self.imports(ROOT / "paypal_adapter" / f), f)

    def test_dependency_direction(self):
        for p in (ROOT / "delivery_gate").glob("*.py"):
            self.assertFalse({"paypal_adapter", "delivery_extraction"} & self.imports(p), p.name)
        for p in (ROOT / "paypal_adapter").glob("*.py"):
            self.assertNotIn("delivery_extraction", self.imports(p), p.name)
        for p in (ROOT / "delivery_extraction").glob("*.py"):
            self.assertNotIn("paypal_adapter", self.imports(p), p.name)

    def test_no_clock_or_randomness_in_the_adapter(self):
        for f in ("adapter.py", "handoff.py"):
            self.assertFalse({"datetime", "time", "random", "uuid"} & self.imports(ROOT / "paypal_adapter" / f), f)


if __name__ == "__main__":
    unittest.main()
