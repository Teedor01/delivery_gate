"""Phase 4: real-browser tests (Chromium via Playwright). Skipped automatically where Playwright or a browser is not available."""
import re
import tempfile
import unittest
from pathlib import Path

from tests.ui_helpers import *

try:
    from playwright.sync_api import sync_playwright
    _pw = sync_playwright().start()
    _browser = _pw.chromium.launch()
except Exception as _e:                                        # noqa: BLE001
    _pw = _browser = None
    _why = f"Playwright/Chromium unavailable: {type(_e).__name__}"


@unittest.skipIf(_browser is None, "Playwright/Chromium unavailable")
class Browser(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.live = LiveServer()
        cls.live.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.live.__exit__(None, None, None)
        try:
            _browser.close()
            _pw.stop()
        except Exception:                                      # noqa: BLE001
            pass

    def setUp(self):
        self.live.srv.app.svc.reset()
        self.ctx = _browser.new_context(viewport={"width": 1672, "height": 941})
        self.page = self.ctx.new_page()
        self.problems = []
        self.page.on("console", lambda m: self.problems.append(f"console {m.type}: {m.text}") if m.type in ("error", "warning") else None)
        self.page.on("pageerror", lambda e: self.problems.append(f"pageerror: {e}"))
        self.page.on("requestfailed", lambda r: self.problems.append(f"requestfailed: {r.url}"))
        self.page.on("response", lambda r: self.problems.append(f"http {r.status}: {r.url}") if r.status >= 400 and "favicon" not in r.url else None)

    def tearDown(self):
        self.ctx.close()

    def go(self, path):
        self.page.goto(self.live.base + path)
        self.page.wait_for_load_state("networkidle")

    def tid(self, name):
        return self.page.get_by_test_id(name)

    # ---- navigation and the payments workspace
    def test_the_styled_app_loads_with_navigation_and_fixture_badge(self):
        self.go("/payments")
        self.assertEqual(self.page.title(), "Payments · Delivery Gate")
        nav = self.page.locator("nav.nav a")
        self.assertEqual([t.strip() for t in nav.all_inner_texts()], ["Overview", "Payments", "Evidence"])
        self.assertIn("Fixture data", self.page.locator(".pill-fixture").inner_text())
        bg = self.page.evaluate("getComputedStyle(document.body).backgroundColor")
        self.assertEqual(bg, "rgb(245, 244, 239)")                                         # Warm Ivory
        side = self.page.evaluate("getComputedStyle(document.querySelector('.side')).backgroundColor")
        self.assertEqual(side, "rgb(16, 28, 44)")                                          # Midnight Navy
        btn = self.page.evaluate("getComputedStyle(document.querySelector('.nav-item.active')).backgroundColor")
        self.assertEqual(btn, "rgb(8, 127, 140)")                                          # Deep Teal
        self.assertEqual(self.problems, [])

    def test_clicking_a_row_opens_the_panel_and_review_evidence_leads_to_the_workspace(self):
        self.go("/payments")
        self.tid("row-DG-20481").click()
        self.page.wait_for_url(re.compile(r"selected=DG-20481"))
        panel = self.tid("side-panel")
        self.assertTrue(panel.is_visible())
        self.assertIn("Requirements not demonstrated", panel.inner_text())
        panel.get_by_role("link", name="Review evidence").click()
        self.page.wait_for_url(re.compile(r"/payments/DG-20481/evidence$"))
        self.assertTrue(self.tid("add-evidence").is_visible())

    def test_search_box_filters_the_table(self):
        self.go("/payments")
        self.page.get_by_label("Search payments").fill("1039")
        self.page.keyboard.press("Enter")
        self.page.wait_for_url(re.compile(r"q=1039"))
        self.assertEqual(self.page.locator("tr.row").count(), 1)
        self.assertIn("DG-20472", self.page.locator("tr.row").inner_text())

    def test_the_kpi_cards_filter(self):
        self.go("/payments")
        self.tid("kpi-attention").click()
        self.page.wait_for_url(re.compile(r"filter=attention"))
        self.assertEqual(self.page.locator("tr.row").count(), 2)

    # ---- the centre of the product
    def test_detail_page_tabs_and_expandable_requirements(self):
        self.go("/payments/DG-20479")
        self.assertIn("Requirements demonstrated", self.tid("assessment-banner").inner_text())
        self.tid("tab-assessment").click()
        self.page.wait_for_url(re.compile(r"tab=assessment"))
        req = self.tid("req-proof_of_delivery.tracking_number")
        body = req.locator(".req-body")
        self.assertFalse(body.is_visible())
        req.locator("summary").first.click()
        self.assertTrue(body.is_visible())
        for t in ("What it means", "What supports it", "What is missing", "Policy source"):
            self.assertIn(t.lower(), body.inner_text().lower())
        self.assertIn("Tracking number: 774912340001", body.inner_text())
        self.assertIn("Evidence A01", body.inner_text())
        self.page.get_by_role("button", name="Expand all").click()
        self.assertEqual(self.page.locator("details.req[open]").count(), self.page.locator("details.req").count())
        self.page.get_by_role("button", name="Collapse all").click()
        self.assertEqual(self.page.locator("details.req[open]").count(), 0)
        self.assertTrue(self.tid("policy-notice").is_visible())
        self.assertEqual(self.problems, [])

    def test_provenance_explains_why_a_fact_is_believed(self):
        self.go("/payments/DG-20479?tab=provenance&group=reviewed")
        row = self.page.locator("details.prov").filter(has_text="Delivery status")
        row.locator("summary").first.click()
        txt = row.inner_text()
        self.assertIn("why does delivery gate believe this?", txt.lower())
        self.assertIn("Reviewed", txt)
        self.assertIn("Your package was delivered", row.locator("mark.hl").inner_text())
        row.get_by_text("Technical details").click()
        self.assertIn("artifact_sha256", row.inner_text())

    # ---- scenario 6, the way a person would do it
    def test_whatif_then_actually_adding_and_reviewing_gives_the_predicted_result(self):
        self.go("/payments/DG-20481")
        self.assertIn("Requirements not demonstrated", self.tid("assessment-banner").inner_text())
        self.tid("tab-whatif").click()
        self.page.get_by_role("link", name="Compare").first.click()
        res = self.tid("whatif-result")
        res.wait_for()
        self.assertIn("Hypothetical", res.inner_text())
        self.assertIn("Requirements demonstrated", self.tid("whatif-hypothetical").inner_text())
        self.assertIn("The result would change", self.tid("whatif-verdict").inner_text())
        # nothing has changed yet
        self.go("/payments/DG-20481")
        self.assertIn("Requirements not demonstrated", self.tid("assessment-banner").inner_text())
        # now do it for real
        self.go("/payments/DG-20481/evidence")
        self.page.get_by_text("Sample evidence library").click()
        self.tid("sample-A01").click()
        self.page.wait_for_url(re.compile(r"/evidence\?"))
        self.assertIn("7 fact(s) found", self.tid("flash").inner_text())
        self.page.goto(self.live.base + "/payments/DG-20481/evidence/A01")
        self.assertIn("Not reviewed", self.tid("authenticity").inner_text())
        self.tid("reviewer").fill("Casey Reviewer")
        self.tid("attest").click()
        self.page.wait_for_url(re.compile(r"/evidence/A01\?"))
        self.assertIn("Reviewed", self.tid("authenticity").inner_text())
        self.assertIn("Casey Reviewer", self.tid("authenticity").inner_text())
        self.go("/payments/DG-20481")
        self.assertIn("Requirements demonstrated", self.tid("assessment-banner").inner_text())
        self.assertIn("PayPal makes the final decision", self.tid("assessment-banner").inner_text())
        self.assertEqual(self.problems, [])

    def test_a_merchant_statement_cannot_be_attested_as_a_carrier_document(self):
        self.go("/payments/DG-20475/evidence/A04")
        self.assertEqual(self.tid("attest").count(), 0)
        self.assertTrue(self.tid("attest-unavailable").is_visible())
        self.assertIn("Your statement", self.tid("authenticity").inner_text())

    def test_the_review_form_requires_a_reviewer_name(self):
        self.go("/payments/DG-20479/evidence/A01")
        self.tid("approve-merchant").click()                                       # browser validation blocks the empty required field
        self.assertIn("evidence/A01", self.page.url)
        self.assertEqual(self.page.evaluate("document.querySelector('#reviewer').validity.valueMissing"), True)

    # ---- the evidence workspace
    def test_pasting_text_that_cannot_be_read_shows_the_unavailable_state(self):
        self.go("/payments/DG-20481/evidence")
        self.tid("evidence-text").fill("The courier left it with a neighbour, I think.")
        self.tid("submit-evidence").click()
        self.page.wait_for_url(re.compile(r"/evidence\?"))
        self.assertIn("could not be read", self.tid("flash").inner_text())
        self.assertEqual(self.tid("analysis-card").get_attribute("data-status"), "UNAVAILABLE")
        self.assertIn("Not analysed", self.tid("analysis-card").inner_text())

    def test_the_submit_button_shows_a_loading_state(self):
        self.go("/payments/DG-20481/evidence")
        self.page.evaluate("""() => { window.__submits = 0;
            document.querySelector('#evidence-form').addEventListener('submit', e => { window.__submits++; e.preventDefault(); }); }""")
        self.tid("evidence-text").fill("A note about the order.")
        self.tid("submit-evidence").click()
        self.page.wait_for_selector("#submit-evidence.loading", timeout=2000)
        self.assertEqual(self.tid("submit-evidence").get_attribute("aria-busy"), "true")

    def test_a_second_submit_while_busy_is_ignored(self):
        self.go("/payments/DG-20481/evidence")
        posts = []
        self.page.route("**/payments/DG-20481/evidence", lambda route: (posts.append(route.request.method), route.continue_()))
        self.tid("evidence-text").fill("A note about the order.")
        self.page.evaluate("() => { const b = document.querySelector('#submit-evidence'); b.click(); b.click(); b.click(); }")
        self.page.wait_for_url(re.compile(r"/evidence\?"))
        self.assertEqual(posts.count("POST"), 1)
        self.assertEqual(len(self.live.srv.app.svc.states["DG-20481"].artifacts), 2)         # fixture A11 plus exactly one new item

    def test_choosing_a_text_file_loads_it_into_the_form_for_checking(self):
        self.go("/payments/DG-20481/evidence")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "fedex.txt"
            f.write_text(SAMPLE["A01"]["text"])
            self.page.set_input_files("#fileinput", str(f))
            self.page.wait_for_function("document.querySelector('#evtext').value.length > 0")
            self.assertEqual(self.tid("evidence-text").input_value(), SAMPLE["A01"]["text"])
            self.assertIn("Loaded fedex.txt", self.tid("filename").inner_text())
            self.assertEqual(self.page.input_value("#evsource"), "Uploaded file: fedex.txt")
            self.tid("evidence-kind").select_option("CARRIER_EMAIL")
            self.tid("submit-evidence").click()
            self.page.wait_for_url(re.compile(r"/evidence\?"))
            self.assertIn("Evidence A01 added", self.tid("flash").inner_text())
            self.assertIn("Uploaded file: fedex.txt", self.page.content())

    def test_unsupported_files_are_refused_with_a_clear_message_and_nothing_is_added(self):
        self.go("/payments/DG-20481/evidence")
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "scan.pdf"
            f.write_bytes(b"%PDF-1.4 fake")
            self.page.set_input_files("#fileinput", str(f))
            self.page.wait_for_function("document.querySelector('#filename').textContent.length > 0")
            self.assertIn("can’t be read yet", self.tid("filename").inner_text())
            self.assertEqual(self.tid("evidence-text").input_value(), "")

    def test_the_dropzone_is_keyboard_accessible(self):
        """Enter and Space on the focused dropzone activate the file input. (Whether the OS chooser then opens is the browser's job; Playwright's
        headless file-chooser interception is itself intermittent, so this asserts the app's own behaviour: the input receives the click.)"""
        self.go("/payments/DG-20481/evidence")
        self.assertEqual(self.page.get_attribute("#dropzone", "role"), "button")
        self.assertEqual(self.page.get_attribute("#dropzone", "tabindex"), "0")
        self.page.evaluate("() => { window.__clicks = 0; document.querySelector('#fileinput').addEventListener('click', e => { window.__clicks++; e.preventDefault(); }); }")
        for key in ("Enter", " "):
            self.page.focus("#dropzone")
            self.page.keyboard.press(key)
        self.assertEqual(self.page.evaluate("window.__clicks"), 2)
        self.page.keyboard.press("Tab")                                                  # focus moves on; nothing else is triggered
        self.assertEqual(self.page.evaluate("window.__clicks"), 2)

    def test_clicking_a_fact_highlights_where_it_was_read_from(self):
        self.go("/payments/DG-20479/evidence/A01")
        self.page.locator("li.fact").filter(has_text="Tracking number").first.click()
        self.assertEqual(self.page.locator("mark.hl.active").count(), 1)
        self.assertIn("774912340001", self.page.locator("mark.hl.active").inner_text())

    # ---- unknown / empty / error states in the browser
    def test_empty_and_error_pages(self):
        self.go("/payments?q=nothing-matches-this")
        self.assertTrue(self.tid("empty-payments").is_visible())
        resp = self.page.goto(self.live.base + "/payments/NOPE")
        self.assertEqual(resp.status, 404)
        self.assertTrue(self.tid("error-page").is_visible())
        self.page.get_by_role("link", name="Back to Payments").click()
        self.page.wait_for_url(re.compile(r"/payments$"))

    def test_unknown_states_are_visible(self):
        self.go("/payments/DG-20463")
        self.assertIn("Route unknown", self.tid("paypal-info").inner_text())
        self.tid("tab-assessment").click()
        self.assertIn("Not known", self.tid("gates-card").inner_text())
        self.assertTrue(self.tid("no-requirements").is_visible())

    # ---- quality: no console noise, no CSP violations, responsive layout
    def test_no_console_errors_or_csp_violations_across_the_app(self):
        paths = ["/", "/payments", "/evidence"] + [f"/payments/{r}?tab={t}" for r in ("DG-20481", "DG-20472", "DG-20479") for t in ("evidence", "assessment", "whatif", "provenance")] \
            + ["/payments/DG-20481/evidence", "/payments/DG-20479/evidence/A01", "/payments/DG-20481?tab=whatif&option=add:A01"]
        for p in paths:
            self.go(p)
        self.assertEqual(self.problems, [])

    def test_layout_does_not_overflow_horizontally_at_common_widths(self):
        for w in (1672, 1280, 1024, 768, 390):
            self.page.set_viewport_size({"width": w, "height": 900})
            for p in ("/payments?selected=DG-20481", "/payments/DG-20481", "/payments/DG-20481?tab=assessment", "/payments/DG-20481/evidence", "/payments/DG-20479/evidence/A01"):
                self.go(p)
                over = self.page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
                self.assertLessEqual(over, 1, (w, p, over))

    def test_status_colours_follow_the_brand_system(self):
        self.go("/payments/DG-20479")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('.banner')).borderLeftColor"), "rgb(35, 132, 91)")      # Forest Green: demonstrated
        self.go("/payments/DG-20481")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('.banner')).borderLeftColor"), "rgb(183, 121, 31)")     # Muted Amber
        self.go("/payments/DG-20472?tab=evidence")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('.mi.tone-red .tico')).color"), "rgb(184, 64, 64)")       # Brick Red: conflict
        self.go("/payments/DG-20481")
        self.assertEqual(self.page.evaluate("getComputedStyle(document.querySelector('.btn-primary')).backgroundColor"), "rgb(8, 127, 140)")


if __name__ == "__main__":
    unittest.main()
