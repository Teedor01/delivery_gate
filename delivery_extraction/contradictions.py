from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from delivery_extraction.schema import UNKNOWN, CandidateFact
from delivery_extraction.validate import norm_text

COMPARABLE = {"tracking_number", "delivery_status", "delivery_date", "shipment_date", "recipient_address",
              "redirect_reported", "signature_present", "carrier_name"}


@dataclass(frozen=True)
class Contradiction:
    contradiction_id: str
    group_id: str
    fact: str
    entity_ref: Any
    status: str                       
    needs_human_review: bool
    fact_ids: Tuple[str, ...]
    values: Tuple[Dict[str, Any], ...]
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {"contradiction_id": self.contradiction_id, "group_id": self.group_id, "fact": self.fact, "entity_ref": self.entity_ref,
                "status": self.status, "needs_human_review": self.needs_human_review, "fact_ids": list(self.fact_ids),
                "values": list(self.values), "note": self.note}


def _norm_addr(a: Dict[str, str]) -> Dict[str, str]:
    return {k: norm_text(v) for k, v in a.items()}


def _differs(fact: str, a: Any, b: Any) -> bool:
    if fact == "recipient_address":
        na, nb = _norm_addr(a), _norm_addr(b)
        common = set(na) & set(nb)
        return bool(common) and any(na[k] != nb[k] for k in common)     
    if isinstance(a, str) and isinstance(b, str):
        return norm_text(a) != norm_text(b)
    return a != b


def detect(candidates: List[CandidateFact], group_id: str = "default") -> List[Contradiction]:
    """Compare facts that belong to ONE case. The caller decides which artifacts belong together (see pipeline groups);
    facts from unrelated orders must never be compared, and entity_ref keeps orders inside one artifact apart."""
    usable = [c for c in candidates if c.fact in COMPARABLE and c.normalized_value != UNKNOWN]
    out: List[Contradiction] = []
    for i, a in enumerate(usable):
        for b in usable[i + 1:]:
            if a.fact != b.fact or a.entity_ref != b.entity_ref or not _differs(a.fact, a.normalized_value, b.normalized_value):
                continue
            note = ("strict comparison; may be a formatting/abbreviation difference, flagged for human review"
                    if a.fact == "recipient_address" else "the artifacts state different values; neither is chosen")
            out.append(Contradiction(f"{group_id}:C{len(out) + 1}", group_id, a.fact, a.entity_ref, "CONTRADICTED", True,
                                     (a.fact_id, b.fact_id),
                                     ({"fact_id": a.fact_id, "artifact_id": a.artifact_id, "normalized_value": a.normalized_value,
                                       "source_span": a.source_span},
                                      {"fact_id": b.fact_id, "artifact_id": b.artifact_id, "normalized_value": b.normalized_value,
                                       "source_span": b.source_span}), note))
    return out
