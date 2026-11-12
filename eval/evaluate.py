"""Extraction evaluation. TEST data only; no training anywhere. Run:  python -m eval.evaluate [--live]

Default replays eval/recorded_outputs (produced by the assistant that wrote the gold; see MANIFEST.json), so the numbers measure
the validator/bridge plumbing and the recorded outputs, NOT the accuracy of an independent model. `--live` uses the configured live extractor
(Groq or Anthropic; needs a provider key and EXTRACTION_MODEL) for a real measurement.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from delivery_extraction.extractor import RecordedExtractor
from delivery_extraction.pipeline import ExtractionRun, run_extraction
from delivery_extraction.schema import Artifact, CandidateFact
from eval.corpus import ADVERSARIAL_IDS, ARTIFACTS, CASE_GROUPS, EXPECTED_CONTRADICTIONS, GOLD

# Thresholds proposed up front (they were not previously agreed; adjust deliberately, not after seeing results).
THRESHOLDS = {
    "fact_recall": (">=", 0.95), "fact_precision": (">=", 0.95), "source_span_correctness": (">=", 0.95),
    "normalization_correctness": (">=", 1.0), "attribution_correctness": (">=", 0.95), "modality_correctness": (">=", 0.95),
    "ambiguity_preservation": (">=", 1.0), "contradiction_preservation": (">=", 1.0), "spurious_contradictions": ("<=", 0),
    "must_not_extract_violations": ("<=", 0), "hallucination_rate": ("<=", 0.0), "unsupported_field_rate": ("<=", 0.05),
}
HALLUCINATION_REASONS = ("SPAN_NOT_FOUND_IN_ARTIFACT", "VALUE_NOT_IN_SPAN", "FACT_NOT_IN_VOCABULARY", "FORBIDDEN_POLICY_LANGUAGE")


def _is_halluc(reasons) -> bool:
    return any(r.startswith(HALLUCINATION_REASONS) or r.startswith("UNGROUNDED_") for r in reasons)


def _counterpart(g: Dict[str, Any], accepted: List[CandidateFact]):
    return [a for a in accepted if a.fact == g["fact"] and a.entity_ref == g["entity_ref"] and g["span_contains"] in a.source_span]


def _violates(m: Dict[str, Any], a: CandidateFact) -> bool:
    if m["fact"] not in ("*", a.fact):
        return False
    if m.get("normalized_value", "*") not in ("*", a.normalized_value):
        return False
    if "entity_ref" in m and m["entity_ref"] != a.entity_ref:
        return False
    if "attribution" in m and m["attribution"] != a.attribution:
        return False
    return True


def evaluate(run: ExtractionRun) -> Dict[str, Any]:
    c = dict(gold=0, matched=0, accepted=0, matched_acc=0, span_ok=0, norm_tot=0, norm_ok=0, attr_tot=0, attr_ok=0, mod_ok=0,
             amb_tot=0, amb_ok=0, raw=0, halluc=0, rejected=0, must_not=0, unsupported=0)
    per: Dict[str, Any] = {}
    by_art = {r.artifact.artifact_id: r for r in run.results}
    for aid, r in by_art.items():
        gold, acc, rep = GOLD[aid], r.report.accepted, r.report
        c["gold"] += len(gold["facts"]); c["accepted"] += len(acc); c["raw"] += rep.raw_fact_count; c["rejected"] += len(rep.rejected)
        c["halluc"] += sum(1 for x in rep.rejected if _is_halluc(x.reasons))
        used: set = set()
        a_matched = 0
        for g in gold["facts"]:
            hit = next((a for a in acc if a.fact_id not in used and a.fact == g["fact"] and a.entity_ref == g["entity_ref"]
                        and a.normalized_value == g["normalized_value"]), None)
            if hit:
                used.add(hit.fact_id); c["matched"] += 1; a_matched += 1
                c["span_ok"] += int(g["span_contains"] in hit.source_span and hit.span_end - hit.span_start == len(hit.source_span))
            cp = _counterpart(g, acc)
            if cp:
                c["norm_tot"] += 1; c["norm_ok"] += int(any(a.normalized_value == g["normalized_value"] for a in cp))
                c["attr_tot"] += 1; c["attr_ok"] += int(any(a.attribution == g["attribution"] for a in cp))
                c["mod_ok"] += int(any(a.modality == g["modality"] for a in cp))
                if g["ambiguity"]:
                    c["amb_tot"] += 1; c["amb_ok"] += int(any(a.ambiguity and a.normalized_value == "UNKNOWN" for a in cp))
            elif g["ambiguity"]:
                c["amb_tot"] += 1
        c["matched_acc"] += len(used)
        c["unsupported"] += sum(1 for a in acc if not any(g["fact"] == a.fact and g["entity_ref"] == a.entity_ref and g["span_contains"] in a.source_span
                                                           for g in gold["facts"]))
        viol = [a.fact_id for a in acc if any(_violates(m, a) for m in gold["must_not_extract"])]
        c["must_not"] += len(viol)
        per[aid] = {"gold": len(gold["facts"]), "accepted": len(acc), "rejected": len(rep.rejected), "must_not_violations": viol}
    def ratio(n, d): return 1.0 if d == 0 else round(n / d, 4)
    found = {(x.group_id, x.fact, tuple(sorted({v["artifact_id"] for v in x.values}))) for x in run.contradictions}
    expected = {(e["group"], e["fact"], tuple(sorted(e["artifacts"]))) for e in EXPECTED_CONTRADICTIONS}
    m = {"fact_recall": ratio(c["matched"], c["gold"]), "fact_precision": ratio(c["matched_acc"], c["accepted"]),
         "source_span_correctness": ratio(c["span_ok"], c["matched"]), "normalization_correctness": ratio(c["norm_ok"], c["norm_tot"]),
         "attribution_correctness": ratio(c["attr_ok"], c["attr_tot"]), "modality_correctness": ratio(c["mod_ok"], c["attr_tot"]),
         "ambiguity_preservation": ratio(c["amb_ok"], c["amb_tot"]),
         "contradiction_preservation": ratio(len(expected & found), len(expected)),
         "spurious_contradictions": len(found - expected), "must_not_extract_violations": c["must_not"],
         "hallucination_rate": ratio(c["halluc"], c["raw"]) if c["raw"] and c["halluc"] else 0.0,
         "unsupported_field_rate": round(c["unsupported"] / c["accepted"], 4) if c["accepted"] else 0.0}
    verdict = {k: (m[k] >= t if op == ">=" else m[k] <= t) for k, (op, t) in THRESHOLDS.items()}
    return {"counts": c, "metrics": m, "thresholds": {k: f"{op} {t}" for k, (op, t) in THRESHOLDS.items()},
            "pass": verdict, "all_pass": all(verdict.values()), "per_artifact": per,
            "extractor_kinds": sorted({r.raw.extractor_kind for r in run.results}),
            "adversarial_artifacts": ADVERSARIAL_IDS, "artifact_count": len(run.results)}


def load_corpus() -> List[Artifact]:
    return [Artifact(a["id"], a["text"], a["kind"]) for a in ARTIFACTS]


def run_recorded() -> ExtractionRun:
    return run_extraction(load_corpus(), RecordedExtractor(ROOT / "eval" / "recorded_outputs"), CASE_GROUPS)


def main(argv: List[str]) -> int:
    if "--live" in argv:
        from delivery_extraction.llm import make_extractor
        live = make_extractor()
        if live is None:
            print("no live extractor configured: set GROQ_API_KEY (or ANTHROPIC_API_KEY) and EXTRACTION_MODEL; see docs/GROQ.md")
            return 2
        run = run_extraction(load_corpus(), live, CASE_GROUPS)
    else:
        run = run_recorded()
    res = evaluate(run)
    (ROOT / "eval" / ("results_live.json" if "--live" in argv else "results.json")).write_text(json.dumps(res, indent=2))
    print(f"extractor: {res['extractor_kinds']}   artifacts: {res['artifact_count']}   counts: {res['counts']}")
    for k, v in res["metrics"].items():
        print(f"  {k:30s} {v!s:8s} (needs {res['thresholds'][k]})  {'PASS' if res['pass'][k] else 'FAIL'}")
    print("ALL PASS" if res["all_pass"] else "FAILURES PRESENT")
    return 0 if res["all_pass"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
