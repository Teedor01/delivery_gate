from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from delivery_extraction.dates import find_dates, find_times
from delivery_extraction.schema import (
    ADDRESS_FIELDS, ARTIFACT_KINDS, ATTRIBUTIONS, CONFIDENCES, FACT_KEYS, FACT_VOCAB, MAX_SPAN_CHARS, MODALITIES,
    OUTPUT_KEYS, UNKNOWN, Artifact, CandidateFact,
)

FORBIDDEN = re.compile(
    r"PROTECT|ELIGIB|WILL[ _-]?(BE[ _-]?)?(ACCEPT|WON|WIN|COVER)|DISPUTE[ _-]?(WON|WIN)|SELLER[ _-]?PROTECT|"
    r"PAYPAL[ _-]?(SHOULD|WILL|ACCEPT|COVER)|COVERED|COVERAGE|WIN[ _-]?THE[ _-]?DISPUTE|REQUIREMENTS?[ _-]?(MET|DEMONSTRATED)",
    re.I)
HEDGE = re.compile(
    r"\b(probably|possibly|perhaps|maybe|likely|might|may have|should have|i think|i believe|i guess|seems?|appears?|"
    r"looks like|not sure|unsure|supposedly|allegedly|around|approximately|roughly|expected|estimated|scheduled)\b", re.I)
DELIVERED_CUE = re.compile(r"\bdelivered\b", re.I)
DELIVERED_NEG = re.compile(r"\b(not delivered|undelivered|wasn'?t delivered|hasn'?t been delivered|never delivered|failed)\b", re.I)
FUTURE_OR_PARTIAL = re.compile(r"\b(will be delivered|should arrive|out for delivery|in transit)\b", re.I)
STATUS_CUES = {
    "DELIVERED": DELIVERED_CUE,
    "IN_TRANSIT": re.compile(r"\b(in transit|out for delivery|on its way|on the way)\b", re.I),
    "RETURNED": re.compile(r"\breturn(ed)? to sender\b|\breturned\b", re.I),
    "UNDELIVERABLE": re.compile(r"\b(undeliverable|could not be delivered|delivery attempt failed)\b", re.I),
}
SIG_TRUE = re.compile(r"\bsigned\b|\bsignature\b", re.I)
SIG_FALSE = re.compile(r"\b(no(body| one)? signed|not signed|no signature|unsigned|signature (was )?not|without (a )?signature)\b", re.I)
REDIRECT_TRUE = re.compile(r"\b(redirect(ed)?|re-?routed|diverted|forwarded)\b", re.I)
REDIRECT_FALSE = re.compile(r"\b(not redirected|wasn'?t redirected|never redirected|no redirect(ion)?|hasn'?t been redirected)\b", re.I)
RELAYED_CUE = re.compile(r"\b(customer|buyer|client)\s+(says|said|claims|claimed|told|states|stated|reports?)\b", re.I)
ADDRESS_ROLE_SUSPECT = re.compile(r"\b(billing|bill to|invoice address|return address|ship(ped)? from|sender|from address)\b", re.I)
INTENDED_CUE = re.compile(r"\b(supposed to (go|be shipped|ship)|should (go|ship)|intended (for|to)|meant to go|ordered to ship|ship(ping)? to)\b", re.I)


def norm_text(s: Any) -> str:
    s = re.sub(r"[^\w\s]", " ", str(s).casefold())
    return re.sub(r"\s+", " ", s).strip()


def alnum_upper(s: Any) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", str(s)).upper()


@dataclass(frozen=True)
class RejectedFact:
    local_id: Optional[str]
    raw: Dict[str, Any]
    reasons: Tuple[str, ...]


@dataclass
class ValidationReport:
    artifact_id: str
    output_ok: bool = True
    output_errors: List[str] = field(default_factory=list)
    accepted: List[CandidateFact] = field(default_factory=list)
    rejected: List[RejectedFact] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    dropped_notes: int = 0
    raw_fact_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {"artifact_id": self.artifact_id, "output_ok": self.output_ok, "output_errors": self.output_errors,
                "accepted": [f.to_dict() for f in self.accepted],
                "rejected": [{"local_id": r.local_id, "reasons": list(r.reasons), "raw": r.raw} for r in self.rejected],
                "notes": self.notes, "dropped_notes": self.dropped_notes, "raw_fact_count": self.raw_fact_count}


def _strip_fence(raw: str) -> str:
    s = raw.strip()
    m = re.fullmatch(r"```(?:json)?\s*(.*?)\s*```", s, re.S)
    return m.group(1) if m else s


def _model_authored_strings(f: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for k in ("fact", "value", "ambiguity_note", "entity_ref", "fact_id"):
        v = f.get(k)
        if isinstance(v, str):
            out.append(v)
    nv = f.get("normalized_value")
    if isinstance(nv, str):
        out.append(nv)
    elif isinstance(nv, dict):
        out += [str(x) for x in nv.values()] + [str(k) for k in nv]
    return out


def _check_grounding(f: Dict[str, Any], span: str, reasons: List[str]) -> None:
    spec = FACT_VOCAB[f["fact"]]
    typ, nv, value = spec["type"], f["normalized_value"], f["value"]
    if nv == UNKNOWN:
        if f["ambiguity"] is not True:
            reasons.append("UNKNOWN_WITHOUT_AMBIGUITY")
        return                                  
    if value == UNKNOWN:
        reasons.append("VALUE_UNKNOWN_BUT_NORMALIZED_SET")
    elif norm_text(value) not in norm_text(span):
        reasons.append("VALUE_NOT_IN_SPAN")
    if typ == "string":
        if not isinstance(nv, str) or not nv:
            reasons.append("BAD_TYPE"); return
        if f["fact"] == "tracking_number":
            if nv != alnum_upper(value) or alnum_upper(value) not in alnum_upper(span) or not re.fullmatch(r"[A-Z0-9]{8,40}", nv):
                reasons.append("UNGROUNDED_TRACKING_NUMBER")
        elif f["fact"] == "order_reference":
            if norm_text(nv) not in norm_text(span):
                reasons.append("UNGROUNDED_ORDER_REFERENCE")
        elif norm_text(nv) != norm_text(value):
            reasons.append("UNGROUNDED_STRING")
    elif typ == "enum":
        if nv not in spec["values"]:
            reasons.append("BAD_ENUM"); return
        if not STATUS_CUES[nv].search(span):
            reasons.append("UNGROUNDED_STATUS")
        if nv == "DELIVERED" and (DELIVERED_NEG.search(span) or FUTURE_OR_PARTIAL.search(span)):
            reasons.append("STATUS_CONTRADICTED_BY_SPAN")
    elif typ == "date":
        found, ambiguous = find_dates(span)
        if not isinstance(nv, str) or nv not in found:
            reasons.append("DATE_AMBIGUOUS_NUMERIC" if ambiguous and not found else "UNGROUNDED_DATE")
    elif typ == "time":
        if not isinstance(nv, str) or nv not in find_times(span):
            reasons.append("UNGROUNDED_TIME")
    elif typ == "bool":
        if not isinstance(nv, bool):
            reasons.append("BAD_TYPE"); return
        name = f["fact"]
        pos, neg = (SIG_TRUE, SIG_FALSE) if name == "signature_present" else (REDIRECT_TRUE, REDIRECT_FALSE)
        if nv is True and (neg.search(span) or not pos.search(span)):
            reasons.append("UNGROUNDED_BOOLEAN")
        if nv is False and not neg.search(span):
            reasons.append("UNGROUNDED_BOOLEAN")      
    elif typ == "address":
        if not isinstance(nv, dict) or not nv or not set(nv) <= set(ADDRESS_FIELDS) or not all(isinstance(v, str) and v for v in nv.values()):
            reasons.append("BAD_TYPE"); return
        ns = norm_text(span)
        if not all(norm_text(v) in ns for v in nv.values()):
            reasons.append("UNGROUNDED_ADDRESS_COMPONENT")
        if ADDRESS_ROLE_SUSPECT.search(span):
            reasons.append("ADDRESS_ROLE_SUSPECT")
        if f["fact"] == "intended_ship_to_address" and not INTENDED_CUE.search(span):
            reasons.append("UNGROUNDED_INTENT_CUE")


def _validate_fact(f: Any, artifact: Artifact, seen_ids: set) -> Tuple[Optional[CandidateFact], List[str]]:
    reasons: List[str] = []
    if not isinstance(f, dict):
        return None, ["FACT_NOT_AN_OBJECT"]
    keys = set(f)
    if keys - set(FACT_KEYS):
        reasons.append("UNKNOWN_KEYS:" + ",".join(sorted(keys - set(FACT_KEYS))))
    if set(FACT_KEYS) - keys:
        reasons.append("MISSING_KEYS:" + ",".join(sorted(set(FACT_KEYS) - keys)))
    if reasons:
        return None, reasons
    if f["fact"] not in FACT_VOCAB:
        reasons.append("FACT_NOT_IN_VOCABULARY")
    if any(FORBIDDEN.search(s) for s in _model_authored_strings(f)):
        reasons.append("FORBIDDEN_POLICY_LANGUAGE")
    if not isinstance(f["fact_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", f["fact_id"]):
        reasons.append("BAD_FACT_ID")
    elif f["fact_id"] in seen_ids:
        reasons.append("DUPLICATE_FACT_ID")
    if f["artifact_id"] != artifact.artifact_id:
        reasons.append("ARTIFACT_ID_MISMATCH")
    if f["confidence"] not in CONFIDENCES:
        reasons.append("BAD_CONFIDENCE")
    if f["attribution"] not in ATTRIBUTIONS:
        reasons.append("BAD_ATTRIBUTION")
    if f["modality"] not in MODALITIES:
        reasons.append("BAD_MODALITY")
    if not isinstance(f["ambiguity"], bool):
        reasons.append("BAD_AMBIGUITY")
    if f["ambiguity_note"] is not None and not isinstance(f["ambiguity_note"], str):
        reasons.append("BAD_AMBIGUITY_NOTE")
    if f["entity_ref"] is not None and (not isinstance(f["entity_ref"], str) or f["entity_ref"] not in artifact.text):
        reasons.append("ENTITY_REF_NOT_IN_ARTIFACT")
    if not isinstance(f["value"], str):
        reasons.append("BAD_TYPE")
    span = f["source_span"]
    if not isinstance(span, str) or not span.strip():
        reasons.append("SPAN_EMPTY")
        return None, reasons
    if len(span) > MAX_SPAN_CHARS:
        reasons.append("SPAN_TOO_LONG")
    start = artifact.text.find(span)
    if start < 0:
        reasons.append("SPAN_NOT_FOUND_IN_ARTIFACT")     
    if reasons:
        return None, reasons
    # semantic guards that need a well-formed fact
    if HEDGE.search(span) and f["modality"] != "HEDGED":
        reasons.append("HEDGE_NOT_PRESERVED")
    if f["modality"] == "HEDGED" and (f["normalized_value"] != UNKNOWN or f["ambiguity"] is not True):
        reasons.append("HEDGED_VALUE_MUST_BE_UNKNOWN_AND_AMBIGUOUS")
    if f["attribution"] == "CARRIER_STATEMENT" and RELAYED_CUE.search(span):
        reasons.append("ATTRIBUTION_CONTRADICTS_SPAN")
    if RELAYED_CUE.search(span) and f["attribution"] not in ("CUSTOMER_STATEMENT_RELAYED", "UNKNOWN"):
        reasons.append("RELAYED_STATEMENT_MISATTRIBUTED")
    _check_grounding(f, span, reasons)
    if reasons:
        return None, reasons
    seen_ids.add(f["fact_id"])
    return CandidateFact(artifact.artifact_id, f["fact_id"], f["fact"], f["value"], f["normalized_value"], span, start,
                         start + len(span), f["confidence"], f["ambiguity"], f["ambiguity_note"], f["attribution"],
                         f["modality"], f["entity_ref"]), []


def validate_output(artifact: Artifact, raw_text: str) -> ValidationReport:
    rep = ValidationReport(artifact.artifact_id)
    try:
        doc = json.loads(_strip_fence(raw_text))
    except (ValueError, TypeError):
        rep.output_ok, rep.output_errors = False, ["INVALID_JSON"]
        return rep
    if not isinstance(doc, dict):
        rep.output_ok, rep.output_errors = False, ["OUTPUT_NOT_AN_OBJECT"]
        return rep
    extra, missing = set(doc) - set(OUTPUT_KEYS), set(OUTPUT_KEYS) - set(doc)
    if extra or missing:                                   # e.g. a smuggled `decision` / `protection_assessment` key
        rep.output_ok = False
        rep.output_errors = ([f"UNKNOWN_TOP_LEVEL_KEYS:{','.join(sorted(extra))}"] if extra else []) + \
                            ([f"MISSING_TOP_LEVEL_KEYS:{','.join(sorted(missing))}"] if missing else [])
        return rep
    if doc["artifact_id"] != artifact.artifact_id:
        rep.output_ok, rep.output_errors = False, ["OUTPUT_ARTIFACT_ID_MISMATCH"]
        return rep
    if not isinstance(doc["facts"], list) or not isinstance(doc["extraction_notes"], list):
        rep.output_ok, rep.output_errors = False, ["BAD_TOP_LEVEL_TYPES"]
        return rep
    for n in doc["extraction_notes"]:
        if isinstance(n, str) and not FORBIDDEN.search(n):
            rep.notes.append(n)
        else:
            rep.dropped_notes += 1
    rep.raw_fact_count = len(doc["facts"])
    seen: set = set()
    for f in doc["facts"]:
        cf, reasons = _validate_fact(f, artifact, seen)
        if cf is not None:
            rep.accepted.append(cf)
        else:
            rep.rejected.append(RejectedFact(f.get("fact_id") if isinstance(f, dict) else None,
                                             f if isinstance(f, dict) else {"raw": repr(f)}, tuple(reasons)))
    return rep
