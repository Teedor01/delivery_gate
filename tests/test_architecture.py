import copy, json, re, shutil, tempfile, unittest
from pathlib import Path
from delivery_gate.adapters import FixtureSource
from delivery_gate.engine import ALL_EVALUATOR_NAMES
from delivery_gate.models import (EvidenceFact, Provenance, ProvStatus, SourceType, TransactionFact,
                                  ProtectionAssessment, Layer, Changes)
from delivery_gate.registry import PolicyRegistry, RegistryError, POLICY_DIR
from tests.helpers import *

ROOT = Path(__file__).resolve().parent.parent


def registry_with(mutator):
    tmp = Path(tempfile.mkdtemp())
    shutil.copytree(POLICY_DIR, tmp / "policy")
    p = tmp / "policy" / "rules" / "us.sp.inr.json"
    d = json.loads(p.read_text())
    mutator(d)
    p.write_text(json.dumps(d))
    return PolicyRegistry(tmp / "policy", ALL_EVALUATOR_NAMES)


class RegistryRules(unittest.TestCase):
    def test_rules_unreviewed_hashes_null_and_fully_sourced(self):
        for r in REG.rules.values():
            self.assertEqual(r.status, "UNREVIEWED")
            self.assertTrue(all(s.source_hash is None for s in r.sources))
            self.assertTrue(r.raw["unknowns"] and r.version and r.jurisdiction == "US")
            self.assertTrue(all(s.url and s.title and s.retrieved_at for s in r.sources))
            self.assertTrue(all(p in REG.passages for p in r.all_passage_ids()))
        self.assertEqual({r.claim_category for r in REG.rules.values()},
                         {"ITEM_NOT_RECEIVED", "UNAUTHORIZED_TRANSACTION", "SIGNIFICANTLY_NOT_AS_DESCRIBED"})

    def test_registry_refuses_silent_promotion(self):
        with self.assertRaises(RegistryError):
            registry_with(lambda d: d.update(status="VERIFIED"))
        with self.assertRaises(RegistryError):
            registry_with(lambda d: d.update(status="REVIEWED"))       

    def test_registry_rejects_bad_rules(self):
        with self.assertRaises(RegistryError):
            registry_with(lambda d: d["checks"][0].update(passage_ids=["NOPE.not.a.passage"]))
        with self.assertRaises(RegistryError):
            registry_with(lambda d: d["checks"][0].update(evaluator="not_implemented"))
        with self.assertRaises(RegistryError):
            registry_with(lambda d: d["checks"][0].update(kind="UNKNOWN"))
        with self.assertRaises(RegistryError):
            registry_with(lambda d: d["checks"][0].pop("interpretation_note"))
        with self.assertRaises(RegistryError):
            registry_with(lambda d: d["checks"][1].update(check_id="route")) 


class Layers(unittest.TestCase):
    def prov(self):
        return Provenance(SourceType.MERCHANT_INPUT, "x", ProvStatus.MERCHANT_ASSERTED)

    def test_facts_cannot_take_policy_ids_as_names(self):
        for rule in REG.rules.values():
            for c in rule.raw["checks"]:
                with self.assertRaises(ValueError):
                    EvidenceFact(c["check_id"], True, self.prov())
                with self.assertRaises(ValueError):
                    TransactionFact(c["check_id"], True, self.prov())

    def test_assessment_never_mutates_rules_or_case(self):
        before = {k: copy.deepcopy(r.raw) for k, r in REG.rules.items()}
        case = S.inr_case()
        snap = case.snapshot()
        assess(REG, case)
        counterfactual(REG, case, Changes("x", remove_evidence=("delivery_record",)))
        self.assertEqual(before, {k: r.raw for k, r in REG.rules.items()})
        self.assertEqual(snap, case.snapshot())

    def test_no_protected_outcome_exists(self):
        self.assertFalse(any("PROTECTED" == m.name or "PROTECTED" == m.value for m in ProtectionAssessment))
        self.assertEqual({m.name for m in ProtectionAssessment}, {"NOT_COVERED", "REQUIREMENTS_NOT_DEMONSTRATED",
                         "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES", "UNSUPPORTED_JURISDICTION", "UNKNOWN"})
        self.assertEqual(len(Layer), 5)


class Provenance_(unittest.TestCase):
    def test_unreviewed_extraction_cannot_demonstrate(self):
        c = S.inr_case().with_changes(set_evidence=[S.ev("delivery_record", True, S.SourceType.EXTRACTED_FROM_TEXT,
                                                         "fixture:email-1", S.ProvStatus.EXTRACTED_UNREVIEWED,
                                                         confidence=0.99, text_span="Delivered, signed by A. Smith")])
        a = assess(REG, c)
        self.assertEqual(a.check("inr.proof_of_delivery.record").status, ES.NEEDS_HUMAN_REVIEW)
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        self.assertTrue(a.needs_human_review)

    def test_extraction_requires_a_text_span(self):
        with self.assertRaises(ValueError):
            S.ev("delivery_record", True, S.SourceType.EXTRACTED_FROM_TEXT, "fixture:email-1", S.ProvStatus.EXTRACTED_UNREVIEWED)

    def test_confidence_never_changes_the_result(self):
        hi = S.inr_case().with_changes(set_evidence=[S.ev("tracking_number", "1Z999AA10123456784", confidence=0.99)])
        lo = S.inr_case().with_changes(set_evidence=[S.ev("tracking_number", "1Z999AA10123456784", confidence=0.01)])
        self.assertEqual(assess(REG, hi).core_dict(), assess(REG, lo).core_dict())

    def test_carrier_record_must_come_from_a_carrier_source(self):
        c = S.inr_case().with_changes(set_evidence=[S.merchant("delivery_record", True)])
        a = assess(REG, c)
        self.assertEqual(a.check("inr.proof_of_delivery.record").reason_code, "SOURCE_TYPE_NOT_CARRIER")
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)


class Determinism(unittest.TestCase):
    def test_same_inputs_same_digest_and_order_independent(self):
        c = S.inr_case()
        shuffled = type(c)(c.case_id, tuple(reversed(c.transaction_facts)), tuple(reversed(c.evidence)))
        a, b, d = assess(REG, c), assess(REG, c), assess(REG, shuffled)
        self.assertEqual(a.digest, b.digest)
        self.assertEqual(a.digest, d.digest)
        self.assertEqual(a.to_dict(), b.to_dict())
        e = assess(REG, c.with_changes(remove_evidence=["delivery_record"]))
        self.assertNotEqual(a.digest, e.digest)

    def test_counterfactual_is_reproducible(self):
        cur = S.inr_case().with_changes(remove_evidence=["delivery_record"])
        cf = Changes("add record", set_evidence=(S.ev("delivery_record", True),))
        self.assertEqual(counterfactual(REG, cur, cf).to_dict(), counterfactual(REG, cur, cf).to_dict())


class Edges(unittest.TestCase):
    def test_missing_claim_category(self):
        a = assess(REG, S.inr_case().with_changes(remove_facts=["claim_category"]))
        self.assertEqual((a.protection_assessment, a.reason_codes), (PA.UNKNOWN, ("CLAIM_CATEGORY_MISSING",)))

    def test_other_route_is_unknown(self):
        a = assess(REG, S.inr_case(route="OTHER_UNKNOWN"))
        self.assertEqual((a.protection_assessment, a.reason_codes), (PA.UNKNOWN, ("ROUTE_NOT_ESTABLISHED_BY_POLICY",)))

    def test_inconsistent_route_and_funding_is_unknown(self):
        a = assess(REG, S.inr_case(route="CARD_ISSUER_CHARGEBACK", funding="BANK"))
        self.assertEqual((a.protection_assessment, a.reason_codes), (PA.UNKNOWN, ("INCONSISTENT_ROUTE_FUNDING",)))

    def test_intangible_goods_out_of_scope(self):
        a = assess(REG, S.inr_case(physical_goods=False))
        self.assertEqual((a.protection_assessment, a.reason_codes), (PA.UNKNOWN, ("OUT_OF_PHASE1_SCOPE_INTANGIBLE",)))

    def test_exclusion_triggers_not_covered(self):
        a = assess(REG, S.inr_case().with_changes(set_evidence=[S.merchant("shipped_after_advised_not_to_release", True)]))
        self.assertEqual((a.protection_assessment, a.reason_codes), (PA.NOT_COVERED, ("EXCLUSION_TRIGGERED",)))

    def test_snad_non_us_is_unsupported_jurisdiction(self):
        a = assess(REG, S.snad_case(country="CA"))
        self.assertEqual(a.protection_assessment, PA.UNSUPPORTED_JURISDICTION)
        self.assertIsNone(a.exposure)

    def test_preorder_must_ship_within_listed_timeframe(self):
        c = S.inr_case().with_changes(set_facts=[S.tf("pre_order_or_made_to_order", True)],
                                      set_evidence=[S.merchant("shipment_timing", "OUTSIDE_LISTED_TIMEFRAME")])
        a = assess(REG, c)
        self.assertEqual(blocking_ids(a), ["inr.preorder_ship_timing"])


class Adapter(unittest.TestCase):
    def test_fixture_source_round_trips_to_the_same_assessment(self):
        loaded = FixtureSource(ROOT / "fixtures").load_case("inr_all_demonstrated")
        self.assertEqual(assess(REG, loaded).digest, assess(REG, S.inr_case("INR-FIXTURE-FILE")).digest)
        self.assertEqual(assess(REG, loaded).protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)


class Schemas(unittest.TestCase):
    def test_assessment_and_rule_shapes_match_schemas(self):
        asm = json.loads((ROOT / "schemas" / "assessment.schema.json").read_text())
        rule = json.loads((ROOT / "schemas" / "rule.schema.json").read_text())
        for case in (S.inr_case(), S.unauth_case(), S.snad_case(), S.inr_case(country="DE")):
            self.assertEqual(set(asm["required"]), set(assess(REG, case).to_dict()))
        for r in REG.rules.values():
            self.assertTrue(set(rule["required"]) <= set(r.raw))
        for r in REG.rules.values():
            self.assertIn(r.raw["status"], rule["properties"]["status"]["enum"])


class Guardrails(unittest.TestCase):
    """Static scan: the policy guardrails from the audit must hold in code and in rule data."""
    def src(self):
        return {p.name: p.read_text() for p in (ROOT / "delivery_gate").glob("*.py")}

    def test_no_hardcoded_signature_or_threshold_rule(self):
        for name, t in self.src().items():
            self.assertIsNone(re.search(r"\b750\b", t), name)
            self.assertNotIn("signature", t.lower(), name)
        for p in (ROOT / "policy" / "rules").glob("*.json"):
            raw = p.read_text()
            self.assertIsNone(re.search(r"\b750\b", raw), p.name)
            d = json.loads(raw)
            for section in ("gates", "exclusions", "checks", "open_requirements", "exposure_model"):
                self.assertNotIn("signature", json.dumps(d.get(section, "")).lower(), f"{p.name}:{section}")

    def test_no_timer_anywhere(self):
        for name, t in self.src().items():
            self.assertNotIn("timedelta", t, name)
            self.assertNotIn("datetime.now", t, name)
            self.assertNotIn("utcnow", t, name)
            self.assertNotIn("import time", t, name)
            self.assertNotIn("two_day", t.lower(), name)
            for m in re.findall(r"from datetime import ([^\n]+)", t):
                self.assertEqual(m.strip(), "date", name)

    def test_no_protected_outcome_in_code_or_rules(self):
        for name, t in self.src().items():
            self.assertIsNone(re.search(r"\bPROTECTED\b", t), name)
        for p in (ROOT / "policy" / "rules").glob("*.json"):
            self.assertIsNone(re.search(r"\bPROTECTED\b", p.read_text()), p.name)

    def test_no_partially_eligible_semantics_in_code_or_rule_data(self):
        for name, t in self.src().items():
            self.assertNotIn("PARTIALLY_ELIGIBLE", t, name)
            self.assertNotIn("NOT_ELIGIBLE", t, name)
        for p in (ROOT / "policy" / "rules").glob("*.json"):      
            raw = p.read_text()
            self.assertNotIn("PARTIALLY_ELIGIBLE", raw, p.name)
            self.assertNotIn("NOT_ELIGIBLE", raw, p.name)
            self.assertNotIn("STATUS_TOKEN_IN_POLICY_LIST", raw, p.name)
        for name, t in self.src().items():
            self.assertNotIn("STATUS_TOKEN_IN_POLICY_LIST", t, name)

    def test_no_llm_and_no_paypal_calls_in_phase1(self):
        for name, t in self.src().items():
            for banned in ("anthropic", "openai", "requests", "urllib", "http.client", "socket", "api-m.sandbox"):
                self.assertNotIn(banned, t.lower(), f"{name}: {banned}")


if __name__ == "__main__":
    unittest.main()
