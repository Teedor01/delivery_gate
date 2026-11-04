import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delivery_gate.engine import assess, default_registry
from paypal_adapter import adapter, api_semantics, disputes, exposure, inventory, sources
from paypal_adapter.handoff import to_case
from tests.paypal_helpers import FIXTURES, full_case

DFIX = FIXTURES / "disputes"


def load(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())["response"]


def dload(name):
    return json.loads((DFIX / f"{name}.json").read_text())["response"]


def chain(name="01_normal", fact="paypal_seller_protection_status"):
    order = adapter.observe_order(load(name), origin="FIXTURE")
    cap = order.select_capture()
    h = to_case(cap)
    f = h.case.fact(fact)
    obs = next(o for o in cap.observations if o.observation_id == f.provenance.source_ref)
    a = assess(default_registry(), full_case(h, "UNAUTHORIZED_TRANSACTION"))
    return {"1_paypal_response_field": obs.field_path, "1_raw_response_sha256": obs.response_sha256,
            "2_observation": obs.to_dict(),
            "2b_api_semantics (what PayPal documents; NOT a policy mapping)": api_semantics.lookup(api_semantics.SPS, obs.raw_value).to_dict() if obs.api_semantics_ref else None,
            "3_delivery_gate_fact": {"name": f.name, "value": f.value, "provenance": f.provenance.to_dict()},
            "4_engine_consumer": {"observed_input": a.observed_inputs[fact],
                                  "policy_condition": next(c for c in a.policy_conditions if c["condition_id"] == "unauth.condition.paypal_mark"),
                                  "protection_assessment": a.protection_assessment.value, "reason_codes": list(a.reason_codes)}}


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "chain"
    cap = lambda: adapter.observe_order(load("01_normal"), origin="FIXTURE").select_capture()
    if mode == "chain":
        print(json.dumps(chain(), indent=2))
    elif mode == "handoff":
        d = disputes.observe_dispute(dload("d01_inr_internal_partial"), origin="FIXTURE")
        h = to_case(adapter.observe_order(load("07_with_address"), origin="FIXTURE").select_capture(), dispute=d).to_dict()
        h.pop("case")
        print(json.dumps(h, indent=2))
    elif mode == "inventory":
        print(json.dumps({"fields": inventory.inventory_rows(), "engine_fact_chains": inventory.engine_fact_chains()}, indent=2))
    elif mode == "semantics":
        print(json.dumps({"rows": [r.to_dict() for r in api_semantics.all_rows()], "cross_surface_notes": list(api_semantics.CROSS_SURFACE_NOTES)}, indent=2))
    elif mode == "sources":
        print(json.dumps({"source_roles": sources.source_roles(), "normalization_tables": disputes.normalization_tables()}, indent=2))
    elif mode == "exposure":
        d = disputes.observe_dispute(dload("d01_inr_internal_partial"), origin="FIXTURE")
        print(json.dumps({"no_dispute": exposure.build_exposure(cap()).to_dict(),
                          "with_linked_partial_dispute": exposure.build_exposure(cap(), d).to_dict()}, indent=2))
    elif mode == "disputes":
        for p in sorted(DFIX.glob("*.json")):
            try:
                d = disputes.observe_dispute(json.loads(p.read_text())["response"], origin="FIXTURE")
                h = to_case(cap(), dispute=d)
                print(f"{p.stem:34s} claim_category={getattr(h.case.fact('claim_category'), 'value', None)!s:26s} route={getattr(h.case.fact('route'), 'value', None)!s:15s} "
                      f"linked={h.linkage['linked']} anomalies={len(d.anomalies)}")
            except adapter.MalformedPayPalResponse as e:
                print(f"{p.stem:34s} REFUSED: {e}")
    elif mode == "fixtures":
        for p in sorted(FIXTURES.glob("*.json")):
            w = json.loads(p.read_text())
            try:
                c = adapter.observe_order(w["response"], origin="FIXTURE").select_capture()
                h = to_case(c)
                print(f"{p.stem:28s} handed={[x['fact'] for x in h.handed_off]} anomalies={len(h.anomalies)} absent={len(h.absent)} withheld={len(h.withheld)}")
            except adapter.MalformedPayPalResponse as e:
                print(f"{p.stem:28s} REFUSED: {e}")
