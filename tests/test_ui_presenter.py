"""Phase 4: plain-language presentation. The presenter maps engine values to words; it never decides."""
import json
import re
import unittest

from delivery_gate.engine import UNREVIEWED_NOTICE
from delivery_gate.models import EvidenceStatus, ProtectionAssessment as PA
from delivery_ui import presenter as P
from tests.ui_helpers import *


def details(s=None):
    s = s or fresh()
    return s, {ref: P.detail(s, s.analyze(ref)) for ref in REFS}


class Wording(unittest.TestCase):
    """The exact translations required for the six statuses."""

    def test_status_messages_are_the_ones_specified(self):
        self.assertEqual(P.PROTECTION_VIEW["REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES"]["message"],
                         "Your available evidence demonstrates the requirements currently modeled. PayPal makes the final decision.")
        self.assertEqual(P.PROTECTION_VIEW["REQUIREMENTS_NOT_DEMONSTRATED"]["message"], "Your current evidence does not demonstrate all the requirements.")
        self.assertEqual(P.PROTECTION_VIEW["UNKNOWN"]["message"], "We don't have enough verified information to assess this requirement.")
        self.assertEqual(P.CHECK_VIEW["CONTRADICTED"]["message"], "These records contain conflicting information.")
        self.assertEqual(P.CHECK_VIEW["NEEDS_HUMAN_REVIEW"]["message"], "This information needs to be checked before it can be relied upon.")
        self.assertEqual(P.PROTECTION_VIEW["NOT_COVERED"]["message"], "This type of claim is not covered by the Seller Protection rules currently modeled.")

    def test_every_engine_status_has_a_translation(self):
        self.assertEqual({m.value for m in PA} - set(P.PROTECTION_VIEW), set())
        self.assertEqual({m.value for m in EvidenceStatus} - set(P.CHECK_VIEW), set())

    def test_internal_codes_are_not_the_primary_labels(self):
        for v in list(P.PROTECTION_VIEW.values()) + list(P.CHECK_VIEW.values()):
            self.assertFalse(re.search(r"[A-Z]{3,}_[A-Z_]{3,}", v["label"] + v["message"]), v)

    def test_every_reason_code_the_engine_gives_for_these_payments_has_plain_language(self):
        s, ds = details()
        for ref in REFS:
            for c in s.analyze(ref).assessment.checks:
                self.assertIn(c.reason_code, P.REASON_TEXT, (ref, c.check_id))

    def test_every_requirement_has_a_plain_title(self):
        s, ds = details()
        for ref, d in ds.items():
            for r in d["requirements"]:
                self.assertIn(r["key"], P.REQUIREMENTS, (ref, r["check_id"]))
                self.assertNotRegex(r["title"], r"[a-z]+_[a-z]+")

    def test_no_forbidden_protection_claims_anywhere_in_the_view_models(self):
        s, ds = details()
        for ref, d in ds.items():
            blob = json.dumps(d)
            self.assertEqual(P.find_forbidden(blob), [], ref)
        s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        s.review_artifact("DG-20481", "A01", "attest_carrier", "R")
        self.assertEqual(P.find_forbidden(json.dumps(P.detail(s, s.analyze("DG-20481")))), [])
        for opt in s.what_if_options("DG-20479") + s.what_if_options("DG-20481"):
            pass
        w = P.what_if_view(fresh(), fresh().analyze("DG-20481"), fresh().what_if("DG-20481", "add:A01"))
        self.assertEqual(P.find_forbidden(json.dumps(w)), [])

    def test_the_forbidden_phrase_guard_actually_catches_them(self):
        for phrase in ("You are protected", "PayPal will approve this", "You will win this dispute", "Guaranteed Seller Protection", "Likely to Qualify"):
            self.assertTrue(P.find_forbidden(phrase), phrase)
        self.assertEqual(P.find_forbidden("PayPal makes the final decision."), [])


class OverallStatus(unittest.TestCase):
    def test_the_banner_follows_the_engine_for_every_payment(self):
        s, ds = details()
        expect = {"DG-20479": "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES", "DG-20481": "REQUIREMENTS_NOT_DEMONSTRATED", "DG-20472": "NEEDS_HUMAN_REVIEW",
                  "DG-20475": "REQUIREMENTS_NOT_DEMONSTRATED", "DG-20468": "UNKNOWN", "DG-20463": "UNKNOWN", "DG-20460": "UNKNOWN", "DG-20455": "NO_DISPUTE"}
        for ref, key in expect.items():
            self.assertEqual(ds[ref]["overall"]["key"], key, ref)

    def test_needs_human_review_uses_the_engines_own_flag(self):
        s, ds = details()
        for ref in REFS:
            a = s.analyze(ref).assessment
            self.assertEqual(ds[ref]["overall"]["needs_human_review"], a.needs_human_review, ref)

    def test_buckets_cover_every_payment_and_match_the_engine(self):
        s, ds = details()
        rows = [d["summary"] for d in ds.values()]
        self.assertEqual(P.counters(rows), {"attention": 2, "review": 1, "ready": 1, "unassessable": 4})
        self.assertEqual(sum(P.counters(rows).values()), len(REFS))
        self.assertEqual(ds["DG-20479"]["summary"]["bucket"], "ready")
        self.assertEqual(ds["DG-20472"]["summary"]["bucket"], "review")

    def test_a_not_demonstrated_status_can_never_be_presented_as_demonstrated(self):
        s, ds = details()
        for ref, d in ds.items():
            if s.analyze(ref).assessment.protection_assessment != PA.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES:
                self.assertNotEqual(d["overall"]["tone"], "green", ref)
                self.assertNotIn("demonstrated", d["overall"]["label"].lower().replace("not demonstrated", ""), ref)

    def test_the_policy_notice_is_the_engines_and_always_present(self):
        s, ds = details()
        for ref, d in ds.items():
            self.assertEqual(d["display_notice"], UNREVIEWED_NOTICE, ref)
            self.assertEqual(d["policy_status"], s.analyze(ref).assessment.policy_status, ref)         # passed through, not invented
            want = "NO_RULE_SELECTED" if ref in ("DG-20460", "DG-20455") else "UNREVIEWED"                # a selected rule is always unreviewed
            self.assertEqual(d["policy_status"], want, ref)
            self.assertEqual(d["paypal_acceptance"], "NOT_ESTABLISHED", ref)


class StatementsAndAuthenticity(unittest.TestCase):
    def setUp(self):
        self.s, self.ds = details()

    def test_a_merchant_statement_is_never_shown_like_a_corroborated_requirement(self):
        d = self.ds["DG-20475"]
        trk = next(r for r in d["requirements"] if r["key"] == "proof_of_delivery.tracking_number")
        self.assertTrue(trk["statement_only"])
        self.assertEqual((trk["label"], trk["tone"]), ("Your statement only", "amber"))
        clean = next(r for r in self.ds["DG-20479"]["requirements"] if r["key"] == "proof_of_delivery.tracking_number")
        self.assertEqual((clean["label"], clean["tone"]), ("Demonstrated", "green"))

    def test_requirements_resting_on_the_merchants_own_answers_are_flagged_even_when_everything_else_is_demonstrated(self):
        d = self.ds["DG-20479"]
        self.assertEqual(set(d["statement_only"]), {"No redirect to another address", "Responded to PayPal on time"})

    def test_authenticity_labels_distinguish_reviewed_from_statements_and_unreviewed(self):
        by = {ref: {e["artifact_id"]: e["authenticity"]["label"] for e in d["evidence"]} for ref, d in self.ds.items()}
        self.assertEqual(by["DG-20479"]["A01"], "Reviewed")
        self.assertEqual(by["DG-20475"]["A04"], "Your statement")
        self.s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        d = P.detail(self.s, self.s.analyze("DG-20481"))
        self.assertEqual({e["artifact_id"]: e["authenticity"]["label"] for e in d["evidence"]}["A01"], "Not reviewed")

    def test_verified_is_never_produced_by_the_ui(self):
        for ref, d in self.ds.items():
            self.assertIsNone(re.search(r"\bVERIFIED\b", json.dumps(d)), ref)
            self.assertNotIn('"Verified"', json.dumps(d))
        for ref in REFS:
            for b in (self.s.analyze(ref).bridge.bridged if self.s.analyze(ref).bridge else []):
                self.assertIn(b["source_authenticity"], ("UNVERIFIED", "REVIEWED"))

    def test_reviewed_text_says_it_was_not_independently_verified(self):
        a = next(e for e in self.ds["DG-20479"]["evidence"] if e["artifact_id"] == "A01")
        self.assertIn("not been independently verified", a["authenticity"]["detail"])

    def test_attribution_is_described_separately_from_authenticity(self):
        f = next(f for e in self.ds["DG-20475"]["evidence"] for f in e["facts"])
        self.assertIn(f["attribution_key"], ("MERCHANT_STATEMENT", "CARRIER_STATEMENT", "UNKNOWN", "CUSTOMER_STATEMENT_RELAYED", "THIRD_PARTY_STATEMENT"))
        a01 = next(f for e in self.ds["DG-20479"]["evidence"] for f in e["facts"] if f["fact"] == "tracking_number")
        self.assertEqual(a01["attribution"], "Written as a statement by the carrier")           # about the wording...
        self.assertEqual(a01["authenticity"]["label"], "Reviewed")                              # ...separate from whether the document is genuine

    def test_attribution_alone_does_not_make_unreviewed_evidence_reviewed(self):
        s = fresh()
        s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        f = next(f for e in P.detail(s, s.analyze("DG-20481"))["evidence"] if e["artifact_id"] == "A01" for f in e["facts"] if f["fact"] == "tracking_number")
        self.assertEqual(f["attribution_key"], "CARRIER_STATEMENT")
        self.assertEqual((f["state"], f["authenticity"]["label"], f["source_kind"]), ("unreviewed", "Not reviewed", "extracted"))


class Provenance(unittest.TestCase):
    def test_every_fact_span_is_the_exact_text_of_its_artifact(self):
        s, ds = details()
        n = 0
        for d in ds.values():
            for e in d["evidence"]:
                for f in e["facts"]:
                    self.assertEqual(e["text"][f["span_start"]:f["span_end"]], f["span"])
                    n += 1
        self.assertGreater(n, 15)

    def test_the_provenance_example_from_the_brief(self):
        s, ds = details()
        e = next(e for e in ds["DG-20479"]["evidence"] if e["artifact_id"] == "A01")
        f = next(f for f in e["facts"] if f["fact"] == "delivery_status")
        self.assertEqual((f["value"], f["artifact_id"], f["artifact_kind"], f["authenticity"]["label"]), ("Delivered", "A01", "Carrier email", "Reviewed"))
        self.assertEqual(f["span"], "Your package was delivered")
        self.assertIn("artifact_sha256", f["details"])                      # technical details are kept in the expandable block

    def test_facts_that_nothing_uses_are_labelled_unused_not_awaiting_review(self):
        s, ds = details()
        f = next(f for e in ds["DG-20479"]["evidence"] for f in e["facts"] if f["fact"] == "carrier_name")
        self.assertEqual((f["state"], f["source_kind"]), ("not_used", "unused"))
        sig = next(f for e in ds["DG-20479"]["evidence"] for f in e["facts"] if f["fact"] == "signature_present")
        self.assertNotIn("DO NOT MODEL", sig["state_note"])
        self.assertIn("not modeled", sig["state_note"])

    def test_requirement_support_points_at_the_facts_that_back_it(self):
        s, ds = details()
        trk = next(r for r in ds["DG-20479"]["requirements"] if r["key"] == "proof_of_delivery.tracking_number")
        self.assertEqual([x["artifact_id"] for x in trk["support"]], ["A01"])
        self.assertEqual(trk["support"][0]["span"], "Tracking number: 774912340001")
        self.assertTrue(trk["policy_sources"] and all(p["review_status"] == "Policy text not independently reviewed" for p in trk["policy_sources"]))

    def test_ambiguity_and_contradictions_are_surfaced(self):
        s, ds = details()
        c = ds["DG-20472"]["contradictions"]
        self.assertTrue(c)
        self.assertTrue(all(x["needs_human_review"] and x["message"] == "These records contain conflicting information." for x in c))
        self.assertEqual({v["artifact_id"] for v in c[0]["values"]}, {"A08", "A09"})
        amb = [f for d in ds.values() for e in d["evidence"] for f in e["facts"] if f["ambiguity"]]
        self.assertTrue(amb)


class UnknownsStayUnknown(unittest.TestCase):
    def setUp(self):
        self.s, self.ds = details()

    def test_external_route_is_unknown_and_explained(self):
        d = self.ds["DG-20463"]
        self.assertFalse(d["paypal"]["dispute"]["route_known"])
        self.assertEqual(d["paypal"]["dispute"]["channel"], "Filed with the card issuer or bank")
        self.assertEqual(d["requirements"], [])                                  # nothing is evaluated when the route is unknown
        g = next(g for g in d["gates"] if g["key"] == "route")
        self.assertEqual(g["outcome"], "Not known")
        self.assertIn("bank return", g["detail"])

    def test_not_as_described_keeps_the_raw_reason_and_is_not_normalised(self):
        d = self.ds["DG-20460"]
        self.assertEqual(d["paypal"]["dispute"]["reason_raw"], "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED")
        self.assertIsNone(d["paypal"]["dispute"]["reason_normalised"])
        self.assertEqual(d["requirements"], [])

    def test_exposure_components_stay_separate_and_unknown_where_unknown(self):
        e = {ref: d["exposure"] for ref, d in self.ds.items()}
        self.assertEqual(e["DG-20472"]["original"]["text"], "$760.00 USD")
        self.assertEqual(e["DG-20472"]["disputed"]["text"], "$320.00 USD")                    # a partial dispute is not the full amount
        self.assertEqual(e["DG-20455"]["disputed"]["text"], "Unknown")
        for ref, x in e.items():
            self.assertEqual(x["potential"]["text"], "Unknown", ref)

    def test_the_seller_protection_status_is_shown_as_observed_not_as_a_decision(self):
        sp = self.ds["DG-20468"]["paypal"]["seller_protection"]
        self.assertEqual((sp["raw"], sp["label"]), ("PARTIALLY_ELIGIBLE", "Partially eligible"))
        self.assertIn("did not receive an item", sp["meaning"])
        self.assertEqual(self.ds["DG-20468"]["overall"]["key"], "UNKNOWN")

    def test_the_shipping_address_on_the_order_is_never_substituted(self):
        s = fresh()
        s.set_merchant_info("DG-20479", {"address": {}})
        d = P.detail(s, s.analyze("DG-20479"))
        self.assertIsNone(d["merchant"]["address"])
        self.assertEqual(s.analyze("DG-20479").case.fact("transaction_details_address"), None)

    def test_lifecycle_stage_is_informational_only(self):
        stages = {ref: d["paypal"]["dispute"]["stage"] for ref, d in self.ds.items() if d["paypal"]["dispute"]}
        self.assertEqual(stages["DG-20463"], "Chargeback")
        s2 = fresh()
        a = s2.analyze("DG-20479")
        self.assertNotIn("dispute_life_cycle_stage", {f.name for f in a.case.transaction_facts})

    def test_an_unresolved_policy_condition_is_explained_in_plain_language(self):
        d = self.ds["DG-20468"]
        c = d["conditions"][0]
        self.assertEqual((c["title"], c["unresolved"], c["outcome"]), ("PayPal's eligibility mark", True, "Can't be resolved"))
        self.assertIn("Partially eligible", c["detail"])
        self.assertIn("neither satisfies nor fails", c["detail"])
        self.assertEqual(c["technical"]["mapping"], "UNKNOWN")
        self.assertEqual(d["next_steps"][0]["kind"], "info")                         # the explanation comes before anything the merchant could add
        self.assertIn("Nothing you add changes that", d["next_steps"][0]["text"])
        for ref in ("DG-20479", "DG-20481"):
            self.assertEqual(self.ds[ref]["conditions"], [])

    def test_an_unmapped_dispute_reason_is_explained_and_not_actionable(self):
        d = self.ds["DG-20460"]
        self.assertIn("not matched to a claim type", d["next_steps"][0]["text"])
        self.assertIn("Not as described", d["next_steps"][0]["text"])

    def test_merchant_jurisdiction_is_labelled_as_provided_by_the_merchant(self):
        d = self.ds["DG-20479"]["merchant"]
        self.assertEqual(d["country"], "US")
        s = fresh()
        f = s.analyze("DG-20479").case.fact("merchant_account_country")
        self.assertEqual((f.provenance.source_type.value, f.provenance.status.value), ("MERCHANT_INPUT", "MERCHANT_ASSERTED"))


class Formatting(unittest.TestCase):
    def test_money_and_dates(self):
        self.assertEqual(P.money("480.00", "USD"), "$480.00 USD")
        self.assertEqual(P.money("12.00", "EUR"), "12.00 EUR")
        self.assertEqual(P.money(None, None), "Unknown")
        self.assertEqual(P.when("2026-10-14T14:32:00Z"), "Oct 14, 2026 · 14:32 UTC")
        self.assertEqual(P.when(None), "Unknown")
        self.assertEqual(P.address_text({"line1": "1 Market St", "city": "San Francisco", "region": "CA", "postal_code": "94105", "country": "US"}),
                         "1 Market St, San Francisco, CA 94105, US")

    def test_reference_amount_and_order_are_consistent_between_summary_and_detail(self):
        s, ds = details()
        for ref, d in ds.items():
            self.assertEqual(d["summary"]["amount"], d["exposure"]["original"]["text"], ref)
            self.assertEqual(d["summary"]["order_ref"], d["order_ref"], ref)


if __name__ == "__main__":
    unittest.main()
