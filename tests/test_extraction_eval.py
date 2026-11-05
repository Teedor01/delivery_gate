import json
import unittest
from tests.ext_helpers import *
from eval import corpus as C
from eval.evaluate import THRESHOLDS, evaluate, load_corpus, run_recorded


class Corpus(unittest.TestCase):
    def test_size_and_required_artifact_types(self):
        self.assertGreaterEqual(len(C.ARTIFACTS), 15)
        cats = " | ".join(a["category"] for a in C.ARTIFACTS).lower()
        for needed in ("clean carrier email", "poorly formatted carrier email", "pasted tracking text", "merchant-written statement",
                       "conflicting addresses", "missing tracking number", "ambiguous delivery date", "contradictory artifacts",
                       "irrelevant text", "unsupported claims", "multiple orders"):
            self.assertIn(needed, cats, needed)

    def test_at_least_three_adversarial_cases_are_included(self):
        self.assertGreaterEqual(len(C.ADVERSARIAL_IDS), 3)
        text = {a["id"]: a["text"] for a in C.ARTIFACTS}
        self.assertIn("probably delivered", text["A11"])            
        self.assertIn("PayPal should cover this", text["A11"])
        self.assertIn("The customer says it wasn't redirected", text["A13"])
        self.assertIn("IGNORE ALL PREVIOUS INSTRUCTIONS", text["A14"])
        self.assertIn("I think", text["A15"])

    def test_gold_and_recorded_outputs_cover_every_artifact_and_the_manifest_is_honest(self):
        self.assertEqual(set(C.GOLD), {a["id"] for a in C.ARTIFACTS})
        man = json.loads((ROOT / "eval" / "recorded_outputs" / "MANIFEST.json").read_text())
        self.assertIs(man["automated_api_call"], False)
        self.assertIn("NOT an independent measure", man["independence_warning"])
        for a in C.ARTIFACTS:
            self.assertTrue((ROOT / "eval" / "recorded_outputs" / f"{a['id']}.json").exists())

    def test_the_gold_correction_is_logged_and_the_first_failing_run_is_preserved(self):
        self.assertEqual(len(C.GOLD_CHANGELOG), 1)
        self.assertIn("weakens the independence", C.GOLD_CHANGELOG[0]["caveat"])
        first = json.loads((ROOT / "eval" / "results_first_run.json").read_text())
        self.assertFalse(first["all_pass"])
        self.assertEqual(first["counts"]["mod_ok"], 63)


class RecordedEvaluation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.extraction = run_recorded()
        cls.res = evaluate(cls.extraction)

    def test_every_extraction_check_passes(self):
        failed = {k: (self.res["metrics"][k], self.res["thresholds"][k]) for k, ok in self.res["pass"].items() if not ok}
        self.assertEqual(failed, {})
        self.assertTrue(self.res["all_pass"])
        self.assertEqual(self.res["extractor_kinds"], ["RECORDED_ASSISTANT_OUTPUT"])

    def test_thresholds_were_fixed_up_front(self):
        self.assertEqual(THRESHOLDS["hallucination_rate"], ("<=", 0.0))
        self.assertEqual(THRESHOLDS["must_not_extract_violations"], ("<=", 0))
        self.assertEqual(THRESHOLDS["contradiction_preservation"], (">=", 1.0))

    def test_every_accepted_fact_has_complete_provenance(self):
        arts = self.extraction.artifacts
        for f in self.extraction.candidates:
            self.assertTrue(f.artifact_id in arts and f.fact_id.startswith(f.artifact_id))
            self.assertEqual(arts[f.artifact_id].text[f.span_start:f.span_end], f.source_span)      
            self.assertIn(f.attribution, ("CARRIER_STATEMENT", "MERCHANT_STATEMENT", "CUSTOMER_STATEMENT_RELAYED", "THIRD_PARTY_STATEMENT", "UNKNOWN"))
            self.assertIn(f.modality, ("DIRECT", "REPORTED", "HEDGED"))
            self.assertIn(f.confidence, ("HIGH", "MEDIUM", "LOW"))
            self.assertTrue(f.value and f.normalized_value is not None)
            if f.normalized_value == "UNKNOWN":
                self.assertTrue(f.ambiguity and f.ambiguity_note)                   
            if f.modality == "HEDGED":
                self.assertEqual(f.normalized_value, "UNKNOWN")

    def test_missing_facts_remain_missing_in_the_recorded_outputs(self):
        self.assertEqual([f for f in facts_of("A06") if f.fact == "tracking_number"], [])
        self.assertEqual([f for f in facts_of("A03") if f.fact == "carrier_name"], [])
        self.assertEqual(facts_of("A10"), [])
        self.assertEqual([f for f in facts_of("A05") if f.value.startswith("22 Broad")], [])
        for f in facts_of("A11", "A15"):
            self.assertEqual(f.normalized_value, "UNKNOWN")

    def test_the_audit_artifact_is_serialisable_and_complete(self):
        audit = self.extraction.to_audit()
        json.dumps(audit)
        self.assertEqual(len(audit["artifacts"]), 15)
        a0 = audit["artifacts"][0]
        for k in ("artifact_id", "sha256", "extractor_kind", "raw_output", "validation"):
            self.assertIn(k, a0)
        self.assertEqual(a0["sha256"], ART["A01"].sha256)


class EvaluatorCanFail(unittest.TestCase):
    """A harness that cannot fail proves nothing. Degrade the outputs and check the evaluator notices."""
    def degraded(self, mutate):
        outs = {}
        for a in C.ARTIFACTS:
            d = json.loads((ROOT / "eval" / "recorded_outputs" / f"{a['id']}.json").read_text())
            mutate(a["id"], d)
            outs[a["id"]] = json.dumps(d)
        return evaluate(run_extraction(load_corpus(), MappingExtractor(outs), C.CASE_GROUPS))

    def test_dropping_facts_lowers_recall_below_the_threshold(self):
        res = self.degraded(lambda aid, d: d.update(facts=[]) if aid == "A12" else None)
        self.assertLess(res["metrics"]["fact_recall"], 0.95)
        self.assertFalse(res["all_pass"])

    def test_a_role_confusion_that_slips_past_the_validator_is_caught_by_the_gold(self):
        def mut(aid, d):
            if aid == "A05":
                d["facts"].append({"fact_id": "f9", "fact": "recipient_address", "value": "22 Broad Street, New York, NY 10004",
                                   "normalized_value": {"line1": "22 Broad Street", "city": "New York", "region": "NY", "postal_code": "10004"},
                                   "source_span": "22 Broad Street, New York, NY 10004", "confidence": "HIGH", "ambiguity": False,
                                   "ambiguity_note": None, "attribution": "MERCHANT_STATEMENT", "modality": "DIRECT", "entity_ref": None,
                                   "artifact_id": "A05"})
        res = self.degraded(mut)
        self.assertGreaterEqual(res["metrics"]["must_not_extract_violations"], 1)
        self.assertGreater(res["metrics"]["unsupported_field_rate"], 0)
        self.assertFalse(res["all_pass"])

    def test_a_missed_contradiction_is_caught(self):
        res = self.degraded(lambda aid, d: d.update(facts=[f for f in d["facts"] if f["fact"] != "recipient_address"]) if aid == "A09" else None)
        self.assertLess(res["metrics"]["contradiction_preservation"], 1.0)
        self.assertFalse(res["all_pass"])

    def test_lost_ambiguity_is_caught(self):
        def mut(aid, d):
            if aid == "A04":
                for f in d["facts"]:
                    if f["fact"] == "shipment_date":
                        f["ambiguity"] = False
        res = self.degraded(mut)
        self.assertGreaterEqual(res["counts"]["rejected"], 1)         
        self.assertLess(res["metrics"]["fact_recall"], 1.0)


if __name__ == "__main__":
    unittest.main()
