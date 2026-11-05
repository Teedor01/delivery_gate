import copy, hashlib, itertools, json, unittest
from dataclasses import replace
from unittest import mock
from paypal_adapter import adapter, handoff as hmod
from paypal_adapter.inventory import CAPTURE_DEF, Semantics
from tests.paypal_helpers import *

EXPECTED_FACTS = {"paypal_seller_protection_status", "currency"}     
CAP0 = "purchase_units[0].payments.captures[0]"
ORIG_OBSERVE_ORDER = adapter.observe_order
ORIG_EXTRACT_SP = adapter._extract_seller_protection
ORIG_EXTRACT_MONEY = adapter._extract_money
ORIG_MAKE_OBS = adapter._make_obs
ORIG_PREPARE = adapter._prepare
ORIG_TO_CASE = hmod.to_case


def _canon_sha(resp):                                                                      
    return hashlib.sha256(json.dumps(resp, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def violations():
    v = []

    def check(name, fn):
        try:
            msg = fn()
        except Exception as e:                                                            
            v.append(f"{name}: raised {type(e).__name__}: {e}")
            return
        if msg:
            v.append(f"{name}: {msg}")

    def opaque_token():
        for n in ("02_sp_eligible", "03_sp_partially_eligible", "04_sp_not_eligible", "10_unexpected_enum"):
            r = response(n); raw = at_path(r, f"{CAP0}.seller_protection.status")
            got = handoff(r).case.fact("paypal_seller_protection_status")
            if got is None or got.value != raw:
                return f"{n}: token {raw!r} was not passed through verbatim (got {None if got is None else got.value!r})"
        r = with_status(response("01_normal"), "eligible")                                 
        got = handoff(r).case.fact("paypal_seller_protection_status")
        if got is None or got.value != "eligible":
            return "token was altered"

    def no_defaults():
        c = observe(response("05_sp_missing")).select_capture()
        if c.find("seller_protection.status") is not None or handoff(response("05_sp_missing")).case.fact("paypal_seller_protection_status"):
            return "a missing seller_protection received a value"
        r = response("01_normal"); del r["purchase_units"][0]["payments"]["captures"][0]["amount"]
        got = {f.name for f in handoff(r).case.transaction_facts}
        if got != {"paypal_seller_protection_status"}:
            return f"a missing amount produced facts {sorted(got)}"
        if "transaction_amount" in {f.name for f in handoff(response("01_normal")).case.transaction_facts}:
            return "the capture amount was handed to the engine"
        h = handoff(response("01_normal"))
        if any(f.provenance.timestamp is not None for f in h.case.transaction_facts) or \
                any(o.observed_at is not None for o in observe(response("01_normal")).select_capture().observations):
            return "an observation time was invented"

    def undocumented_flagged():
        c = observe(response("10_unexpected_enum")).select_capture()
        cats, st = c.find("seller_protection.dispute_categories"), c.find("seller_protection.status")
        if cats is None or cats.raw_value != ["UNAUTHORIZED_TRANSACTION", "NEW_CATEGORY"] or cats.normalized_value is not None:
            return "undocumented category token was dropped or normalised"
        if st is None or st.normalized_value != "ELIGIBLE_V2" or st.enum_state != "UNDOCUMENTED_TOKEN":
            return "undocumented status token was not kept verbatim and flagged"
        if sum(a.kind == "UNDOCUMENTED_ENUM_VALUE" for a in c.anomalies) != 4:
            return "undocumented tokens were not all reported"

    def malformed_raises():
        for n in ("09_malformed",):
            try:
                adapter.observe_order(response(n), origin="FIXTURE")
            except adapter.MalformedPayPalResponse:
                continue
            return f"{n} did not fail"
        try:
            adapter.observe_order({"status": "COMPLETED"}, origin="FIXTURE")
        except adapter.MalformedPayPalResponse:
            return None
        return "an order without an id did not fail"

    def provenance_intact():
        r = response("01_normal"); sha = _canon_sha(r)
        cap = observe(r).select_capture()
        ids = {o.observation_id for o in cap.observations}
        for o in cap.observations:
            if not (o.doc_ref.startswith("https://") and o.field_path and o.local_path and o.observation_id and o.source == "PAYPAL_API"):
                return f"observation {o.observation_id!r} lost provenance fields"
            if o.response_sha256 != sha:
                return "response hash missing or wrong"
        for f in hmod.to_case(cap).case.transaction_facts:
            if f.provenance.source_ref not in ids or f.provenance.source_type.value != "PAYPAL_API":
                return f"fact {f.name} does not resolve to an observation"

    def deterministic():
        for n in ("01_normal", "10_unexpected_enum"):
            if observe(response(n)).to_dict() != observe(response(n)).to_dict():
                return f"{n}: two runs differ"

    def handoff_closed():
        for n in ("01_normal", "07_with_address", "06_unknown_funding_source", "12_partially_refunded"):
            names = {f.name for f in handoff(response(n)).case.transaction_facts}
            if names - EXPECTED_FACTS:
                return f"{n}: facts outside the closed plan reached the engine: {sorted(names - EXPECTED_FACTS)}"

    def token_swap_invariance():
        base = policy_view(assessment(with_status(response("01_normal"), "ELIGIBLE"), "UNAUTHORIZED_TRANSACTION"), "ELIGIBLE")
        for t in ("PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE", "ELIGIBLE_V2"):
            a = assessment(with_status(response("01_normal"), t), "UNAUTHORIZED_TRANSACTION")
            if policy_view(a, t) != base:
                return f"changing only the token to {t} changed the policy assessment"

    def categories_not_consumed():
        r1, r2 = response("01_normal"), response("01_normal")
        r2["purchase_units"][0]["payments"]["captures"][0]["seller_protection"]["dispute_categories"] = ["ITEM_NOT_RECEIVED"]
        if handoff(r1).case.snapshot() != handoff(r2).case.snapshot():
            return "dispute_categories influenced the case"

    for name, fn in (("opaque_token", opaque_token), ("no_defaults", no_defaults), ("undocumented_flagged", undocumented_flagged),
                     ("malformed_raises", malformed_raises), ("provenance_intact", provenance_intact), ("deterministic", deterministic),
                     ("handoff_closed", handoff_closed), ("token_swap_invariance", token_swap_invariance),
                     ("categories_not_consumed", categories_not_consumed)):
        check(name, fn)
    return v


# ---- the broken variants ---------------------------------------------------------------------------------------------------
def _m_status_mapped(raw):                         
    if not isinstance(raw, str) or not raw:
        return None, None, ("TYPE", "x")
    return {"ELIGIBLE": "SATISFIED", "NOT_ELIGIBLE": "UNSATISFIED"}.get(raw, raw), "DOCUMENTED_TOKEN", None


def _m_status_upper(raw):                          
    if not isinstance(raw, str) or not raw:
        return None, None, ("TYPE", "x")
    return raw.upper(), "DOCUMENTED_TOKEN", None


def _m_status_drop_unknown(raw):                  
    if not isinstance(raw, str) or raw not in ("ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE"):
        return None, None, ("UNDOCUMENTED_ENUM_VALUE", "dropped")
    return raw, "DOCUMENTED_TOKEN", None


def _m_categories_filtered(raw):                  
    return sorted(x for x in raw if x in ("ITEM_NOT_RECEIVED", "UNAUTHORIZED_TRANSACTION")), None


def _m_default_sp(ctx, cap):                       
    if "seller_protection" not in cap:
        ctx.obs.append(ORIG_MAKE_OBS(ctx, "seller_protection.status", None, "NOT_ELIGIBLE", "NONE", Semantics.OBSERVED_AND_DOCUMENTED, CAPTURE_DEF, "DOCUMENTED_TOKEN"))
        return
    return ORIG_EXTRACT_SP(ctx, cap)


def _m_default_amount(ctx, parent, local, doc_ref, semantics):     
    return ORIG_EXTRACT_MONEY(ctx, parent if parent is not None else {"value": "0.01", "currency_code": "USD"}, local, doc_ref, semantics)


def _m_strip_provenance(ctx, local, raw, normalized, normalization, semantics, doc_ref, enum_state=None, full_path=None, api_semantics_ref=None):
    return replace(ORIG_MAKE_OBS(ctx, local, raw, normalized, normalization, semantics, doc_ref, enum_state, full_path, api_semantics_ref), doc_ref="", field_path="")


def _m_no_hash(response_, origin, observed_at):
    ORIG_PREPARE(response_, origin, observed_at)
    return ""


_counter = itertools.count()


def _m_nondeterministic(response_, origin, observed_at):
    return ORIG_PREPARE(response_, origin, observed_at) + str(next(_counter))


def _m_lenient_observe(response_, *, origin, observed_at=None):    
    try:
        return ORIG_OBSERVE_ORDER(response_, origin=origin, observed_at=observed_at)
    except adapter.MalformedPayPalResponse:
        return adapter.OrderObservation("UNKNOWN", origin, observed_at, "", ())


def _m_clock(response_, *, origin, observed_at=None):             
    return ORIG_OBSERVE_ORDER(response_, origin=origin, observed_at=observed_at or "2026-01-01T00:00:00Z")


def _m_to_case_default_status(cap, *, case_id=None):               
    res = ORIG_TO_CASE(cap, case_id=case_id)
    if res.case.fact("paypal_seller_protection_status") is None:
        f = TransactionFact("paypal_seller_protection_status", "NOT_ELIGIBLE", Provenance(SourceType.PAYPAL_API, "default", ProvStatus.SYSTEM_RECORD))
        return replace(res, case=Case(res.case.case_id, res.case.transaction_facts + (f,)))
    return res


MUTATIONS = {
    "M01 adapter maps ELIGIBLE/NOT_ELIGIBLE to policy-like values": ("paypal_adapter.adapter", "_norm_status_token", _m_status_mapped),
    "M02 adapter upper-cases the opaque token": ("paypal_adapter.adapter", "_norm_status_token", _m_status_upper),
    "M03 undocumented status token silently dropped": ("paypal_adapter.adapter", "_norm_status_token", _m_status_drop_unknown),
    "M04 undocumented dispute category filtered without a trace": ("paypal_adapter.adapter", "_norm_categories", _m_categories_filtered),
    "M05 missing seller_protection defaulted to NOT_ELIGIBLE": ("paypal_adapter.adapter", "_extract_seller_protection", _m_default_sp),
    "M06 missing amount defaulted to 0.01 USD": ("paypal_adapter.adapter", "_extract_money", _m_default_amount),
    "M07 provenance (doc_ref, field_path) stripped": ("paypal_adapter.adapter", "_make_obs", _m_strip_provenance),
    "M08 response hash dropped": ("paypal_adapter.adapter", "_prepare", _m_no_hash),
    "M09 non-deterministic output": ("paypal_adapter.adapter", "_prepare", _m_nondeterministic),
    "M10 malformed responses swallowed": ("paypal_adapter.adapter", "observe_order", _m_lenient_observe),
    "M11 observation time invented": ("paypal_adapter.adapter", "observe_order", _m_clock),
    "M12 handoff defaults a missing status": ("paypal_adapter.handoff", "to_case", _m_to_case_default_status),
    "M13 handoff plan hands over the shipping address": ("paypal_adapter.handoff", "HANDOFF_PLAN",
                                                          hmod.HANDOFF_PLAN + (("transaction_details_address", "unit.shipping.address"),)),
    "M14 handoff plan hands over the PayPal fee (name-based inference)": ("paypal_adapter.handoff", "HANDOFF_PLAN",
                                                                         hmod.HANDOFF_PLAN + (("paypal_fee_amount", "seller_receivable_breakdown.paypal_fee.value"),)),
    "M15 handoff plan turns the status token into a PROTECTED fact": ("paypal_adapter.handoff", "HANDOFF_PLAN",
                                                                      (("protected", "seller_protection.status"),) + hmod.HANDOFF_PLAN[1:]),
    "M16 handoff plan hands the capture amount to the engine": ("paypal_adapter.handoff", "HANDOFF_PLAN",
                                                                  hmod.HANDOFF_PLAN + (("transaction_amount", "amount.value"),)),
}


class Battery(unittest.TestCase):
    def test_the_real_adapter_passes_every_property(self):
        self.assertEqual(violations(), [])

    def test_every_mutation_is_caught(self):
        survivors = {}
        for label, (mod, attr, bad) in MUTATIONS.items():
            target = adapter if mod.endswith(".adapter") else hmod
            with mock.patch.object(target, attr, bad):
                found = violations()
            if not found:
                survivors[label] = "NOT CAUGHT"
        self.assertEqual(survivors, {})

    def test_each_mutation_is_caught_by_a_named_property(self):
        for label, (mod, attr, bad) in MUTATIONS.items():
            target = adapter if mod.endswith(".adapter") else hmod
            with mock.patch.object(target, attr, bad):
                found = violations()
            self.assertTrue(found, label)

    def test_the_protected_mutation_is_stopped_by_the_model_itself(self):
        mod, attr, bad = MUTATIONS["M15 handoff plan turns the status token into a PROTECTED fact"]
        with mock.patch.object(hmod, attr, bad):
            with self.assertRaises(ValueError):
                handoff(response("01_normal"))                                         


if __name__ == "__main__":
    unittest.main()
