import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from delivery_ui import presenter as P
from delivery_ui.service import DeliveryGateService
from eval.corpus import ARTIFACTS

SAMPLE = {a["id"]: a for a in ARTIFACTS}
s = DeliveryGateService()
for ref in s.refs():
    an = s.analyze(ref)
    d = P.detail(s, an)
    fx = an.state.fixture
    print(f"\n### {ref} · {fx['order_ref']} · {d['summary']['amount']} · scenarios {fx['scenarios'] or '-'}  ({fx['scenario_title']})")
    print(f"- PayPal reports: payment {d['paypal']['payment_status']['label']}; dispute {d['summary']['dispute']}"
          + (f"; filed: {d['paypal']['dispute']['channel']}; disputed amount {d['paypal']['dispute']['disputed_amount']}" if d['paypal']['dispute'] else ""))
    print(f"- Evidence on file: " + (", ".join(f"{e['artifact_id']} ({e['kind_label']}, {e['authenticity']['label']})" for e in d['evidence']) or "none"))
    print(f"- Delivery Gate shows: **{d['overall']['label']}** (engine: {d['overall']['engine_value']}, human review: {d['overall']['needs_human_review']})")
    c = d["counts"]
    if d["requirements"]:
        print(f"- Requirements: {c['met']} demonstrated, {c['statement_only']} your statement only, {c['not_met']} not demonstrated, {c['conflict']} conflicting, {c['review']} need review")
    if d["contradictions"]:
        print("- Conflict: " + "; ".join(f"{x['label']}: " + " vs ".join(v['value'] for v in x['values']) for x in d['contradictions']))
    print("- First next step: " + (d["next_steps"][0]["text"] if d["next_steps"] else "-"))
r = s.what_if("DG-20481", "add:A01")
print(f"\n### Counterfactual on DG-20481: {r.option.label}\n- Current: {P.overall_for(r.report.current, None)['label']} -> hypothetical: {P.overall_for(r.report.counterfactual, None)['label']}")
print("- Changed requirements: " + ", ".join(P.what_if_view(s, s.analyze('DG-20481'), r)['changes'][i]['title'] for i in range(len(P.what_if_view(s, s.analyze('DG-20481'), r)['changes']))))
s.add_artifact("DG-20481", SAMPLE["A01"]["text"], "CARRIER_EMAIL")
print("- After actually adding A01 (unreviewed): " + P.overall(s.analyze('DG-20481'))['label'])
s.review_artifact("DG-20481", "A01", "attest_carrier", "Reviewer")
a = s.analyze("DG-20481")
print("- After a reviewer attests A01: " + P.overall(a)['label'] + f" | digest equals the hypothetical: {a.assessment.digest == r.report.counterfactual.digest}")
