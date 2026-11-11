"""Mutation checks for the Phase 4 UI. The property battery must pass on the real code and FAIL on each deliberately broken variant."""
import json
import os
import re
import unittest
from unittest import mock

from delivery_extraction import bridge
from delivery_gate.engine import UNREVIEWED_NOTICE, assess
from delivery_gate.models import Changes, Provenance, ProvStatus, SourceAuthenticity, SourceType
from delivery_extraction.review import ReviewAction
from delivery_ui import presenter as P
from delivery_ui import render as R
from delivery_ui import server as SRV
from delivery_ui import service as SVC
from tests.ui_helpers import *

SECRET = "sk-secret-mutation-0123456789"
ORIG_OVERALL_VIEW = dict(P.PROTECTION_VIEW)
ORIG_BRIDGE_PROV = bridge._provenance
ORIG = {"authenticity_view": P.authenticity_view, "exposure_view": P.exposure_view, "paypal_view": P._paypal_view, "shell": R.shell, "highlight": R.highlighted_text,
        "fields": SRV.App._fields, "Changes": SVC.Changes}


def violations():
    v = []

    def check(name, fn):
        try:
            msg = fn()
        except Exception as e:                                              # a crash on a safe input is itself a violation
            v.append(f"{name}: raised {type(e).__name__}: {e}")
            return
        if msg:
            v.append(f"{name}: {msg}")

    def engine_followed():
        s = fresh()
        for ref in ("DG-20481", "DG-20479", "DG-20468", "DG-20463", "DG-20472"):
            an = s.analyze(ref)
            d = P.detail(s, an)
            a = an.assessment
            if a.digest != independent_assessment(ref).digest:
                return f"{ref}: assessment differs from the engine driven directly"
            if d["overall"]["engine_value"] != a.protection_assessment.value:
                return f"{ref}: shown status is not the engine's"
            if a.protection_assessment.value != "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES" and d["overall"]["tone"] == "green":
                return f"{ref}: a non-demonstrated result is shown in the demonstrated colour"
            if a.protection_assessment.value != "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES" and "demonstrates the requirements" in d["overall"]["message"]:
                return f"{ref}: a non-demonstrated result carries the demonstrated message"

    def statement_not_corroborated():
        s = fresh()
        d = P.detail(s, s.analyze("DG-20475"))
        trk = next(r for r in d["requirements"] if r["key"] == "proof_of_delivery.tracking_number")
        if (trk["label"], trk["tone"]) != ("Your statement only", "amber"):
            return f"a merchant-asserted requirement was shown as {trk['label']!r}/{trk['tone']}"

    def notice_shown():
        app = App(fresh())
        html = get(app, "/payments/DG-20481?tab=assessment")[2]
        if "NOT an officially verified PayPal interpretation" not in html:
            return "the engine's display notice is missing from the assessment view"

    def no_forbidden_or_verified():
        app = App(fresh())
        for p in ("/payments/DG-20479", "/payments/DG-20479?tab=assessment", "/payments/DG-20479?tab=provenance", "/payments/DG-20481?tab=whatif&option=add:A01"):
            t = text_of(get(app, p)[2])
            if P.find_forbidden(t):
                return f"{p}: forbidden claim {P.find_forbidden(t)}"
            if re.search(r"(?<![A-Za-z])Verified(?![A-Za-z])|\bVERIFIED\b", t):
                return f"{p}: shows a Verified status"

    def api_strict():
        app = App(fresh())
        st, h, b = post(app, "/api/payments/DG-20481/artifacts", json_body={"text": "t", "kind": "OTHER", "protection_assessment": "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES"})
        if st != 400:
            return "a request was allowed to supply an assessment result"
        st, h, b = post(app, "/api/payments/DG-20481/artifacts/A11/review", json_body={"mode": "undo", "reviewer": "r", "source_authenticity": "VERIFIED"})
        if st != 400:
            return "a request was allowed to supply an authenticity level"

    def bridge_is_the_authority():
        s = fresh()
        s.add_artifact("DG-20481", SAMPLE["A04"]["text"], "MERCHANT_STATEMENT")
        try:
            s.review_artifact("DG-20481", "A04", "attest_carrier", "r")
        except SVC.ServiceError:
            return None
        return "a merchant statement was recorded as a carrier document"

    def highlight_exact():
        import html as H
        text = SAMPLE["A01"]["text"]
        facts = [{"fact_id": "f", "span_start": 10, "span_end": 40, "state": "unreviewed"}]
        out = R.highlighted_text(text, facts)
        if H.unescape(re.sub(r"</?mark[^>]*>", "", out)) != text:
            return "highlighting altered the original document"

    def whatif_faithful():
        s = fresh()
        hyp = s.what_if("DG-20481", "add:A01").report.counterfactual.digest
        s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
        s.review_artifact("DG-20481", "A01", "attest_carrier", "r")
        if s.analyze("DG-20481").assessment.digest != hyp:
            return "the what-if result is not what actually happens when the evidence is added and reviewed"

    def no_secrets():
        with mock.patch.dict(os.environ, {"ANTHROPIC_API_KEY": SECRET, "EXTRACTION_MODEL": "m"}):
            app = App(fresh())
            blob = get(app, "/payments")[2] + get(app, "/payments/DG-20481")[2] + get(app, "/api/payments/DG-20481")[2] + get(app, "/static/app.js")[2]
            if SECRET in blob:
                return "a secret reached the browser"

    def unknowns_stay_unknown():
        s = fresh()
        d = P.detail(s, s.analyze("DG-20463"))
        if d["paypal"]["dispute"]["route_known"] or d["overall"]["key"] != "UNKNOWN" or d["requirements"]:
            return "an unknown dispute route was presented as known or assessed"
        d = P.detail(s, s.analyze("DG-20455"))
        if d["exposure"]["disputed"]["text"] != "Unknown":
            return "a disputed amount was shown where none exists"
        for ref in REFS:
            if P.detail(s, s.analyze(ref))["exposure"]["potential"]["text"] != "Unknown":
                return f"{ref}: potential seller exposure was presented as known"

    for n, f in (("engine_followed", engine_followed), ("statement_not_corroborated", statement_not_corroborated), ("notice_shown", notice_shown),
                 ("no_forbidden_or_verified", no_forbidden_or_verified), ("api_strict", api_strict), ("bridge_is_the_authority", bridge_is_the_authority),
                 ("highlight_exact", highlight_exact), ("whatif_faithful", whatif_faithful), ("no_secrets", no_secrets), ("unknowns_stay_unknown", unknowns_stay_unknown)):
        check(n, f)
    return v


# ---- broken variants ------------------------------------------------------------------------------------------------------------------------------
def _ui_computes_its_own_result(registry, case):                                    # the UI layer decides the outcome itself
    real = assess(registry, case)
    real.protection_assessment = type(real.protection_assessment)("REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES")
    return real


def _unknown_shown_as_demonstrated():
    return mock.patch.dict(P.PROTECTION_VIEW, {"UNKNOWN": {**ORIG_OVERALL_VIEW["REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES"]}})


def _bridge_skips_carrier_checks(f, decision, artifact, attested):                  # every carrier safeguard in the bridge is bypassed
    if decision is not None and decision.action == ReviewAction.APPROVE_AS_CARRIER_DOCUMENT:
        return Provenance(SourceType.CARRIER_DOCUMENT, f.fact_id, ProvStatus.HUMAN_CONFIRMED, None, None, f.source_span, SourceAuthenticity.REVIEWED)
    return ORIG_BRIDGE_PROV(f, decision, artifact, attested)


def _no_notice(d):
    return ""


def _shell_leaks(title, active, body, q="", flash=None):
    return ORIG["shell"](title, active, body + f"<!-- {os.environ.get('ANTHROPIC_API_KEY', '')} -->", q, flash)


def _lax_fields(self, body, ctype, allowed):
    return ORIG["fields"](self, body, ctype, None)


def _highlight_drops_text(text, facts):
    return ORIG["highlight"](text[1:], facts)


def _changes_without_evidence(label, set_evidence=(), remove_evidence=(), **kw):
    return ORIG["Changes"](label)                                                   # the hypothetical evidence is silently dropped


def _verified_label(row, reviewer=None, at=None):
    out = ORIG["authenticity_view"](row, reviewer, at)
    return {**out, "label": "Verified"} if out["key"] == "REVIEWED" else out


def _potential_from_original(an):
    v = ORIG["exposure_view"](an)
    v["potential"] = {**v["potential"], "text": v["original"]["text"], "state": "OBSERVED"}
    return v


def _route_always_known(an):
    v = ORIG["paypal_view"](an)
    if v["dispute"]:
        v["dispute"]["route_known"] = True
    return v


MUTANTS = {
    "U01 the UI layer computes its own protection result": lambda: mock.patch.object(SVC.DeliveryGateService, "__init__", _patched_init(_ui_computes_its_own_result)),
    "U02 an unknown result is presented as demonstrated": _unknown_shown_as_demonstrated,
    "U03 a merchant statement is presented as a demonstrated requirement": lambda: mock.patch.object(P, "STATEMENT_ONLY_VIEW", dict(P.CHECK_VIEW["DEMONSTRATED"])),
    "U04 the engine's display notice is dropped": lambda: mock.patch.object(R, "notice_bar", _no_notice),
    "U05 the API accepts any field (so a result can be supplied)": lambda: mock.patch.object(SRV.App, "_fields", _lax_fields),
    "U06 every carrier safeguard in the bridge is bypassed underneath the UI": lambda: mock.patch.object(bridge, "_provenance", _bridge_skips_carrier_checks),
    "U07 highlighting alters the original document": lambda: mock.patch.object(R, "highlighted_text", _highlight_drops_text),
    "U08 the what-if drops the hypothetical evidence": lambda: mock.patch.object(SVC, "Changes", _changes_without_evidence),
    "U09 a secret is written into pages": lambda: mock.patch.object(R, "shell", _shell_leaks),
    "U10 reviewed evidence is labelled Verified": lambda: mock.patch.object(P, "authenticity_view", _verified_label),
    "U11 potential seller exposure is shown as the original amount": lambda: mock.patch.object(P, "exposure_view", _potential_from_original),
    "U12 an unknown route is presented as known": lambda: mock.patch.object(P, "_paypal_view", _route_always_known),
}


def _patched_init(assess_fn):
    real_init = SVC.DeliveryGateService.__init__

    def init(self, *a, **kw):
        kw["assess_fn"] = assess_fn
        real_init(self, *a, **kw)
    return init


class DefenceInDepth(unittest.TestCase):
    def test_a_merchant_statement_is_protected_by_two_independent_barriers(self):
        """Weakening only the artifact-kind rule is NOT enough to let a merchant statement become carrier evidence: the content-attribution rule still refuses it.
        (This is why the single-rule variant is not used as a mutant: another layer catches it.)"""
        with mock.patch.object(bridge, "CARRIER_KINDS", bridge.CARRIER_KINDS | {"MERCHANT_STATEMENT"}):
            s = fresh()
            s.add_artifact("DG-20481", SAMPLE["A04"]["text"], "MERCHANT_STATEMENT")
            with self.assertRaises(SVC.ServiceError) as c:
                s.review_artifact("DG-20481", "A04", "attest_carrier", "r")
            self.assertEqual(c.exception.code, "carrier_review_refused")


class Battery(unittest.TestCase):
    def test_the_real_ui_passes_every_property(self):
        self.assertEqual(violations(), [])

    def test_every_mutant_is_caught(self):
        survivors = []
        for label, ctx in MUTANTS.items():
            with ctx():
                if not violations():
                    survivors.append(label)
        self.assertEqual(survivors, [])

    def test_the_right_property_catches_each_mutant(self):
        expect = {"U01": "engine_followed", "U02": "engine_followed", "U03": "statement_not_corroborated", "U04": "notice_shown", "U05": "api_strict",
                  "U06": "bridge_is_the_authority", "U07": "highlight_exact", "U08": "whatif_faithful", "U09": "no_secrets", "U10": "no_forbidden_or_verified",
                  "U11": "unknowns_stay_unknown", "U12": "unknowns_stay_unknown"}
        for label, ctx in MUTANTS.items():
            with ctx():
                found = {x.split(":")[0] for x in violations()}
            self.assertIn(expect[label[:3]], found, (label, found))


if __name__ == "__main__":
    unittest.main()
