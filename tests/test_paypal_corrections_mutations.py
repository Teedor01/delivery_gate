import copy, json, types, unittest
from dataclasses import replace
from unittest import mock
from paypal_adapter import api_semantics as sem, disputes, exposure, handoff as hmod, webhooks
from paypal_adapter.handoff import to_case
from tests.paypal_helpers import *
from tests.test_paypal_corrections import cap01, dobs, dresp, dispute_with

LITERAL_ALLOWED = {"paypal_seller_protection_status", "currency", "claim_category", "route", "merchant_account_country"}
ORIG = {"route_for": disputes._route_for, "make_obs": disputes._make_obs, "disputed": exposure._disputed, "original": exposure._original,
        "jur": hmod.merchant_jurisdiction_fact, "lookup": sem.lookup}


class Ok:
    def verify(self, h, e, w):
        return "SUCCESS"


class Bad:
    def verify(self, h, e, w):
        return "FAILURE"


HEADERS = {h: "x" for h in webhooks.REQUIRED_HEADERS}
EVENT = {"id": "WH-1", "event_type": "CUSTOMER.DISPUTE.CREATED", "resource": {"dispute_id": "PP-D-FX0001", "dispute_amount": {"value": "300.00"}}}


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

    def semantics_not_policy():
        for t in ("ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE"):
            r = sem.lookup(sem.SPS, t)
            if r is None or r.legal_policy_equivalence != "NOT_ESTABLISHED":
                return f"{t}: a documented API meaning was treated as legal-policy equivalence"
        if any(r.legal_policy_equivalence != "NOT_ESTABLISHED" for r in sem.all_rows()):
            return "a semantics row asserts equivalence"

    def exposure_separation():
        no = exposure.build_exposure(cap01()).to_dict()
        if no["disputed_amount"]["state"] != "UNKNOWN" or no["disputed_amount"]["value"] is not None:
            return "disputed amount was assumed when no dispute exists"
        yes = exposure.build_exposure(cap01(), dobs("d01_inr_internal_partial")).to_dict()
        if yes["disputed_amount"]["value"] != "300.00" or yes["original_transaction_value"]["value"] != "1200.00":
            return "original and disputed amounts were conflated"
        for x in (no, yes):
            if x["potential_seller_exposure"]["state"] != "UNKNOWN" or x["potential_seller_exposure"]["value"] is not None:
                return "potential seller exposure was derived"
            text = json.dumps(x).lower()
            if any(w in text for w in ("floor", "minimum", "lower bound", "lower_bound")):
                return "the capture amount was described as a floor / minimum"

    def route_channel_only():
        for reason in ("UNAUTHORISED", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED"):
            for ch, want in (("INTERNAL", "PAYPAL_DISPUTE"), ("EXTERNAL", None), ("ALERT", None), (None, None)):
                f = to_case(cap01(), dispute=dispute_with(reason, ch, "CHARGEBACK")).case.fact("route")
                if (f.value if f else None) != want:
                    return f"route for reason={reason} channel={ch} was {f.value if f else None}, expected {want}"

    def reason_rules():
        d = dobs("d01_inr_internal_partial")
        if d.find("reason").raw_value != "MERCHANDISE_OR_SERVICE_NOT_RECEIVED":
            return "the raw reason was not preserved"
        if to_case(cap01(), dispute=dobs("d06_not_as_described")).case.fact("claim_category") is not None:
            return "an unestablished reason was normalised"
        f = to_case(cap01(), dispute=dobs("d02_unauthorised_internal")).case.fact("claim_category")
        if f is None or f.value != "UNAUTHORIZED_TRANSACTION":
            return "an established reason was not normalised"

    def linkage_required():
        h = to_case(cap01(), dispute=dobs("d11_other_transaction"))
        if h.case.fact("claim_category") is not None or h.case.fact("route") is not None:
            return "facts from an unlinked dispute reached the engine"
        if exposure.build_exposure(cap01(), dobs("d11_other_transaction")).disputed_amount["state"] != "UNKNOWN":
            return "an unlinked dispute's amount was presented"

    def closed_plan():
        for d in (None, dobs("d01_inr_internal_partial")):
            names = {f.name for f in to_case(cap01(), dispute=d).case.transaction_facts}
            if names - LITERAL_ALLOWED:
                return f"facts outside the closed plan reached the engine: {sorted(names - LITERAL_ALLOWED)}"

    def webhook_gate():
        if webhooks.WebhookReceiver(Bad(), "W").receive(HEADERS, EVENT).accepted:
            return "an unverified notification was accepted"
        d = webhooks.WebhookReceiver(Ok(), "W").receive(HEADERS, EVENT)
        if not d.accepted or set(vars(d.read_request)) != {"dispute_id", "event_id", "event_type", "purpose"}:
            return "a verified notification carried more than a read request"

    def jurisdiction():
        if hmod.merchant_jurisdiction_fact("", source_ref="x") is not None or hmod.merchant_jurisdiction_fact(None, source_ref="x") is not None:
            return "an unknown jurisdiction was defaulted"
        f = hmod.merchant_jurisdiction_fact("US", source_ref="x")
        if (f.provenance.source_type.value, f.provenance.status.value) != ("MERCHANT_INPUT", "MERCHANT_ASSERTED"):
            return "jurisdiction was not marked merchant-asserted"

    for n, f in (("semantics_not_policy", semantics_not_policy), ("exposure_separation", exposure_separation), ("route_channel_only", route_channel_only),
                 ("reason_rules", reason_rules), ("linkage_required", linkage_required), ("closed_plan", closed_plan), ("webhook_gate", webhook_gate),
                 ("jurisdiction", jurisdiction)):
        check(n, f)
    return v


def _route_from_reason(channel, reason):
    if reason == "UNAUTHORISED":
        return "CARD_ISSUER_CHARGEBACK", "CHANNEL_ROUTE_TABLE_V1:ESTABLISHED"
    return ORIG["route_for"](channel, reason)


def _raw_overwritten(ctx, local, raw, normalized, normalization, semantics, doc_ref, enum_state=None, full_path=None, api_semantics_ref=None):
    return ORIG["make_obs"](ctx, local, normalized if (local == "reason" and normalized) else raw, normalized, normalization, semantics, doc_ref, enum_state, full_path, api_semantics_ref)


def _disputed_assumed(cap, dispute, flags, linkage):
    return ORIG["disputed"](cap, dispute, flags, linkage) if dispute is not None else dict(ORIG["original"](cap))


def _potential_derived(original, disputed):
    return exposure._component(disputed["state"], disputed["value"], disputed["currency"], None, None)


def _original_floor(cap):
    return {**ORIG["original"](cap), "note": "A conservative exposure floor."}


def _leaky_request(dispute_id, event_id, event_type):
    return types.SimpleNamespace(dispute_id=dispute_id, event_id=event_id, event_type=event_type, purpose="FRESH_DISPUTES_API_READ", payload=EVENT["resource"])


def _jurisdiction_default(country, *, source_ref):
    return ORIG["jur"](country or "US", source_ref=source_ref)


def _lookup_equivalent(field_id, value):
    r = ORIG["lookup"](field_id, value)
    return replace(r, legal_policy_equivalence="ESTABLISHED") if r else r


NR = disputes.Normalization
MUTANTS = {
    "C01 documented API meaning promoted to legal-policy equivalence": lambda: mock.patch.object(sem, "lookup", _lookup_equivalent),
    "C02 route inferred from the claim reason": lambda: mock.patch.object(disputes, "_route_for", _route_from_reason),
    "C03 EXTERNAL channel mapped to a card-issuer chargeback": lambda: mock.patch.dict(
        disputes.CHANNEL_ROUTE_TABLE_V1, {"EXTERNAL": NR("CARD_ISSUER_CHARGEBACK", True, (), "")}),
    "C04 not-as-described normalised without a primary description": lambda: mock.patch.dict(
        disputes.CLAIM_REASON_TABLE_V1, {"MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": NR("SIGNIFICANTLY_NOT_AS_DESCRIBED", True, (), "")}),
    "C05 raw reason overwritten by its normalised value": lambda: mock.patch.object(disputes, "_make_obs", _raw_overwritten),
    "C06 dispute linkage skipped": lambda: mock.patch.object(disputes, "is_linked", lambda capture_id, dispute: True),
    "C07 potential seller exposure derived": lambda: mock.patch.object(exposure, "_potential", _potential_derived),
    "C08 disputed amount assumed equal to the original value": lambda: mock.patch.object(exposure, "_disputed", _disputed_assumed),
    "C09 capture amount described as an exposure floor": lambda: mock.patch.object(exposure, "_original", _original_floor),
    "C10 unverified webhook accepted": lambda: mock.patch.object(webhooks.WebhookReceiver, "_verified", lambda self, h, e: True),
    "C11 webhook payload copied into the read request": lambda: mock.patch.object(webhooks.WebhookReceiver, "_make_request", staticmethod(_leaky_request)),
    "C12 unknown jurisdiction defaulted to US": lambda: mock.patch.object(hmod, "merchant_jurisdiction_fact", _jurisdiction_default),
    "C13 dispute amount handed to the engine": lambda: mock.patch.object(hmod, "DISPUTE_HANDOFF_PLAN", hmod.DISPUTE_HANDOFF_PLAN + (("transaction_amount", "dispute_amount.value"),)),
}


class CorrectionsBattery(unittest.TestCase):
    def test_the_real_code_passes_every_property(self):
        self.assertEqual(violations(), [])

    def test_every_mutant_is_caught(self):
        survivors = [label for label, ctx in MUTANTS.items() if not self._run(ctx)]
        self.assertEqual(survivors, [])

    @staticmethod
    def _run(ctx):
        with ctx():
            return violations()

    def test_the_right_property_catches_each_mutant(self):
        expect = {"C01": "semantics_not_policy", "C02": "route_channel_only", "C03": "route_channel_only", "C04": "reason_rules", "C05": "reason_rules",
                  "C06": "linkage_required", "C07": "exposure_separation", "C08": "exposure_separation", "C09": "exposure_separation",
                  "C10": "webhook_gate", "C11": "webhook_gate", "C12": "jurisdiction", "C13": "closed_plan"}
        for label, ctx in MUTANTS.items():
            found = {x.split(":")[0] for x in self._run(ctx)}
            self.assertIn(expect[label[:3]], found, (label, found))


if __name__ == "__main__":
    unittest.main()
