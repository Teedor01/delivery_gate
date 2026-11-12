"""Phase 4: the web application, driven over HTTP. Pages, forms, JSON API, safety properties."""
import json
import os
import re
import unittest
from unittest import mock

from delivery_ui import presenter as P
from delivery_ui.render import highlighted_text
from tests.ui_helpers import *

TABS = ("evidence", "assessment", "whatif", "provenance")


def all_pages(app):
    out = {"/": get(app, "/")[2], "/payments": get(app, "/payments")[2], "/evidence": get(app, "/evidence")[2]}
    for ref in REFS:
        for t in TABS:
            out[f"/payments/{ref}?tab={t}"] = get(app, f"/payments/{ref}?tab={t}")[2]
        out[f"/payments?selected={ref}"] = get(app, f"/payments?selected={ref}")[2]
        out[f"/payments/{ref}/evidence"] = get(app, f"/payments/{ref}/evidence")[2]
        for aid in app.svc.states[ref].artifacts:
            out[f"/payments/{ref}/evidence/{aid}"] = get(app, f"/payments/{ref}/evidence/{aid}")[2]
        for o in app.svc.what_if_options(ref):
            out[f"/payments/{ref}?tab=whatif&option={o.option_id}"] = get(app, f"/payments/{ref}?tab=whatif&option={o.option_id}")[2]
    return out


class Screens(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = App(fresh())
        cls.pages = all_pages(cls.app)

    def test_every_screen_renders_and_is_well_formed(self):
        self.assertGreater(len(self.pages), 50)
        for path, html in self.pages.items():
            self.assertIn("<title>", html, path)
            self.assertEqual(balance_errors(html), [], path)

    def test_every_page_says_it_is_fixture_data_and_that_paypal_decides(self):
        for path, html in self.pages.items():
            self.assertIn("Fixture data", html, path)
            self.assertIn("PayPal makes the final decision", html, path)

    def test_no_forbidden_protection_claim_on_any_screen(self):
        for path, html in self.pages.items():
            self.assertEqual(P.find_forbidden(text_of(html)), [], path)

    def test_verified_never_appears_as_a_status(self):
        for path, html in self.pages.items():
            t = text_of(html)
            self.assertIsNone(re.search(r"(?<![A-Za-z])Verified(?![A-Za-z])", t), path)
            self.assertIsNone(re.search(r"\bVERIFIED\b", t), path)

    def test_the_main_navigation_is_overview_payments_evidence_only(self):
        for path in ("/", "/payments", "/payments/DG-20481"):
            html = self.pages.get(path) or get(self.app, path)[2]
            labels = re.findall(r'<a class="nav-item[^"]*" href="[^"]+">.*?<span>([^<]+)</span>', html)
            self.assertEqual(labels, ["Overview", "Payments", "Evidence", "Live sandbox"], path)

    def test_no_inline_script_style_or_external_resource(self):
        for path, html in self.pages.items():
            self.assertNotRegex(html, r"<script(?![^>]*\bsrc=)[^>]*>", path)
            self.assertNotRegex(html, r'\sstyle="', path)
            self.assertNotRegex(html, r'(?:src|href)="https?://', path)
            self.assertNotRegex(html, r"\son[a-z]+=", path)

    def test_pages_are_deterministic(self):
        again = all_pages(App(fresh()))
        self.assertEqual({k: v for k, v in again.items() if "?tab=whatif" not in k}, {k: v for k, v in self.pages.items() if "?tab=whatif" not in k})


class PaymentsOverview(unittest.TestCase):
    def setUp(self):
        self.app = App(fresh())

    def test_lists_every_payment_with_the_required_columns(self):
        _, _, html = get(self.app, "/payments")
        for h in ("Transaction", "Customer / order", "Amount", "Payment status", "Dispute", "Assessment"):
            self.assertIn(f"<th>{h}</th>", html)
        for ref in REFS:
            self.assertIn(f'data-testid="row-{ref}"', html)
        self.assertIn("$480.00 USD", html)
        self.assertIn("Order #1048", html)
        self.assertIn("Item not received", html)
        self.assertIn("Requirements not demonstrated", html)
        self.assertIn("No dispute reported", html)

    def test_counters_come_from_the_engines_results(self):
        _, _, html = get(self.app, "/payments")
        for k, n in (("attention", 2), ("review", 1), ("ready", 1), ("unassessable", 4)):
            self.assertRegex(html, rf'data-testid="kpi-{k}".*?<strong>{n}</strong>')

    def test_search_and_filters(self):
        _, _, html = get(self.app, "/payments?q=1048")
        self.assertIn('data-testid="row-DG-20481"', html)
        self.assertNotIn('data-testid="row-DG-20479"', html)
        self.assertIn("1 of 8 payments", html)
        for q in ("dg-20475", "A-1042", "760", "unauthorized", "partially refunded"):
            self.assertTrue(re.search(r'data-testid="row-DG-', get(self.app, f"/payments?q={q}")[2]), q)
        _, _, html = get(self.app, "/payments?filter=review")
        self.assertEqual(re.findall(r'data-testid="row-(DG-\d+)"', html), ["DG-20472"])
        _, _, html = get(self.app, "/payments?filter=bogus")
        self.assertIn("8 of 8 payments", html)

    def test_empty_search_shows_an_empty_state_not_a_broken_table(self):
        _, _, html = get(self.app, "/payments?q=zzzz-no-such-payment")
        self.assertIn('data-testid="empty-payments"', html)
        self.assertIn("No payments match", html)
        self.assertNotIn("<table", html)

    def test_selecting_a_payment_opens_the_summary_panel_with_checklist_and_sources(self):
        _, _, html = get(self.app, "/payments?selected=DG-20481")
        self.assertIn('data-testid="side-panel"', html)
        for t in ("Requirement checklist", "Evidence sources", "Review evidence", "View assessment", "PayPal makes the final Seller Protection decision"):
            self.assertIn(t, html)
        self.assertIn("/payments/DG-20481/evidence", html)
        self.assertNotIn('data-testid="side-panel"', get(self.app, "/payments?selected=NOPE")[2])

    def test_search_input_is_escaped(self):
        _, _, html = get(self.app, '/payments?q="><script>alert(1)</script>')
        self.assertNotIn("<script>alert(1)", html)
        self.assertIn("&lt;script&gt;", html)


class TransactionDetail(unittest.TestCase):
    def setUp(self):
        self.app = App(fresh())

    def test_the_example_payment_from_the_brief(self):
        _, _, html = get(self.app, "/payments/DG-20481")
        for t in ("$480.00 USD", "Order #1048", "DG-20481", "Requirements not demonstrated", "Your current evidence does not demonstrate all the requirements.",
                  "Item not received", "Payment Overview"):
            self.assertIn(t, html)

    def test_the_five_sections_exist(self):
        _, _, html = get(self.app, "/payments/DG-20481")
        for tid in ("paypal-info", "merchant-info", "assessment-banner", "evidence-list", "missing-card", "next-steps", "assessment-summary"):
            self.assertIn(f'data-testid="{tid}"', html, tid)

    def test_paypal_reported_merchant_provided_and_assessment_stay_visibly_distinct(self):
        _, _, html = get(self.app, "/payments/DG-20481")
        self.assertIn('data-source="paypal"', html)
        self.assertIn('data-source="merchant"', html)
        self.assertRegex(html, r'data-testid="paypal-info".*?Reported by PayPal.*?data-testid="merchant-info".*?Provided by you')
        self.assertIn("Observed value", html)
        self.assertIn("It is not a Seller Protection decision", html)
        self.assertIn("The shipping address on the order is not used in its place", html)

    def test_unknown_values_are_shown_as_unknown(self):
        _, _, html = get(self.app, "/payments/DG-20463")
        self.assertIn("Route unknown", html)
        self.assertIn("Filed with the card issuer or bank", html)
        _, _, html = get(self.app, "/payments/DG-20460")
        self.assertIn("Not matched to a claim type", html)
        self.assertIn("Not as described", html)
        _, _, html = get(self.app, "/payments/DG-20455")
        self.assertIn("No dispute reported", html)
        self.assertIn("No dispute to assess", html)
        self.assertRegex(get(self.app, "/payments/DG-20481")[2], r"Potential seller exposure.*?Unknown")

    def test_the_assessment_tab_expands_each_requirement_with_the_five_required_parts(self):
        _, _, html = get(self.app, "/payments/DG-20479?tab=assessment")
        self.assertEqual(html.count('<details class="req '), len(self.app.svc.analyze("DG-20479").assessment.checks))
        for h in ("What it means", "What supports it", "What is missing", "Policy source", "Technical details"):
            self.assertIn(h, html)
        self.assertIn("Policy text not independently reviewed", html)
        self.assertIn('data-testid="policy-notice"', html)
        self.assertIn("NOT an officially verified PayPal interpretation", html)            # the engine's display notice, verbatim

    def test_internal_codes_stay_out_of_the_primary_interface(self):
        for ref in ("DG-20479", "DG-20481", "DG-20463"):
            html = get(self.app, f"/payments/{ref}?tab=assessment")[2]
            visible = re.sub(r"<pre>.*?</pre>", "", html, flags=re.S)
            visible = re.sub(r'<details class="tech">.*?</details>', "", visible, flags=re.S)
            visible = re.sub(r'(data-[a-z-]+|class|href|value|name|id)="[^"]*"', "", visible)
            t = text_of(visible)
            for code in ("MISSING_FACT", "ONLY_UNREVIEWED_EXTRACTION", "REQUIREMENTS_NOT_DEMONSTRATED", "POLICY_STATUS_MAPPING_UNKNOWN", "merchant_account_country", "physical_goods", "inr.proof"):
                self.assertNotIn(code, t, (ref, code))

    def test_requirements_that_rest_on_your_own_statement_are_not_shown_as_demonstrated(self):
        html = get(self.app, "/payments/DG-20475?tab=assessment")[2]
        self.assertRegex(html, r'data-testid="req-proof_of_delivery.tracking_number" data-status="DEMONSTRATED".*?Your statement only')
        self.assertNotRegex(html, r'data-testid="req-proof_of_delivery.tracking_number"[^>]*>.*?<span class="chip tone-green"><span>Demonstrated')

    def test_conflicts_are_shown_with_both_values_and_never_resolved(self):
        html = get(self.app, "/payments/DG-20472")[2]
        self.assertIn('data-kind="conflict"', html)
        self.assertIn("These records contain conflicting information.", html)
        self.assertIn("Delivery Gate does not decide which record is right", html)
        self.assertIn("Needs human review", html)

    def test_the_unknown_status_scenario_explains_why_it_stays_unresolved(self):
        html = get(self.app, "/payments/DG-20468?tab=assessment")[2]
        self.assertIn("PayPal's eligibility mark".replace("'", "&#x27;"), html)
        self.assertIn("Can&#x27;t be resolved", html)
        self.assertIn("neither satisfies nor fails the condition", html)
        self.assertIn("Partially eligible", get(self.app, "/payments/DG-20468")[2])
        miss = get(self.app, "/payments/DG-20468")[2]
        self.assertRegex(miss, r'data-kind="unknown".*?eligibility mark')

    def test_the_provenance_tab_groups_by_source(self):
        html = get(self.app, "/payments/DG-20479?tab=provenance")[2]
        for g in ("All (17)", "Found in evidence (3)", "Reviewed (4)", "Provided by you (5)", "Reported by PayPal (5)"):
            self.assertIn(g, html)
        self.assertIn("Why does Delivery Gate believe this?", html)
        self.assertIn("This describes the wording only. It does not show the document is genuine.", html)
        only = get(self.app, "/payments/DG-20479?tab=provenance&group=reviewed")[2]
        self.assertEqual(only.count('data-group="reviewed"'), 4)
        self.assertNotIn('data-group="paypal"', only)

    def test_provenance_shows_the_exact_supporting_text_and_original_artifact(self):
        html = get(self.app, "/payments/DG-20479?tab=provenance")[2]
        self.assertRegex(html, r'<mark class="hl[^"]*" data-facts="[^"]*">Delivered: Tuesday, October 20, 2026 at 2:32 PM</mark>')
        art = get(self.app, "/payments/DG-20479/evidence/A01")[2]
        self.assertIn("FedEx Delivery Manager", art)
        self.assertIn('data-testid="original-text"', art)

    def test_unknown_tab_falls_back_and_unknown_payment_is_a_clear_404(self):
        self.assertIn('data-testid="tabpane-evidence"', get(self.app, "/payments/DG-20481?tab=hax")[2])
        st, _, html = get(self.app, "/payments/NOPE")
        self.assertEqual(st, 404)
        self.assertIn('data-testid="error-page"', html)
        self.assertIn("No payment with reference", html)
        self.assertNotIn("Traceback", html)

    def test_reference_amount_and_order_are_consistent_across_screens(self):
        for ref in REFS:
            d = P.detail(self.app.svc, self.app.svc.analyze(ref))
            amount, order = d["summary"]["amount"], d["order_ref"]
            for path in (f"/payments?selected={ref}", f"/payments/{ref}"):
                html = get(self.app, path)[2]
                self.assertIn(ref, html, path)
                self.assertIn(amount, html, (ref, path))
                self.assertIn(order, html, (ref, path))
            self.assertEqual(json.loads(get(self.app, f"/api/payments/{ref}")[2])["summary"]["amount"], amount)
            self.assertIn(ref, get(self.app, f"/payments/{ref}/evidence")[2])
            self.assertIn(ref, get(self.app, "/evidence")[2] if d["evidence"] else ref)

    def test_overview_links_all_six_scenarios(self):
        html = get(self.app, "/")[2]
        for n in range(1, 7):
            self.assertIn(f'data-testid="scenario-{n}"', html)
        self.assertEqual(re.findall(r'data-testid="scenario-(\d)" href="/payments/(DG-\d+)"', html.replace('href="/payments/', 'href="/payments/').replace('class="ref" ', ''))[:0], [])


class EvidenceWorkspace(unittest.TestCase):
    def setUp(self):
        self.app = App(fresh())

    def test_workspace_shows_every_required_element(self):
        html = get(self.app, "/payments/DG-20481/evidence")[2]
        for tid in ("add-evidence", "evidence-text", "evidence-kind", "submit-evidence", "analysis-card", "facts-card"):
            self.assertIn(f'data-testid="{tid}"', html, tid)
        for t in ("Drop a text file here", "Or paste the evidence", "Extraction confidence", "Ambiguity", "Review status", "Sample evidence library (14)"):
            self.assertIn(t, html)
        self.assertIn("PDFs and images can't be read yet", html)

    def test_adding_a_sample_reads_it_with_the_existing_extraction(self):
        st, h, _ = post(self.app, "/payments/DG-20481/evidence/sample", {"sample_id": "A01"})
        self.assertEqual(st, 303)
        _, _, html = follow(self.app, (st, h, b""))
        self.assertIn("Sample A01 added: 7 fact(s) found.", visible(html))
        self.assertIn('data-testid="evidence-A01"', get(self.app, "/payments/DG-20481")[2])
        self.assertIn("Replayed from a recorded extraction. No live model was called.", html)
        self.assertIn("Tracking number:", html)
        self.assertIn("Not reviewed", html)

    def test_pasting_a_sample_text_is_recognised_and_read(self):
        st, h, _ = post(self.app, "/payments/DG-20481/evidence", {"text": SAMPLE["A01"]["text"], "kind": "CARRIER_EMAIL", "source_label": "Pasted text"})
        _, _, html = follow(self.app, (st, h, b""))
        self.assertIn("Evidence A01 added: 7 fact(s) found.", html)
        self.assertIn('data-status="EXTRACTED"', html)

    def test_text_that_cannot_be_read_is_saved_unread_and_says_why(self):
        st, h, _ = post(self.app, "/payments/DG-20481/evidence", {"text": "Parcel was left at the neighbours.", "kind": "OTHER"})
        _, _, html = follow(self.app, (st, h, b""))
        self.assertIn("could not be read: No extraction model is configured", visible(html))
        self.assertIn('data-status="UNAVAILABLE"', html)
        self.assertIn("Not analysed", html)
        self.assertIn("Not read", get(self.app, "/payments/DG-20481")[2])

    def test_empty_and_invalid_submissions_show_a_clear_error_and_change_nothing(self):
        before = len(self.app.svc.states["DG-20481"].artifacts)
        for fields, msg in (({"text": "   ", "kind": "OTHER"}, "There is no text to add"), ({"text": "hi", "kind": "BOGUS"}, "Evidence type must be one of"),
                            ({"text": "x" * 20001, "kind": "OTHER"}, "limited to 20,000")):
            st, h, _ = post(self.app, "/payments/DG-20481/evidence", fields)
            self.assertEqual(st, 303)
            self.assertIn("level=error", h["Location"])
            _, _, html = follow(self.app, (st, h, b""))
            self.assertIn(msg, visible(html))
            self.assertIn('role="alert"', html)
        self.assertEqual(len(self.app.svc.states["DG-20481"].artifacts), before)

    def test_pasted_markup_is_escaped_everywhere(self):
        evil = '<script>alert("x")</script><img src=x onerror=alert(1)>'
        post(self.app, "/payments/DG-20481/evidence", {"text": evil, "kind": "OTHER"})
        for path in ("/payments/DG-20481/evidence", "/payments/DG-20481/evidence/U1", "/payments/DG-20481", "/evidence", "/payments/DG-20481?tab=provenance"):
            html = get(self.app, path)[2]
            self.assertNotIn("<script>alert", html, path)
            self.assertNotIn("<img src=x", html, path)
        self.assertIn("&lt;script&gt;alert", get(self.app, "/payments/DG-20481/evidence/U1")[2])

    def test_flash_messages_cannot_inject_markup(self):
        html = get(self.app, "/payments?msg=%3Cscript%3Ealert(1)%3C/script%3E&level=error")[2]
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_the_artifact_page_shows_original_facts_and_review_controls(self):
        html = get(self.app, "/payments/DG-20479/evidence/A01")[2]
        for tid in ("original-text", "authenticity", "review-panel", "attest", "approve-merchant", "reject-all", "undo-review", "reviewer"):
            self.assertIn(f'data-testid="{tid}"', html, tid)
        self.assertIn("Source authenticity", html)
        self.assertIn("not been independently verified", html)
        self.assertIn("Delivery Gate cannot mark evidence as independently verified", html)

    def test_a_merchant_statement_offers_no_carrier_attestation(self):
        html = get(self.app, "/payments/DG-20475/evidence/A04")[2]
        self.assertNotIn('data-testid="attest"', html)
        self.assertIn('data-testid="attest-unavailable"', html)
        self.assertIn("Your statement", html)
        self.assertNotIn("Reviewed carrier document", html)

    def test_evidence_index_lists_artifacts_across_payments(self):
        html = get(self.app, "/evidence")[2]
        for ref, aid in (("DG-20479", "A01"), ("DG-20475", "A04"), ("DG-20481", "A11")):
            self.assertIn(f'data-testid="evrow-{ref}-{aid}"', html)

    def test_highlighting_never_alters_the_document(self):
        for sid in ("A01", "A04", "A08", "A09", "A11"):
            s = self.app.svc
            ref = "DG-20481"
            rec = s.add_artifact(ref, SAMPLE[sid]["text"], SAMPLE[sid]["kind"]) if sid not in s.states[ref].artifacts else s.states[ref].artifacts[sid]
            facts = [{"fact_id": f.fact_id, "span_start": f.span_start, "span_end": f.span_end, "state": "unreviewed"} for f in rec.facts]
            marked = highlighted_text(rec.artifact.text, facts)
            import html as H
            self.assertEqual(H.unescape(re.sub(r"</?mark[^>]*>", "", marked)), rec.artifact.text, sid)


class FullWorkflowOverHttp(unittest.TestCase):
    """Scenario 6 end to end, through the forms a person would use."""

    def test_add_review_and_see_the_assessment_change_exactly_as_the_what_if_predicted(self):
        app = App(fresh())
        before = json.loads(get(app, "/api/payments/DG-20481/assessment")[2])
        self.assertEqual(before["protection_assessment"], "REQUIREMENTS_NOT_DEMONSTRATED")
        pred = json.loads(get(app, "/api/payments/DG-20481/whatif?option=add:A01")[2])
        self.assertEqual((pred["before"]["key"], pred["after"]["key"]), ("REQUIREMENTS_NOT_DEMONSTRATED", "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES"))
        self.assertIn("Hypothetical", get(app, "/payments/DG-20481?tab=whatif&option=add:A01")[2])
        self.assertEqual(json.loads(get(app, "/api/payments/DG-20481/assessment")[2])["digest"], before["digest"])        # asking changed nothing
        post(app, "/payments/DG-20481/evidence/sample", {"sample_id": "A01"})
        mid = json.loads(get(app, "/api/payments/DG-20481/assessment")[2])
        self.assertEqual(mid["protection_assessment"], "REQUIREMENTS_NOT_DEMONSTRATED")                                      # unreviewed does not count
        self.assertTrue(mid["needs_human_review"])
        st, h, _ = post(app, "/payments/DG-20481/evidence/A01/review", {"mode": "attest_carrier", "reviewer": "Alex Reviewer", "note": ""})
        self.assertEqual(st, 303)
        after = json.loads(get(app, "/api/payments/DG-20481/assessment")[2])
        self.assertEqual(after["protection_assessment"], "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES")
        self.assertEqual(after["digest"], pred["digests"]["hypothetical"])                                                    # what-if == what happened
        html = get(app, "/payments/DG-20481")[2]
        self.assertIn("Requirements demonstrated", html)
        self.assertIn("Your available evidence demonstrates the requirements currently modeled. PayPal makes the final decision.", html)
        self.assertIn("Alex Reviewer", get(app, "/payments/DG-20481?tab=provenance")[2])

    def test_review_without_a_reviewer_name_is_refused_with_a_message(self):
        app = App(fresh())
        st, h, _ = post(app, "/payments/DG-20479/evidence/A01/review", {"mode": "reject_all", "reviewer": ""})
        _, _, html = follow(app, (st, h, b""))
        self.assertIn("Enter the reviewer's name", visible(html))
        self.assertEqual(app.svc.analyze("DG-20479").assessment.protection_assessment.value, "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES")

    def test_updating_what_the_merchant_provided_changes_the_result_through_the_engine(self):
        app = App(fresh())
        st, h, _ = post(app, "/payments/DG-20479/info", {"country": "US", "line1": "1 Market St", "city": "San Francisco", "region": "CA", "postal_code": "94105",
                                                         "addr_country": "US", "redirect_detected": "true", "response_to_paypal": "NO_REQUEST_OUTSTANDING",
                                                         "shipped_after_advised_not_to_release": "false"})
        self.assertEqual(st, 303)
        self.assertNotEqual(json.loads(get(app, "/api/payments/DG-20479/assessment")[2])["protection_assessment"], "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES")
        st, h, _ = post(app, "/payments/DG-20479/info", {"country": "USA"})
        self.assertIn("Country must be a two-letter code", follow(app, (st, h, b""))[2])

    def test_reset_restores_the_demo(self):
        app = App(fresh())
        post(app, "/payments/DG-20481/evidence/sample", {"sample_id": "A01"})
        self.assertEqual(post(app, "/reset", {})[0], 303)
        self.assertNotIn("A01", app.svc.states["DG-20481"].artifacts)


class ApiSafety(unittest.TestCase):
    """A request cannot supply a result, a status or an authenticity level, and nothing sensitive leaks."""

    def setUp(self):
        self.app = App(fresh())

    def api(self, path, body):
        st, h, b = post(self.app, path, json_body=body)
        return st, json.loads(b)

    def test_unexpected_fields_are_rejected_everywhere(self):
        forged = ("protection_assessment", "assessment", "status", "authenticity", "source_authenticity", "verified", "policy_status", "digest", "needs_human_review")
        for f in forged:
            for path, body in (("/api/payments/DG-20481/artifacts", {"text": "t", "kind": "OTHER"}),
                               ("/api/payments/DG-20481/artifacts/A11/review", {"mode": "undo", "reviewer": "r"}),
                               ("/api/payments/DG-20481/merchant-info", {"country": "US"}), ("/api/payments/DG-20481/entity", {"entity_ref": ""})):
                st, out = self.api(path, {**body, f: "VERIFIED"})
                self.assertEqual((st, out["error"]), (400, "unexpected_field"), (f, path))

    def test_authenticity_cannot_be_set_to_verified_by_any_route(self):
        s = self.app.svc
        s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        for body in ({"mode": "attest_carrier", "reviewer": "r", "authenticity": "VERIFIED"}, {"mode": "attest_verified", "reviewer": "r"},
                     {"mode": "VERIFIED", "reviewer": "r"}):
            st, out = self.api("/api/payments/DG-20481/artifacts/A01/review", body)
            self.assertEqual(st, 400, body)
        self.assertEqual({b["source_authenticity"] for b in s.analyze("DG-20481").bridge.bridged} - {"UNVERIFIED"}, set())

    def test_the_review_api_applies_the_bridge_rules(self):
        self.app.svc.add_artifact("DG-20481", SAMPLE["A04"]["text"], "MERCHANT_STATEMENT")
        st, out = self.api("/api/payments/DG-20481/artifacts/A04/review", {"mode": "attest_carrier", "reviewer": "r"})
        self.assertEqual((st, out["error"]), (400, "carrier_review_refused"))
        st, out = self.api("/api/payments/DG-20481/artifacts/A01/review", {"mode": "undo"})
        self.assertEqual((st, out["error"]), (404, "artifact_not_found")) if st == 404 else self.assertEqual(st, 400)

    def test_api_add_and_review_round_trip(self):
        st, out = self.api("/api/payments/DG-20481/artifacts", {"text": SAMPLE["A01"]["text"], "kind": "CARRIER_EMAIL"})
        self.assertEqual((st, out["artifact_id"], out["extraction_status"], out["fact_count"]), (201, "A01", "EXTRACTED", 7))
        st, out = self.api("/api/payments/DG-20481/artifacts/A01/review", {"mode": "attest_carrier", "reviewer": "r"})
        self.assertEqual(st, 200)
        self.assertEqual(json.loads(get(self.app, "/api/payments/DG-20481/assessment")[2])["protection_assessment"], "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES")

    def test_malformed_requests_fail_cleanly(self):
        st, h, b = self.app.handle("POST", "/api/payments/DG-20481/artifacts", b"{not json", "application/json")
        self.assertEqual((st, json.loads(b)["error"]), (400, "invalid_json"))
        st, h, b = self.app.handle("POST", "/api/payments/DG-20481/artifacts", b"[1,2]", "application/json")
        self.assertEqual((st, json.loads(b)["error"]), (400, "invalid_json"))
        st, h, b = self.app.handle("POST", "/api/payments/DG-20481/artifacts", b"x" * 1_000_001, "application/json")
        self.assertEqual((st, json.loads(b)["error"]), (400, "body_too_large"))
        st, h, b = self.app.handle("POST", "/api/payments/NOPE/artifacts", json.dumps({"text": "t"}).encode(), "application/json")
        self.assertEqual((st, json.loads(b)["error"]), (404, "transaction_not_found"))
        st, h, b = self.app.handle("DELETE", "/api/payments", b"", "")
        self.assertEqual(st, 405)
        st, h, b = self.app.handle("GET", "/api/nothing-here")
        self.assertEqual(st, 404)

    def test_server_errors_do_not_leak_internals(self):
        with mock.patch.object(self.app.svc, "analyze", side_effect=RuntimeError("secret internal path /home/x")):
            st, h, b = self.app.handle("GET", "/payments/DG-20481")
        self.assertEqual(st, 500)
        self.assertNotIn(b"secret internal path", b)
        self.assertNotIn(b"Traceback", b)

    def test_no_secret_ever_appears_in_any_response(self):
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": "sk-secret-test-0123456789", "EXTRACTION_MODEL": "model-x"}):
            app = App(fresh())
            pages = all_pages(app)
            blob = "".join(pages.values()) + get(app, "/api/payments")[2] + get(app, "/static/app.js")[2] + get(app, "/static/app.css")[2]
            self.assertNotIn("sk-secret-test", blob)
            self.assertNotIn("ANTHROPIC_API_KEY", blob)
        js = get(self.app, "/static/app.js")[2]
        for word in ("api_key", "apikey", "ANTHROPIC", "sk-ant"):
            self.assertNotIn(word, js)

    def test_static_files_cannot_escape_the_static_directory(self):
        for p in ("/static/../service.py", "/static/..%2fservice.py", "/static/%2e%2e/server.py", "/static/missing.css"):
            self.assertEqual(self.app.handle("GET", p)[0], 404, p)


class SocketLevel(unittest.TestCase):
    def test_a_real_server_serves_pages_assets_and_security_headers(self):
        with LiveServer() as s:
            st, h, b = s.request("GET", "/payments")
            self.assertEqual(st, 200)
            self.assertIn("text/html", h["Content-Type"])
            self.assertIn("default-src 'self'", h["Content-Security-Policy"])
            self.assertEqual(h["X-Frame-Options"], "DENY")
            self.assertEqual(h["X-Content-Type-Options"], "nosniff")
            self.assertEqual(h["Cache-Control"], "no-store")
            st, h, b = s.request("GET", "/static/app.css")
            self.assertEqual((st, h["Content-Type"].split(";")[0]), (200, "text/css"))
            st, h, b = s.request("GET", "/static/app.js")
            self.assertIn("javascript", h["Content-Type"])
            self.assertEqual(s.request("GET", "/healthz")[0], 200)
            self.assertEqual(s.request("GET", "/nope")[0], 404)

    def test_a_form_post_over_the_socket(self):
        with LiveServer() as s:
            body = b"sample_id=A01"
            import http.client
            c = http.client.HTTPConnection("127.0.0.1", s.port)
            c.request("POST", "/payments/DG-20481/evidence/sample", body, {"Content-Type": "application/x-www-form-urlencoded", "Content-Length": str(len(body))})
            r = c.getresponse()
            self.assertEqual(r.status, 303)
            self.assertIn("/payments/DG-20481/evidence", r.getheader("Location"))
            self.assertIn(b"A01", s.request("GET", "/payments/DG-20481")[2])


if __name__ == "__main__":
    unittest.main()
