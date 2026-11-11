"""Phase 4: the UI service. It must consume the existing engine/extraction/review components and add nothing to their results."""
import unittest

from delivery_extraction.review import Attestation, ReviewError
from delivery_gate.models import ProtectionAssessment as PA
from delivery_ui.service import NotFound, ServiceError
from tests.ui_helpers import *


class Parity(unittest.TestCase):
    """No bypass: the UI's assessment is exactly what the Phase 1-3 components produce when driven directly."""

    def test_every_payment_matches_the_independent_oracle(self):
        s = fresh()
        for ref in REFS:
            ui = s.analyze(ref).assessment
            oracle = independent_assessment(ref)
            self.assertEqual(ui.digest, oracle.digest, ref)
            self.assertEqual(ui.protection_assessment, oracle.protection_assessment, ref)

    def test_the_service_displays_whatever_the_engine_returns(self):
        called = []

        def spy(registry, case):
            a = assess(registry, case)
            called.append(case.case_id)
            return a
        s = fresh(assess_fn=spy)
        s.analyze("DG-20479")
        self.assertEqual(called, ["DG-20479"])

    def test_a_forced_engine_result_is_what_gets_presented(self):
        """If the engine said something else, the UI would say it: nothing in the service or presenter computes a result of its own."""
        from delivery_ui import presenter as P
        real = fresh().analyze("DG-20479").assessment
        forced = type("F", (), {})()
        for k in ("needs_human_review",):
            setattr(forced, k, False)
        forced.protection_assessment = PA.NOT_COVERED
        forced.reason_codes = ("POLICY_SAYS_SO",)
        view = P.overall_for(forced, object())
        self.assertEqual((view["key"], view["label"]), ("NOT_COVERED", "Not covered"))
        self.assertNotEqual(view["key"], real.protection_assessment.value)


class Scenarios(unittest.TestCase):
    def setUp(self):
        self.s = fresh()

    def a(self, ref):
        return self.s.analyze(ref).assessment

    def test_1_clean_carrier_evidence(self):
        a = self.a("DG-20479")
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)
        self.assertFalse(a.needs_human_review)
        self.assertEqual(a.paypal_acceptance, "NOT_ESTABLISHED")

    def test_2_missing_delivery_evidence(self):
        a = self.a("DG-20481")
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        rec = next(c for c in a.checks if c.check_id.endswith("proof_of_delivery.record"))
        self.assertEqual((rec.status.value, rec.reason_code), ("NOT_DEMONSTRATED", "MISSING_FACT"))

    def test_3_conflicting_addresses_need_human_review(self):
        an = self.s.analyze("DG-20472")
        self.assertTrue(an.assessment.needs_human_review)
        self.assertEqual(an.assessment.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        self.assertIn("CONTRADICTED", {c.status.value for c in an.assessment.checks})
        self.assertTrue(an.contradictions and all(c.needs_human_review for c in an.contradictions))

    def test_4_a_merchant_assertion_is_never_corroborated(self):
        a = self.a("DG-20475")
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        trk = next(c for c in a.checks if c.check_id.endswith("tracking_number"))
        self.assertEqual(trk.corroboration, "MERCHANT_ASSERTED_ONLY")
        rec = next(c for c in a.checks if c.check_id.endswith("proof_of_delivery.record"))
        self.assertEqual(rec.status.value, "NOT_DEMONSTRATED")

    def test_5_unknown_paypal_status_stays_unresolved(self):
        a = self.a("DG-20468")
        self.assertEqual(a.protection_assessment, PA.UNKNOWN)
        self.assertIn("POLICY_STATUS_MAPPING_UNKNOWN", a.reason_codes)

    def test_6_counterfactual_changes_the_modeled_assessment(self):
        r = self.s.what_if("DG-20481", "add:A01")
        self.assertEqual(r.report.current.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        self.assertEqual(r.report.counterfactual.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)
        self.assertTrue(r.report.result_change["changed"])

    def test_unknowns_stay_unknown(self):
        self.assertEqual(self.a("DG-20463").protection_assessment, PA.UNKNOWN)          # EXTERNAL channel: route unknown
        self.assertEqual(self.a("DG-20460").protection_assessment, PA.UNKNOWN)          # not-as-described reason: not normalised
        self.assertEqual(self.a("DG-20455").protection_assessment, PA.UNKNOWN)          # no dispute at all
        an = self.s.analyze("DG-20455")
        self.assertIsNone(an.dispute)
        self.assertEqual(an.exposure.disputed_amount["state"], "UNKNOWN")
        self.assertEqual(an.exposure.potential_seller_exposure["state"], "UNKNOWN")


class Counterfactual(unittest.TestCase):
    def test_the_hypothetical_equals_what_actually_happens_when_the_evidence_is_added_and_reviewed(self):
        s = fresh()
        hyp = s.what_if("DG-20481", "add:A01").report.counterfactual
        s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        s.review_artifact("DG-20481", "A01", "attest_carrier", "Reviewer R")
        actual = s.analyze("DG-20481").assessment
        self.assertEqual(actual.digest, hyp.digest)
        self.assertEqual(actual.protection_assessment, hyp.protection_assessment)

    def test_asking_what_if_changes_nothing(self):
        s = fresh()
        before = s.analyze("DG-20481").assessment.digest
        events = len(s.states["DG-20481"].events)
        s.what_if("DG-20481", "add:A01")
        self.assertEqual(s.analyze("DG-20481").assessment.digest, before)
        self.assertEqual(len(s.states["DG-20481"].events), events)
        self.assertNotIn("A01", s.states["DG-20481"].artifacts)

    def test_confirming_evidence_as_your_own_statement_cannot_demonstrate_delivery(self):
        s = fresh()
        s.add_artifact("DG-20481", SAMPLE["A04"]["text"], "MERCHANT_STATEMENT")
        opts = {o.option_id for o in s.what_if_options("DG-20481")}
        self.assertIn("review:A04:merchant", opts)
        self.assertNotIn("review:A04:carrier", opts)                    # a merchant statement offers no carrier route
        r = s.what_if("DG-20481", "review:A04:merchant")
        self.assertEqual(r.report.counterfactual.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)

    def test_unknown_option_is_refused(self):
        with self.assertRaises(NotFound):
            fresh().what_if("DG-20481", "add:A99")


class EvidenceFlow(unittest.TestCase):
    def test_a_sample_is_read_by_the_existing_recorded_extraction(self):
        s = fresh()
        rec = s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        self.assertEqual((rec.artifact.artifact_id, rec.status, len(rec.facts)), ("A01", "EXTRACTED", 7))
        self.assertEqual(rec.extractor_kind, "RECORDED_ASSISTANT_OUTPUT")
        self.assertTrue(rec.recognized_sample)

    def test_unreviewed_extraction_does_not_demonstrate_anything(self):
        s = fresh()
        s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        a = s.analyze("DG-20481").assessment
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        self.assertTrue(a.needs_human_review)
        trk = next(c for c in a.checks if c.check_id.endswith("tracking_number"))
        self.assertEqual((trk.status.value, trk.reason_code), ("NEEDS_HUMAN_REVIEW", "ONLY_UNREVIEWED_EXTRACTION"))
        rec = next(c for c in a.checks if c.check_id.endswith("proof_of_delivery.record"))
        self.assertEqual(rec.status.value, "NOT_DEMONSTRATED")           # a delivery record exists only once a reviewer attests the document

    def test_attesting_the_carrier_document_demonstrates_the_modeled_requirements(self):
        s = fresh()
        s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        out = s.review_artifact("DG-20481", "A01", "attest_carrier", "Reviewer R")
        self.assertEqual(len(out["applied"]), 4)
        self.assertEqual(s.analyze("DG-20481").assessment.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)

    def test_text_that_nothing_can_read_is_saved_but_unread_and_changes_nothing(self):
        s = fresh()
        before = s.analyze("DG-20481").assessment.digest
        rec = s.add_artifact("DG-20481", "I never got the parcel, honest.", "OTHER")
        self.assertEqual((rec.status, rec.facts), ("UNAVAILABLE", []))
        self.assertIn("No extraction model is configured", rec.message)
        self.assertEqual(s.analyze("DG-20481").assessment.digest, before)

    def test_an_injected_model_output_goes_through_validation_and_review(self):
        s = fresh(extractor_factory=injected_factory({"U1": custom_output()}))
        rec = s.add_artifact("DG-20481", CUSTOM_TEXT, "CARRIER_EMAIL")
        self.assertEqual((rec.artifact.artifact_id, rec.status, len(rec.facts), rec.extractor_kind), ("U1", "EXTRACTED", 3, "TEST_INJECTED_OUTPUT"))
        self.assertEqual({f.fact for f in rec.facts}, {"carrier_name", "tracking_number", "delivery_status"})
        s.review_artifact("DG-20481", "U1", "attest_carrier", "R")
        trk = next(c for c in s.analyze("DG-20481").assessment.checks if c.check_id.endswith("tracking_number"))
        self.assertEqual((trk.status.value, trk.corroboration), ("DEMONSTRATED", "CORROBORATED"))

    def test_model_output_that_fails_validation_is_discarded_not_trusted(self):
        bad = custom_output().replace("Tracking number: 1Z999AA10123456784", "Tracking number: 9999")      # span not in the text
        s = fresh(extractor_factory=injected_factory({"U1": bad}))
        rec = s.add_artifact("DG-20481", CUSTOM_TEXT, "CARRIER_EMAIL")
        self.assertNotIn("tracking_number", {f.fact for f in rec.facts})
        self.assertGreaterEqual(len(rec.rejected), 1)

    def test_extractor_failure_is_reported(self):
        def boom(artifact, recognized):
            from delivery_extraction.extractor import MappingExtractor
            if recognized:
                return default_extractor_factory(artifact, recognized)
            return MappingExtractor({}), "TEST", None                        # KeyError when asked
        rec = fresh(extractor_factory=boom).add_artifact("DG-20481", "some text here", "OTHER")
        self.assertEqual(rec.status, "FAILED")
        self.assertIn("KeyError", rec.message)

    def test_input_validation(self):
        s = fresh()
        for text, code in (("", "empty_evidence"), ("   \n", "empty_evidence"), (None, "empty_evidence"), ("x" * 20001, "evidence_too_long")):
            with self.assertRaises(ServiceError) as c:
                s.add_artifact("DG-20481", text, "OTHER")
            self.assertEqual(c.exception.code, code)
        with self.assertRaises(ServiceError) as c:
            s.add_artifact("DG-20481", "text", "CARRIER_API")
        self.assertEqual(c.exception.code, "invalid_kind")
        with self.assertRaises(NotFound):
            s.add_artifact("DG-99999", "text", "OTHER")

    def test_the_same_evidence_is_not_added_twice(self):
        s = fresh()
        a = s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        b = s.add_artifact("DG-20481", SAMPLE["A01"]["text"].strip(), "CARRIER_EMAIL")
        self.assertIs(a, b)
        self.assertEqual(len(s.states["DG-20481"].artifacts), 2)             # A11 from the fixture, plus A01

    def test_two_orders_in_one_evidence_need_a_choice_and_nothing_is_guessed(self):
        s = fresh()
        s.add_artifact("DG-20481", SAMPLE["A12"]["text"], "OTHER")
        an = s.analyze("DG-20481")
        self.assertTrue(an.needs_entity_choice)
        self.assertIsNone(an.assessment)
        self.assertTrue(len(an.entities) >= 2)
        with self.assertRaises(ServiceError):
            s.set_entity("DG-20481", "NOT-A-REAL-ORDER")
        s.set_entity("DG-20481", an.entities[0])
        self.assertIsNotNone(s.analyze("DG-20481").assessment)


class Review(unittest.TestCase):
    def test_a_merchant_statement_cannot_be_recorded_as_a_carrier_document(self):
        s = fresh()
        s.add_artifact("DG-20481", SAMPLE["A04"]["text"], "MERCHANT_STATEMENT")
        with self.assertRaises(ServiceError) as c:
            s.review_artifact("DG-20481", "A04", "attest_carrier", "R")
        self.assertEqual(c.exception.code, "carrier_review_refused")
        self.assertNotIn("A04", s.states["DG-20481"].attestations)

    def test_recording_as_your_own_statement_is_not_corroboration(self):
        s = fresh()
        an = s.analyze("DG-20475")
        row = {b["fact_id"]: b for b in an.bridge.bridged}
        self.assertTrue(row and all(r["source_type"] == "MERCHANT_STATEMENT" and r["source_authenticity"] == "UNVERIFIED" for r in row.values()))

    def test_a_reviewer_can_only_confer_reviewed_never_verified(self):
        s = fresh()
        s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        s.review_artifact("DG-20481", "A01", "attest_carrier", "R")
        an = s.analyze("DG-20481")
        auths = {b["source_authenticity"] for b in an.bridge.bridged}
        self.assertEqual(auths - {"UNVERIFIED"}, {"REVIEWED"})
        with self.assertRaises(ReviewError):
            Attestation("A01", "R", authenticity="VERIFIED")
        with self.assertRaises(ServiceError) as c:
            s.review_artifact("DG-20481", "A01", "attest_verified", "R")
        self.assertEqual(c.exception.code, "invalid_review_mode")

    def test_reviewer_name_is_required_and_bounded(self):
        s = fresh()
        for bad in ("", "   ", None, "x" * 81):
            with self.assertRaises(ServiceError) as c:
                s.review_artifact("DG-20479", "A01", "reject_all", bad)
            self.assertEqual(c.exception.code, "reviewer_required")

    def test_rejecting_a_fact_removes_it_from_the_assessment_and_undo_restores_the_review(self):
        s = fresh()
        an = s.analyze("DG-20479")
        tn = next(f for f in an.candidates if f.fact == "tracking_number")
        s.review_artifact("DG-20479", "A01", "reject_fact", "R", fact_id=tn.fact_id)
        trk = next(c for c in s.analyze("DG-20479").assessment.checks if c.check_id.endswith("tracking_number"))
        self.assertEqual(trk.status.value, "NOT_DEMONSTRATED")
        s.review_artifact("DG-20479", "A01", "undo", "")
        self.assertEqual(s.analyze("DG-20479").assessment.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)   # back to unreviewed, not silently approved

    def test_unknown_artifact_fact_and_mode(self):
        s = fresh()
        with self.assertRaises(NotFound):
            s.review_artifact("DG-20479", "A99", "undo", "")
        with self.assertRaises(NotFound):
            s.review_artifact("DG-20479", "A01", "reject_fact", "R", fact_id="nope")
        with self.assertRaises(ServiceError):
            s.review_artifact("DG-20479", "A01", "approve_everything", "R")

    def test_fixture_reviews_are_marked_as_fixtures(self):
        s = fresh()
        log = s.states["DG-20479"].review_log
        self.assertTrue(log and all(x["fixture"] and "fixture" in x["reviewer"].lower() for x in log))


class MerchantInfo(unittest.TestCase):
    def test_answers_feed_the_engine_as_merchant_statements(self):
        s = fresh()
        s.set_merchant_info("DG-20479", {"answers": {"redirect_detected": True}})
        a = s.analyze("DG-20479").assessment
        red = next(c for c in a.checks if c.check_id.endswith("no_redirect"))
        self.assertNotEqual(red.status.value, "DEMONSTRATED")
        self.assertNotEqual(a.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)

    def test_unanswered_stays_missing(self):
        s = fresh()
        s.set_merchant_info("DG-20479", {"answers": {"redirect_detected": None, "response_to_paypal": None}})
        a = s.analyze("DG-20479").assessment
        self.assertEqual(a.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        red = next(c for c in a.checks if c.check_id.endswith("no_redirect"))
        self.assertEqual(red.reason_code, "MISSING_FACT")

    def test_removing_the_transaction_details_address_leaves_the_comparison_unknown(self):
        s = fresh()
        s.set_merchant_info("DG-20479", {"address": {}})
        an = s.analyze("DG-20479")
        self.assertNotEqual(an.assessment.protection_assessment, PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES)

    def test_a_non_us_country_is_outside_the_modeled_rules(self):
        s = fresh()
        s.set_merchant_info("DG-20479", {"country": "ng"})
        self.assertEqual(s.analyze("DG-20479").assessment.protection_assessment, PA.UNSUPPORTED_JURISDICTION)

    def test_validation(self):
        s = fresh()
        for bad in ({"country": "USA"}, {"country": "1!"}, {"address": {"bogus": "x"}}, {"answers": {"redirect_detected": "maybe"}},
                    {"answers": {"response_to_paypal": "SOMETIMES"}}, {"answers": {"protection_assessment": True}}, {"answers": "x"}):
            with self.assertRaises(ServiceError, msg=str(bad)):
                s.set_merchant_info("DG-20479", bad)


class Lifecycle(unittest.TestCase):
    def test_reset_restores_the_fixtures(self):
        s = fresh()
        s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        s.review_artifact("DG-20481", "A01", "attest_carrier", "R")
        s.reset()
        self.assertEqual(s.analyze("DG-20481").assessment.protection_assessment, PA.REQUIREMENTS_NOT_DEMONSTRATED)
        self.assertEqual(list(s.states["DG-20481"].artifacts), ["A11"])

    def test_services_are_isolated_from_each_other(self):
        a, b = fresh(), fresh()
        a.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        self.assertNotIn("A01", b.states["DG-20481"].artifacts)

    def test_fixture_data_is_never_presented_as_live(self):
        s = fresh()
        for ref in REFS:
            an = s.analyze(ref)
            self.assertEqual(an.capture.origin, "FIXTURE")
            self.assertTrue(an.capture.resource_ref.startswith("fixture:"))
            self.assertTrue(all(e["fixture"] for e in an.state.events))

    def test_events_record_what_happened_in_order(self):
        s = fresh()
        s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        s.review_artifact("DG-20481", "A01", "attest_carrier", "Reviewer R")
        kinds = [e["kind"] for e in s.states["DG-20481"].events]
        self.assertEqual(kinds[-2:], ["EVIDENCE_ADDED", "REVIEW_RECORDED"])
        self.assertFalse(s.states["DG-20481"].events[-1]["fixture"])


if __name__ == "__main__":
    unittest.main()
