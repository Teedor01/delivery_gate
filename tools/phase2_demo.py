import json, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from delivery_gate.engine import default_registry
from delivery_extraction.bridge import assess_extraction, trace_fact
from delivery_extraction.extractor import RecordedExtractor
from delivery_extraction.pipeline import run_extraction
from delivery_extraction.review import Attestation, ReviewAction, ReviewDecision
from delivery_extraction.schema import Artifact
from eval.corpus import ARTIFACTS, CASE_GROUPS
from tests.ext_helpers import base_case

REG = default_registry()
ART = {a["id"]: Artifact(a["id"], a["text"], a["kind"]) for a in ARTIFACTS}
RUN = run_extraction(list(ART.values()), RecordedExtractor(ROOT / "eval" / "recorded_outputs"), CASE_GROUPS)


def facts(*ids):
    return [f for f in RUN.candidates if f.artifact_id in ids]


def line(*cols, w=(16, 30, 24, 7)):
    print("  " + " | ".join(str(c) for c in cols))


def example():
    aid = "A07"
    print("=== 1. MESSY ARTIFACT (A07, declared kind MERCHANT_STATEMENT) ===\n" + ART[aid].text)
    print("\n=== 2. RAW LLM OUTPUT (recorded; see MANIFEST) ===")
    print((ROOT / "eval" / "recorded_outputs" / f"{aid}.json").read_text())
    r = next(x for x in RUN.results if x.artifact.artifact_id == aid)
    print(f"\n=== 3. VALIDATION === output_ok={r.report.output_ok} accepted={len(r.report.accepted)} rejected={len(r.report.rejected)}")
    print("\n=== 4. NORMALIZED CANDIDATE FACTS ===")
    for f in r.report.accepted:
        print(f"  {f.fact_id:7s} {f.fact:25s} value={f.value!r:28s} normalized={json.dumps(f.normalized_value)}")
        print(f"          span[{f.span_start}:{f.span_end}]={f.source_span!r}  attribution={f.attribution} modality={f.modality} ambiguity={f.ambiguity}")
    f_all = facts(aid)
    revs = [ReviewDecision(f.fact_id, ReviewAction.APPROVE_AS_MERCHANT_ASSERTION, "reviewer-1") for f in f_all]
    for label, rv in (("UNREVIEWED (as extracted)", []), ("AFTER REVIEW: reviewer approves every fact as a MERCHANT ASSERTION", revs)):
        br, a = assess_extraction(REG, base_case(), f_all, ART, rv)
        print(f"\n=== 5. BRIDGE + DETERMINISTIC ASSESSMENT: {label} ===")
        print("  bridged     :", [(b['fact'], b['provenance_status']) for b in br.bridged])
        print("  not bridged :", [(n['fact'], n['reason']) for n in br.not_bridged])
        print(f"  policy_status={a.policy_status}  protection_assessment={a.protection_assessment.value}  "
              f"evidence_fields_assessment={a.evidence_fields_assessment.value}  paypal_acceptance={a.paypal_acceptance}")
        for c in a.checks:
            print(f"    {c.check_id:52s} {c.status.value:19s} {c.reason_code}")
        print("  digest:", a.digest[:24])
    print("\n=== 6. PROVENANCE CHAIN for A07#f6 (recipient_address), after review ===")
    br, a = assess_extraction(REG, base_case(), f_all, ART, revs)
    t = trace_fact(REG, br, a, next(f for f in f_all if f.fact_id == "A07#f6"), ART)
    print(json.dumps(t, indent=2))


def clean():
    f_all = facts("A01")
    revs = [ReviewDecision(f"A01#{i}", ReviewAction.APPROVE_AS_CARRIER_DOCUMENT, "reviewer-1") for i in ("f1", "f3", "f4", "f6")]
    br, a = assess_extraction(REG, base_case(), f_all, ART, revs, [Attestation("A01", "reviewer-1")])
    print(f"A01 reviewed as carrier document -> {a.protection_assessment.value} | {a.evidence_fields_assessment.value} | paypal_acceptance={a.paypal_acceptance} | {a.policy_status}")
    print("uncorroborated:", a.uncorroborated_requirements)


if __name__ == "__main__":
    {"example": example, "clean": clean}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
