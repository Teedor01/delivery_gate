"""Extraction evaluation. TEST data only; no training anywhere. Run:  python -m eval.evaluate [--live]

Live runs are resumable (eval/.live_cache) and rate-limit aware; see docs/GROQ.md.
Default replays eval/recorded_outputs (produced by the assistant that wrote the gold; see MANIFEST.json), so the numbers measure
the validator/bridge plumbing and the recorded outputs, NOT the accuracy of an independent model. `--live` uses the configured live extractor
(Groq or Anthropic; needs a provider key and EXTRACTION_MODEL) for a real measurement.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from delivery_extraction.extractor import RawExtraction, RecordedExtractor
from delivery_extraction.llm import LLMError
from delivery_extraction.pipeline import ExtractionRun, run_extraction
from delivery_extraction.schema import Artifact, CandidateFact
from eval.live_cache import LiveCache, cache_meta
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
        missing_gold: List[Dict[str, Any]] = []
        for g in gold["facts"]:
            hit = next((a for a in acc if a.fact_id not in used and a.fact == g["fact"] and a.entity_ref == g["entity_ref"]
                        and a.normalized_value == g["normalized_value"]), None)
            if hit:
                used.add(hit.fact_id); c["matched"] += 1; a_matched += 1
                c["span_ok"] += int(g["span_contains"] in hit.source_span and hit.span_end - hit.span_start == len(hit.source_span))
            else:
                missing_gold.append({"fact": g["fact"], "entity_ref": g["entity_ref"],
                                     "normalized_value": g["normalized_value"], "span_contains": g["span_contains"]})
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
        per[aid] = {"gold": len(gold["facts"]), "accepted": len(acc), "rejected": len(rep.rejected),
                    "must_not_violations": viol, "missing_gold_facts": missing_gold,
                    "rejected_details": [{"fact": x.raw.get("fact"), "value": x.raw.get("value"),
                                          "source_span": x.raw.get("source_span"), "reasons": list(x.reasons)}
                                         for x in rep.rejected]}
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


class _Prefetched:
    """Serves already-collected raw outputs to run_extraction (so contradiction grouping runs once, over the complete set)."""
    def __init__(self, raws: Dict[str, RawExtraction]):
        self.raws = raws

    def extract(self, artifact: Artifact) -> RawExtraction:
        return self.raws[artifact.artifact_id]


def collect_live(artifacts: Sequence[Artifact], live: Any, cache: Optional[LiveCache], say: Callable[[str], None], tpm: Optional[int] = None,
                 sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> Dict[str, Any]:
    """Extract every artifact, reusing cached successes. Never raises for a model failure: failures are recorded, not counted as passes.
    Aborts the remaining artifacts on authentication/request errors and on exhausted rate-limit retries (more calls would only fail)."""
    n = len(artifacts)
    raws: Dict[str, RawExtraction] = {}
    source: Dict[str, str] = {}
    failed: List[Dict[str, Any]] = []
    not_attempted: List[str] = []
    effort = getattr(live, "reasoning_effort", "n/a")
    abort = False
    for i, a in enumerate(artifacts, 1):
        aid = a.artifact_id
        if abort:
            not_attempted.append(aid)
            continue
        meta = cache_meta(a.sha256, live.KIND, live.model, effort)
        hit = cache.get(meta) if cache else None
        if hit is not None:
            raws[aid], source[aid] = hit, "cache"
            say(f"[{i}/{n}] {aid}: CACHED (no API call)   done {len(raws)}, remaining {n - len(raws) - len(failed)}")
            continue
        t0 = clock()
        try:
            raw = live.extract(a)
        except LLMError as e:
            failed.append({"artifact_id": aid, "error": str(e), "status": e.status, "attempts": e.attempts})
            say(f"[{i}/{n}] {aid}: FAILED after {e.attempts} attempt(s): {e}")
            if e.status in (400, 401, 403, 404) or (e.status == 429):
                abort = True
                say("stopping: further requests would fail the same way. Completed artifacts are saved; re-run to resume.")
            continue
        raws[aid], source[aid] = raw, "api"
        if cache:
            cache.put(meta, raw)
        used = getattr(live, "last_usage_tokens", None)
        say(f"[{i}/{n}] {aid}: FRESH API call ({getattr(live, 'last_attempts', 1)} request(s), {used if used is not None else '?'} tokens)   done {len(raws)}, remaining {n - len(raws) - len(failed)}")
        if tpm and used and i < n:
            sleep(max(0.0, used / tpm * 60 - (clock() - t0)))
    return {"raws": raws, "source": source, "failed": failed, "not_attempted": not_attempted}


def run_live_eval(argv_ns: argparse.Namespace, live: Any, out: Callable[[str], None]) -> int:
    arts = load_corpus()
    cache = None if argv_ns.no_cache else LiveCache(Path(argv_ns.cache_dir))
    got = collect_live(arts, live, cache, out, argv_ns.tpm)
    fresh, cached = sum(v == "api" for v in got["source"].values()), sum(v == "cache" for v in got["source"].values())
    complete = len(got["raws"]) == len(arts)
    if not complete:
        part = {"mode": "LIVE", "complete": False, "model": live.model, "expected_artifacts": len(arts), "completed": sorted(got["raws"]),
                "failed": got["failed"], "not_attempted": got["not_attempted"], "fresh_api_calls": fresh, "cache_hits": cached,
                "note": "PARTIAL: no metrics are reported and nothing here counts as a pass."}
        (ROOT / "eval" / "results_live_partial.json").write_text(json.dumps(part, indent=2))
        out(f"\nINCOMPLETE LIVE EVALUATION: {len(got['raws'])}/{len(arts)} artifacts extracted, {len(got['failed'])} failed, {len(got['not_attempted'])} not attempted.")
        out("No metrics are reported for a partial run. Re-run the same command to resume (completed artifacts are cached).")
        return 3
    run = run_extraction(arts, _Prefetched(got["raws"]), CASE_GROUPS)
    res = evaluate(run)
    res["run"] = {"mode": "LIVE", "complete": True, "model": live.model, "fresh_api_calls": fresh, "cache_hits": cached,
                  "per_artifact_source": got["source"], "note": "Live-model measurement. Not comparable to the recorded baseline in results.json."}
    (ROOT / "eval" / "results_live.json").write_text(json.dumps(res, indent=2))
    (ROOT / "eval" / "results_live_partial.json").unlink(missing_ok=True)
    return _report(res, out, f"LIVE ({fresh} fresh API call(s), {cached} from cache)")


def _report(res: Dict[str, Any], out: Callable[[str], None], label: str) -> int:
    out(f"extractor: {res['extractor_kinds']}   artifacts: {res['artifact_count']}   mode: {label}   counts: {res['counts']}")
    for k, v in res["metrics"].items():
        out(f"  {k:30s} {v!s:8s} (needs {res['thresholds'][k]})  {'PASS' if res['pass'][k] else 'FAIL'}")
    out("ALL PASS" if res["all_pass"] else "FAILURES PRESENT")
    return 0 if res["all_pass"] else 1


def main(argv: Optional[Sequence[str]] = None, env=None, live_factory=None, out: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m eval.evaluate", description="Extraction evaluation. Default: replay the recorded outputs (no network). --live: real model.")
    ap.add_argument("--live", action="store_true", help="use the configured live extractor (GROQ_API_KEY + EXTRACTION_MODEL); resumable")
    ap.add_argument("--cache-dir", default=str(ROOT / "eval" / ".live_cache"), help="checkpoint directory for successful live extractions")
    ap.add_argument("--no-cache", action="store_true", help="neither read nor write the checkpoint cache")
    ap.add_argument("--tpm", type=int, default=None, help="pace fresh calls to stay under this tokens-per-minute budget (e.g. 8000)")
    a = ap.parse_args(list(sys.argv[1:] if argv is None else argv))
    if a.tpm is not None and a.tpm <= 0:
        ap.error("--tpm must be positive")
    if a.live:
        from delivery_extraction.llm import GroqExtractor, make_extractor
        try:
            live = (live_factory or make_extractor)(env)
        except LLMError as e:
            out(f"live extractor configuration error: {e}")
            return 2
        if live is None:
            out("no live extractor configured: set GROQ_API_KEY (or ANTHROPIC_API_KEY) and EXTRACTION_MODEL; see docs/GROQ.md")
            return 2
        if isinstance(live, GroqExtractor):
            live.on_retry = lambda m: out("  " + m)
        return run_live_eval(a, live, out)
    res = evaluate(run_recorded())
    (ROOT / "eval" / "results.json").write_text(json.dumps(res, indent=2))
    return _report(res, out, "RECORDED")


if __name__ == "__main__":
    sys.exit(main())
