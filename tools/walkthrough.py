import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delivery_gate.engine import assess, counterfactual, default_registry
from delivery_gate.models import Changes
from delivery_gate import samples as S

REG = default_registry()


def show(report):
    print(f"CURRENT       : {report.current.protection_assessment.value}   digest {report.current.digest[:16]}")
    print(f"COUNTERFACTUAL: {report.counterfactual.protection_assessment.value}   digest {report.counterfactual.digest[:16]}")
    print("\n-- CURRENT STATE explanation --")
    for l in report.current.explanation: print("  " + l)
    print("\n-- COUNTERFACTUAL explanation --")
    for l in report.counterfactual.explanation: print("  " + l)
    print("\n-- WHAT CHANGED --")
    for l in report.explanation: print("  " + l)


def inr():
    print("=== INR counterfactual: carrier delivery record missing -> supplied ===\n")
    current = S.inr_case("INR-DEMO").with_changes(
        remove_evidence=["delivery_record", "tracking_number", "delivery_date", "delivered_status"])
    cf = Changes("merchant supplies the carrier delivery record", set_evidence=(
        S.ev("delivery_record", True, ref="fixture:carrier-FX1"), S.ev("tracking_number", "1Z999AA10123456784"),
        S.ev("delivery_date", "2026-10-20"), S.ev("delivered_status", "DELIVERED")))
    show(counterfactual(REG, current, cf))


def unauth():
    print("=== Unauthorized counterfactual: no shipment record -> carrier shipment record supplied ===")
    print("    (PayPal status is opaque: the overall result stays UNKNOWN even when every evidence field is demonstrated)\n")
    base = S.unauth_case("UNAUTH-DEMO", status="PARTIALLY_ELIGIBLE").with_changes(
        set_facts=[S.tf("paypal_notification_timestamp", "2026-10-19T10:00:00Z")],
        set_evidence=[S.merchant("shipment_timestamp", "2026-10-20T09:00:00Z")],
        remove_evidence=["shipment_record", "tracking_number", "shipment_date"])
    cf = Changes("merchant supplies the carrier shipment record", set_evidence=(
        S.ev("shipment_record", True), S.ev("tracking_number", "1Z999AA10123456785"), S.ev("shipment_date", "2026-10-18")))
    r = counterfactual(REG, base, cf)
    show(r)
    print("\ntiming_requirement  current:", r.current.timing_requirement, "| counterfactual:", r.counterfactual.timing_requirement)
    c = r.counterfactual.condition("unauth.condition.paypal_mark")
    print("policy condition  :", {k: c[k] for k in ("observation", "observed_value", "status_semantics", "POLICY_STATUS_MAPPING", "state")})
    print("RESULT_CHANGE     :", json.dumps(r.result_change["protection_assessment"]), json.dumps(r.result_change["evidence_fields_assessment"]))
    print("policy_status     :", r.counterfactual.policy_status, "|", r.counterfactual.display_notice)


def snad():
    print("=== SNAD assessment (return shipping documented, other costs unknown) ===\n")
    c = S.snad_case("SNAD-DEMO").with_changes(set_facts=[S.tf("return_shipping_cost", "25.00", S.SourceType.MERCHANT_INPUT,
                                                              "fixture:return-label", S.ProvStatus.MERCHANT_ASSERTED)])
    a = assess(REG, c)
    for l in a.explanation: print("  " + l)
    print("\nprotection_assessment:", a.protection_assessment.value)
    print(json.dumps(a.exposure, indent=2))


def registry():
    d = REG.dump()
    print(json.dumps(REG.summary_rows(), indent=1))
    print("\n--- resolved rule (us.sp.unauthorized, abridged) ---")
    r = d["us.sp.unauthorized"]
    for k in ("rule_id", "version", "status", "jurisdiction", "claim_category", "policy_effect", "eligibility_determination", "sources"):
        print(k, "=", json.dumps(r[k]))


if __name__ == "__main__":
    {"inr": inr, "unauth": unauth, "snad": snad, "registry": registry}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
