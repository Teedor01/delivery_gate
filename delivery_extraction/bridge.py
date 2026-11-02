from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence

from delivery_gate.engine import Assessment, assess
from delivery_gate.models import Case, EvidenceFact, Provenance, ProvStatus, SourceType
from delivery_gate.registry import PolicyRegistry
from delivery_extraction.review import Attestation, ReviewAction, ReviewDecision, ReviewError
from delivery_extraction.schema import FACT_VOCAB, UNKNOWN, Artifact, CandidateFact

CARRIER_KINDS = {"CARRIER_EMAIL", "TRACKING_PASTE"}


class MultipleEntitiesError(ValueError):
    pass


@dataclass
class BridgeResult:
    case: Case
    entity_ref: Optional[str]
    bridged: List[Dict[str, Any]] = field(default_factory=list)
    not_bridged: List[Dict[str, Any]] = field(default_factory=list)
    evidence_index: Dict[str, List[str]] = field(default_factory=dict)     # engine evidence name -> candidate fact ids

    def to_dict(self) -> Dict[str, Any]:
        return {"entity_ref": self.entity_ref, "bridged": self.bridged, "not_bridged": self.not_bridged,
                "evidence_index": self.evidence_index}


def _provenance(f: CandidateFact, decision: Optional[ReviewDecision], artifact: Artifact,
                attested: set) -> Provenance:
    if decision is None:
        return Provenance(SourceType.EXTRACTED_FROM_TEXT, f.fact_id, ProvStatus.EXTRACTED_UNREVIEWED, None, None, f.source_span)
    if decision.action == ReviewAction.APPROVE_AS_MERCHANT_ASSERTION:
        return Provenance(SourceType.MERCHANT_STATEMENT, f.fact_id, ProvStatus.MERCHANT_ASSERTED, None, None, f.source_span)
    if decision.action == ReviewAction.APPROVE_AS_CARRIER_DOCUMENT:
        if artifact.artifact_id not in attested:
            raise ReviewError(f"{f.fact_id}: carrier-document approval needs a reviewer attestation for artifact {artifact.artifact_id}")
        if artifact.declared_kind not in CARRIER_KINDS:
            raise ReviewError(f"{f.fact_id}: artifact kind {artifact.declared_kind} cannot be a carrier document")
        if f.attribution not in ("CARRIER_STATEMENT", "UNKNOWN") or f.modality != "DIRECT":
            raise ReviewError(f"{f.fact_id}: a {f.attribution}/{f.modality} statement can never be promoted to a carrier document")
        return Provenance(SourceType.CARRIER_DOCUMENT, f.fact_id, ProvStatus.HUMAN_CONFIRMED, None, None, f.source_span)
    raise ReviewError(f"unsupported review action {decision.action}")


def build_case(base_case: Case, candidates: Sequence[CandidateFact], artifacts: Dict[str, Artifact],
               reviews: Iterable[ReviewDecision] = (), attestations: Iterable[Attestation] = (),
               entity_ref: Optional[str] = None) -> BridgeResult:
    decisions = {d.fact_id: d for d in reviews}
    attested = {a.artifact_id for a in attestations if a.attested_source_type == "CARRIER_DOCUMENT"}
    consumable = [c for c in candidates if FACT_VOCAB[c.fact]["engine"] and c.normalized_value != UNKNOWN]
    entities = sorted({c.entity_ref for c in consumable if c.entity_ref})
    if len(entities) > 1 and entity_ref is None:
        raise MultipleEntitiesError(f"artifacts describe several orders {entities}; select one with entity_ref")
    res = BridgeResult(base_case, entity_ref)
    items: List[EvidenceFact] = []
    carrier_artifacts: set = set()
    for c in candidates:
        spec = FACT_VOCAB[c.fact]
        row = {"fact_id": c.fact_id, "fact": c.fact, "artifact_id": c.artifact_id}
        if spec["engine"] is None:
            res.not_bridged.append({**row, "reason": "NOT_CONSUMED_BY_ENGINE", "why": spec.get("why", "")}); continue
        if c.normalized_value == UNKNOWN:
            res.not_bridged.append({**row, "reason": "NORMALIZED_UNKNOWN_REMAINS_MISSING", "ambiguity_note": c.ambiguity_note}); continue
        if entity_ref is not None and c.entity_ref not in (None, entity_ref):
            res.not_bridged.append({**row, "reason": "OTHER_ENTITY", "entity_ref": c.entity_ref}); continue
        d = decisions.get(c.fact_id)
        if d is not None and d.action == ReviewAction.REJECT:
            res.not_bridged.append({**row, "reason": "REJECTED_BY_REVIEWER", "reviewer": d.reviewer}); continue
        prov = _provenance(c, d, artifacts[c.artifact_id], attested)
        ev = EvidenceFact(spec["engine"], c.normalized_value, prov)
        items.append(ev)
        if prov.source_type == SourceType.CARRIER_DOCUMENT:
            carrier_artifacts.add(c.artifact_id)
        res.bridged.append({**row, "engine_evidence": spec["engine"], "engine_value": ev.value,
                            "source_type": prov.source_type.value, "provenance_status": prov.status.value,
                            "source_ref": prov.source_ref, "reviewed": d is not None})
        res.evidence_index.setdefault(spec["engine"], []).append(c.fact_id)
    for aid in sorted(carrier_artifacts):                      # the reviewer attested these artifacts as carrier documents
        ev = EvidenceFact("delivery_record", True, Provenance(SourceType.CARRIER_DOCUMENT, f"{aid}#attestation", ProvStatus.HUMAN_CONFIRMED))
        items.append(ev)
        res.bridged.append({"fact_id": f"{aid}#attestation", "fact": "reviewer_attestation", "artifact_id": aid,
                            "engine_evidence": "delivery_record", "engine_value": True, "source_type": "CARRIER_DOCUMENT",
                            "provenance_status": "HUMAN_CONFIRMED", "source_ref": f"{aid}#attestation", "reviewed": True})
        res.evidence_index.setdefault("delivery_record", []).append(f"{aid}#attestation")
    res.case = Case(base_case.case_id, base_case.transaction_facts, base_case.evidence + tuple(items))
    return res


def assess_extraction(registry: PolicyRegistry, base_case: Case, candidates: Sequence[CandidateFact],
                      artifacts: Dict[str, Artifact], reviews=(), attestations=(), entity_ref=None):
    br = build_case(base_case, candidates, artifacts, reviews, attestations, entity_ref)
    return br, assess(registry, br.case)


def trace_fact(registry: PolicyRegistry, br: BridgeResult, assessment: Assessment, fact: CandidateFact,
               artifacts: Dict[str, Artifact]) -> Dict[str, Any]:
    """candidate fact -> source span -> artifact -> deterministic assessment -> policy requirement -> PayPal source passage."""
    art = artifacts[fact.artifact_id]
    engine_name = FACT_VOCAB[fact.fact]["engine"]
    entry = next((b for b in br.bridged if b["fact_id"] == fact.fact_id), None)
    chain: Dict[str, Any] = {
        "1_candidate_fact": {"fact_id": fact.fact_id, "fact": fact.fact, "value": fact.value, "normalized_value": fact.normalized_value,
                             "attribution": fact.attribution, "modality": fact.modality, "ambiguity": fact.ambiguity},
        "2_source_span": {"text": fact.source_span, "start": fact.span_start, "end": fact.span_end,
                          "verified_exact_substring": art.text[fact.span_start:fact.span_end] == fact.source_span},
        "3_artifact": {"artifact_id": art.artifact_id, "declared_kind": art.declared_kind, "sha256": art.sha256},
        "4_engine_input": entry or {"not_bridged": next((n for n in br.not_bridged if n["fact_id"] == fact.fact_id), None)},
        "5_assessment_checks": [], "6_policy_requirements": [], "7_paypal_source_passages": []}
    if engine_name is None or entry is None:
        return chain
    rule = registry.rules[assessment.rule["rule_id"]] if assessment.rule else None
    descs = {c["check_id"]: c for c in rule.raw["checks"]} if rule else {}
    seen: set = set()
    for chk in assessment.checks:
        if engine_name not in chk.inputs_used:
            continue
        chain["5_assessment_checks"].append({"check_id": chk.check_id, "status": chk.status.value, "reason_code": chk.reason_code,
                                             "establishes": chk.establishes, "paypal_acceptance": chk.paypal_acceptance})
        spec = descs.get(chk.check_id)
        if spec:
            chain["6_policy_requirements"].append({"check_id": chk.check_id, "kind": spec["kind"], "requirement": spec["description"],
                                                   "passage_ids": spec["passage_ids"]})
        for pid in chk.passage_ids:
            if pid in seen:
                continue
            seen.add(pid)
            p = registry.passages[pid]
            s = registry.sources[p["source"]]
            chain["7_paypal_source_passages"].append({"passage_id": pid, "section_locator": p["section_locator"],
                                                      "passage_sha256_prefix": p["passage_sha256"][:16], "source_url": s.url,
                                                      "source_title": s.title, "policy_status": assessment.policy_status})
    return chain
