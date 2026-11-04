from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Callable, Dict, List, Optional, Tuple

from .models import (
    NON_BLOCKING, NOT_ESTABLISHED_CLAIM, PAYPAL_ACCEPTANCE_NOT_ESTABLISHED, Case, Changes, EvidenceFact,
    EvidenceFieldsAssessment, EvidenceStatus, Layer, ProtectionAssessment, ProvStatus, SourceType, TransactionFact,
    canonical, norm_address, sha256_hex,
)
from .registry import PolicyRegistry, Rule

SCOPE_NOTE = (
    "The assessment speaks only for the requirements listed under `checks`, and only at the level of the fields those "
    "requirements name. Items under `open_items`, `not_modeled` and `unknowns` were not evaluated. PayPal determines "
    "eligibility in its sole discretion; no output asserts that PayPal accepts any artifact as sufficient proof, that the "
    "merchant is protected, or that the merchant will retain the funds."
)
UNREVIEWED_NOTICE = ("Policy rules are UNREVIEWED and source documents were not raw-byte verified. This assessment is NOT an "
                     "officially verified PayPal interpretation and must not be presented as one.")
CORROBORATING_SOURCE_TYPES = {SourceType.CARRIER_DOCUMENT, SourceType.CARRIER_API, SourceType.PAYPAL_API}
OBSERVED_NAMES = ("merchant_account_country", "claim_category", "route", "funding_source",
                  "paypal_seller_protection_status", "physical_goods")


# ---- result types -------------------------------------------------------------------------------
@dataclass(frozen=True)
class EvidenceAssessment:
    """Layer EVIDENCE_ASSESSMENT: what the supplied artifacts establish about the FIELDS of ONE policy requirement."""
    check_id: str
    kind: str
    status: EvidenceStatus
    reason_code: str
    detail: str
    passage_ids: Tuple[str, ...]
    inputs_used: Tuple[str, ...]
    interpretation: bool = False
    interpretation_note: Optional[str] = None
    needs_human_review: bool = False
    establishes: Optional[str] = None            
    corroboration: str = "NOT_APPLICABLE"       
    paypal_acceptance: str = PAYPAL_ACCEPTANCE_NOT_ESTABLISHED
    does_not_establish: Tuple[str, ...] = (NOT_ESTABLISHED_CLAIM,)

    def to_dict(self) -> Dict[str, Any]:
        return {"layer": Layer.EVIDENCE_ASSESSMENT.value, "check_id": self.check_id, "kind": self.kind,
                "status": self.status.value, "reason_code": self.reason_code, "detail": self.detail,
                "passage_ids": list(self.passage_ids), "inputs_used": list(self.inputs_used),
                "interpretation": self.interpretation, "interpretation_note": self.interpretation_note,
                "needs_human_review": self.needs_human_review, "establishes": self.establishes,
                "corroboration": self.corroboration, "paypal_acceptance": self.paypal_acceptance,
                "does_not_establish": list(self.does_not_establish)}


@dataclass(frozen=True)
class GateResult:
    gate_id: str
    gate_type: str
    outcome: str                      
    reason_code: str
    detail: str
    passage_ids: Tuple[str, ...]
    inputs_used: Tuple[str, ...]
    interpretation: bool = False
    interpretation_note: Optional[str] = None

    @property
    def terminal(self) -> bool:
        return self.outcome != "PASS"

    def to_dict(self) -> Dict[str, Any]:
        return {"gate_id": self.gate_id, "gate_type": self.gate_type, "outcome": self.outcome,
                "reason_code": self.reason_code, "detail": self.detail, "passage_ids": list(self.passage_ids),
                "inputs_used": list(self.inputs_used), "interpretation": self.interpretation,
                "interpretation_note": self.interpretation_note}


@dataclass(frozen=True)
class Assessment:
    case_id: str
    policy_status: str
    display_notice: str
    rule: Optional[Dict[str, Any]]
    protection_assessment: ProtectionAssessment
    evidence_fields_assessment: EvidenceFieldsAssessment
    paypal_acceptance: str
    reason_codes: Tuple[str, ...]
    observed_inputs: Dict[str, Any]
    gates: Tuple[GateResult, ...]
    policy_conditions: Tuple[Dict[str, Any], ...]
    exclusions: Tuple[Dict[str, Any], ...]
    checks: Tuple[EvidenceAssessment, ...]
    uncorroborated_requirements: Tuple[str, ...]
    open_items: Tuple[Dict[str, Any], ...]
    not_modeled: Tuple[Dict[str, Any], ...]
    unknowns: Tuple[Dict[str, Any], ...]
    needs_human_review: bool
    timing_requirement: Optional[str]
    exposure: Optional[Dict[str, Any]]
    explanation: Tuple[str, ...]
    digest: str = ""

    def core_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id, "policy_status": self.policy_status, "display_notice": self.display_notice,
            "rule": self.rule, "protection_assessment": self.protection_assessment.value,
            "evidence_fields_assessment": self.evidence_fields_assessment.value,
            "paypal_acceptance": self.paypal_acceptance, "reason_codes": list(self.reason_codes),
            "observed_inputs": self.observed_inputs, "gates": [g.to_dict() for g in self.gates],
            "policy_conditions": list(self.policy_conditions), "exclusions": list(self.exclusions),
            "checks": [c.to_dict() for c in self.checks],
            "uncorroborated_requirements": list(self.uncorroborated_requirements),
            "open_items": list(self.open_items), "not_modeled": list(self.not_modeled),
            "unknowns": list(self.unknowns), "needs_human_review": self.needs_human_review,
            "timing_requirement": self.timing_requirement, "exposure": self.exposure,
            "scope_note": SCOPE_NOTE, "explanation": list(self.explanation),
        }

    def to_dict(self) -> Dict[str, Any]:
        d = self.core_dict()
        d["digest"] = self.digest
        return d

    def check(self, check_id: str) -> Optional[EvidenceAssessment]:
        return next((c for c in self.checks if c.check_id == check_id), None)

    def gate(self, gate_id: str) -> Optional[GateResult]:
        return next((g for g in self.gates if g.gate_id == gate_id), None)

    def condition(self, condition_id: str) -> Optional[Dict[str, Any]]:
        return next((c for c in self.policy_conditions if c["condition_id"] == condition_id), None)

    def blocking(self) -> List[EvidenceAssessment]:
        return [c for c in self.checks if c.status not in NON_BLOCKING]


# ---- fact + evidence resolution ----------------------------------------------------------------------
def _unknown_provenance(f) -> bool:
    return f.provenance.status == ProvStatus.UNKNOWN or f.provenance.source_type == SourceType.UNKNOWN


def _fact(case: Case, name: str) -> Optional[TransactionFact]:
    """A transaction fact is usable only if it was supplied AND its provenance is known."""
    f = case.fact(name)
    return None if f is None or _unknown_provenance(f) else f


@dataclass(frozen=True)
class Resolved:
    state: str                         
    value: Any = None
    items: Tuple[EvidenceFact, ...] = ()
    distinct: Tuple[Any, ...] = ()
    reason: str = ""


def _canon(value: Any) -> Any:
    return norm_address(value) if isinstance(value, dict) else value


def resolve(case: Case, name: str) -> Resolved:
    """Collapse the evidence items for one name. Items that are unreviewed extractions or carry unknown provenance never
    count as support; differing usable values are a conflict. Confidence is never consulted."""
    items = case.evidence_items(name)
    if not items:
        return Resolved("MISSING")
    usable = tuple(i for i in items if i.provenance.status != ProvStatus.EXTRACTED_UNREVIEWED and not _unknown_provenance(i))
    if not usable:
        reason = "UNKNOWN_PROVENANCE" if any(_unknown_provenance(i) for i in items) else "ONLY_UNREVIEWED_EXTRACTION"
        return Resolved("REVIEW_ONLY", items=items, reason=reason)
    distinct = {canonical(_canon(i.value)): i.value for i in usable}
    if len(distinct) > 1:
        return Resolved("CONFLICT", items=usable, distinct=tuple(distinct.values()))
    return Resolved("VALUE", usable[0].value, usable, tuple(distinct.values()))


def _corr(items) -> str:
    items = list(items)
    if items and all(i.provenance.source_type in CORROBORATING_SOURCE_TYPES for i in items):
        return "CORROBORATED"
    return "MERCHANT_ASSERTED_ONLY"


def _mk(req: Dict[str, Any], status: EvidenceStatus, reason: str, detail: str, inputs: List[str],
        review: bool = False, corr: Optional[str] = None) -> EvidenceAssessment:
    demonstrated = status == EvidenceStatus.DEMONSTRATED
    return EvidenceAssessment(
        req["check_id"], req["kind"], status, reason, detail, tuple(req["passage_ids"]), tuple(inputs),
        bool(req.get("interpretation")), req.get("interpretation_note"), review,
        establishes=req["establishes"] if demonstrated else None,
        corroboration=(corr or "MERCHANT_ASSERTED_ONLY") if demonstrated else "NOT_APPLICABLE",
        paypal_acceptance=(PAYPAL_ACCEPTANCE_NOT_ESTABLISHED if not req["sufficiency_stated_by_policy"] else "STATED_BY_POLICY"),
        does_not_establish=tuple(req.get("does_not_establish", ())))


def _non_value(req: Dict[str, Any], res: Resolved, name: str, inputs: List[str]) -> EvidenceAssessment:
    if res.state == "REVIEW_ONLY":
        why = ("has unknown provenance" if res.reason == "UNKNOWN_PROVENANCE"
               else "is supported only by unreviewed extracted values")
        return _mk(req, EvidenceStatus.NEEDS_HUMAN_REVIEW, res.reason, f"{name} {why}", inputs, True)
    if res.state == "CONFLICT":
        return _mk(req, EvidenceStatus.CONTRADICTED, "CONFLICTING_EVIDENCE",
                   f"{name} has conflicting reviewed values: {list(res.distinct)}", inputs, True)
    return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "MISSING_FACT", f"{name} was not supplied", inputs)


def _address_diffs(recipient: Dict[str, Any], td: Dict[str, Any]) -> List[str]:
    """Strict: exact equality after case/punctuation/whitespace normalisation. No abbreviation expansion, no fuzzy match."""
    r, t = norm_address(recipient), norm_address(td)
    return [k for k in t if r.get(k) != t[k]]


# ---- evaluators (one per rule `evaluator` name) -----------------------------------------------------
def ev_record_present(case: Case, req: Dict[str, Any]) -> EvidenceAssessment:
    names, carrier = req["params"]["evidence"], set(req["params"]["carrier_source_types"])
    res = {n: resolve(case, n) for n in names}
    inputs = list(names)
    for n, r in res.items():
        if r.state == "CONFLICT":
            return _non_value(req, r, n, inputs)
    true_items = [i for n, r in res.items() if r.state == "VALUE" and r.value is True for i in r.items]
    if true_items:
        carrier_items = [i for i in true_items if i.provenance.source_type.value in carrier]
        if carrier_items:
            return _mk(req, EvidenceStatus.DEMONSTRATED, "RECORD_PRESENT",
                       "A record from a shipping-company source type is present. This establishes presence of the record only.",
                       inputs, corr=_corr(carrier_items))
        found = sorted({i.provenance.source_type.value for i in true_items})
        return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "SOURCE_TYPE_NOT_CARRIER",
                   f"A record is asserted, but source type(s) {found} are not shipping-company sources.", inputs, True)
    for n, r in res.items():
        if r.state == "REVIEW_ONLY":
            return _non_value(req, r, n, inputs)
    if any(r.state == "VALUE" for r in res.values()):
        return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "RECORD_ASSERTED_ABSENT", "The record is asserted absent.", inputs)
    return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "MISSING_FACT", f"None of {names} was supplied.", inputs)


def ev_value_present(case: Case, req: Dict[str, Any]) -> EvidenceAssessment:
    names = req["params"]["evidence"]
    res = {n: resolve(case, n) for n in names}
    for n, r in res.items():
        if r.state == "CONFLICT":
            return _non_value(req, r, n, list(names))
    present = [(n, r) for n, r in res.items() if r.state == "VALUE"]
    if present:
        items = [i for _, r in present for i in r.items]
        return _mk(req, EvidenceStatus.DEMONSTRATED, "VALUE_PRESENT", f"Present: {[n for n, _ in present]}",
                   list(names), corr=_corr(items))
    for n, r in res.items():
        if r.state == "REVIEW_ONLY":
            return _non_value(req, r, n, list(names))
    return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "MISSING_FACT", f"None of {names} was supplied.", list(names))


def ev_delivery_date_and_status(case: Case, req: Dict[str, Any]) -> EvidenceAssessment:
    p = req["params"]
    inputs = [p["date"], p["status"]]
    rd, rs = resolve(case, p["date"]), resolve(case, p["status"])
    for n, r in ((p["date"], rd), (p["status"], rs)):
        if r.state in ("CONFLICT", "REVIEW_ONLY"):
            return _non_value(req, r, n, inputs)
    missing = [n for n, r in ((p["date"], rd), (p["status"], rs)) if r.state == "MISSING"]
    if missing:
        return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "MISSING_FACT", f"Not supplied: {missing}", inputs)
    if rs.value != p["delivered_value"]:
        return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "STATUS_NOT_DELIVERED",
                   f"{p['status']}={rs.value!r}; the requirement names {p['delivered_value']!r}.", inputs)
    return _mk(req, EvidenceStatus.DEMONSTRATED, "DATE_AND_STATUS_PRESENT",
               "A delivery date and a 'delivered' status are both present.", inputs, corr=_corr(list(rd.items) + list(rs.items)))


def ev_address_granularity(case: Case, req: Dict[str, Any]) -> EvidenceAssessment:
    name = req["params"]["evidence"]
    r = resolve(case, name)
    if r.state != "VALUE":
        return _non_value(req, r, name, [name])
    have = norm_address(r.value)
    for group in req["params"]["min_granularity"]:
        if all(have.get(k) for k in group):
            return _mk(req, EvidenceStatus.DEMONSTRATED, "GRANULARITY_MET", f"Address carries {group}.", [name], corr=_corr(r.items))
    return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "ADDRESS_TOO_COARSE",
               f"Address fields present: {sorted(have)}; none of the named groups is complete.", [name])


def ev_address_matches(case: Case, req: Dict[str, Any]) -> EvidenceAssessment:
    name, fact = req["params"]["evidence"], req["params"]["fact"]
    inputs = [name, fact]
    r, td = resolve(case, name), _fact(case, fact)
    if r.state in ("CONFLICT", "REVIEW_ONLY"):
        return _non_value(req, r, name, inputs)
    missing = ([name] if r.state == "MISSING" else []) + ([fact] if td is None else [])
    if missing:
        return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "MISSING_FACT", f"Not supplied (or provenance unknown): {missing}", inputs)
    diffs = _address_diffs(r.value, td.value)
    if diffs:
        return _mk(req, EvidenceStatus.CONTRADICTED, "ADDRESS_MISMATCH",
                   f"Recipient address differs from the Transaction Details address in {diffs} after strict normalisation; "
                   "no fuzzy matching is applied, so this is flagged for human review.", inputs, True)
    return _mk(req, EvidenceStatus.DEMONSTRATED, "ADDRESS_MATCH",
               "Recipient address equals the Transaction Details address after strict normalisation.", inputs, corr=_corr(r.items))


def ev_ship_to_address(case: Case, req: Dict[str, Any]) -> EvidenceAssessment:
    p = req["params"]
    inputs = [p["assertion"], p["evidence"], p["fact"]]
    a, r, td = resolve(case, p["assertion"]), resolve(case, p["evidence"]), _fact(case, p["fact"])
    for n, x in ((p["assertion"], a), (p["evidence"], r)):
        if x.state == "CONFLICT":
            return _non_value(req, x, n, inputs)
    derived = None
    if r.state == "VALUE" and td is not None:
        derived = not _address_diffs(r.value, td.value)
    asserted = a.value if a.state == "VALUE" else None
    if asserted is False:
        return _mk(req, EvidenceStatus.CONTRADICTED, "ASSERTED_NOT_SHIPPED_TO_TRANSACTION_ADDRESS",
                   "The merchant states the item was not shipped to the Transaction Details address.", inputs, True)
    if derived is False:
        return _mk(req, EvidenceStatus.CONTRADICTED, "ADDRESS_MISMATCH",
                   "The recipient address differs from the Transaction Details address after strict normalisation; "
                   "flagged for human review.", inputs, True)
    if derived is True:
        return _mk(req, EvidenceStatus.DEMONSTRATED, "DERIVED_FROM_RECIPIENT_ADDRESS",
                   "Recipient address equals the Transaction Details address after strict normalisation.", inputs, corr=_corr(r.items))
    if asserted is True:
        return _mk(req, EvidenceStatus.DEMONSTRATED, "ASSERTED_ONLY",
                   "Merchant asserts shipment to the Transaction Details address; no comparable address exists to corroborate it.",
                   inputs, corr="MERCHANT_ASSERTED_ONLY")
    for n, x in ((p["assertion"], a), (p["evidence"], r)):
        if x.state == "REVIEW_ONLY":
            return _non_value(req, x, n, inputs)
    return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "MISSING_FACT",
               "No assertion and no comparable recipient address / Transaction Details address.", inputs)


def ev_negative_condition(case: Case, req: Dict[str, Any]) -> EvidenceAssessment:
    name = req["params"]["evidence"]
    r = resolve(case, name)
    if r.state != "VALUE":
        return _non_value(req, r, name, [name])
    if r.value is True:
        return _mk(req, EvidenceStatus.CONTRADICTED, "CONDITION_VIOLATED", f"{name} is True.", [name])
    return _mk(req, EvidenceStatus.DEMONSTRATED, "CONDITION_NOT_TRIGGERED", f"{name} is False as supplied.", [name], corr=_corr(r.items))


def ev_enum_in(case: Case, req: Dict[str, Any]) -> EvidenceAssessment:
    p = req["params"]
    r = resolve(case, p["evidence"])
    if r.state != "VALUE":
        return _non_value(req, r, p["evidence"], [p["evidence"]])
    if r.value in p["allowed"]:
        return _mk(req, EvidenceStatus.DEMONSTRATED, "VALUE_ALLOWED", f"{p['evidence']}={r.value}", [p["evidence"]], corr=_corr(r.items))
    if r.value in p["contradicted"]:
        return _mk(req, EvidenceStatus.CONTRADICTED, "CONDITION_VIOLATED", f"{p['evidence']}={r.value}", [p["evidence"]])
    return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "VALUE_UNKNOWN", f"{p['evidence']}={r.value}", [p["evidence"]])


def ev_conditional_enum(case: Case, req: Dict[str, Any]) -> EvidenceAssessment:
    p = req["params"]
    inputs = [p["flag"], p["evidence"]]
    flag = _fact(case, p["flag"])
    if flag is None:
        return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "MISSING_FACT",
                   f"{p['flag']} not supplied (or provenance unknown), so applicability is unknown.", inputs)
    if flag.value is False:
        return _mk(req, EvidenceStatus.NOT_APPLICABLE, "CONDITION_DOES_NOT_APPLY", f"{p['flag']} is False.", inputs)
    r = resolve(case, p["evidence"])
    if r.state != "VALUE":
        return _non_value(req, r, p["evidence"], inputs)
    if r.value == p["required"]:
        return _mk(req, EvidenceStatus.DEMONSTRATED, "VALUE_ALLOWED", f"{p['evidence']}={r.value}", inputs, corr=_corr(r.items))
    if r.value in p["contradicted"]:
        return _mk(req, EvidenceStatus.CONTRADICTED, "CONDITION_VIOLATED", f"{p['evidence']}={r.value}", inputs)
    return _mk(req, EvidenceStatus.NOT_DEMONSTRATED, "VALUE_UNKNOWN", f"{p['evidence']}={r.value}", inputs)


EVALUATORS: Dict[str, Callable[[Case, Dict[str, Any]], EvidenceAssessment]] = {
    "record_present": ev_record_present, "value_present": ev_value_present,
    "delivery_date_and_status": ev_delivery_date_and_status, "address_granularity": ev_address_granularity,
    "address_matches": ev_address_matches, "ship_to_address": ev_ship_to_address,
    "negative_condition": ev_negative_condition, "enum_in": ev_enum_in, "conditional_enum": ev_conditional_enum,
}


def open_timing(case: Case, o: Dict[str, Any]) -> Dict[str, Any]:
    """Reports whether the inputs for the timing requirement exist. It never compares the timestamps."""
    p = o["params"]
    notified, shipped = _fact(case, p["notification"]), resolve(case, p["shipment"])
    both = notified is not None and shipped.state == "VALUE"
    state = "UNKNOWN_CLOCK" if both else "TIMESTAMPS_MISSING"
    detail = ("Both timestamps are present, but the clock semantics are not established (calendar vs business days, "
              "which notification, which time zone). No comparison is made."
              if both else "The PayPal notification timestamp and/or the shipment timestamp were not supplied.")
    return {"open_id": o["open_id"], "kind": o["kind"], "state": state, "detail": detail,
            "passage_ids": list(o["passage_ids"]), "inputs_used": [p["notification"], p["shipment"]]}


OPEN_EVALUATORS = {"open_timing": open_timing}
ALL_EVALUATOR_NAMES = set(EVALUATORS) | set(OPEN_EVALUATORS)


# ---- gates ------------------------------------------------------------------------------------------
def _gate(g: Dict[str, Any], outcome: str, reason: str, detail: str, inputs: List[str], pids: Optional[List[str]] = None) -> GateResult:
    return GateResult(g["gate_id"], g["type"], outcome, reason, detail, tuple(pids or g["passage_ids"]),
                      tuple(inputs), bool(g.get("interpretation")), g.get("interpretation_note"))


def run_gate(g: Dict[str, Any], case: Case, open_items: List[Dict[str, Any]]) -> GateResult:
    t = g["type"]
    if t == "jurisdiction":
        f = _fact(case, g["fact"])
        if f is None:
            return _gate(g, ProtectionAssessment.UNKNOWN.value, "JURISDICTION_UNKNOWN",
                         "merchant_account_country was not supplied (or its provenance is unknown); the policy applies to US accounts only.", [g["fact"]])
        if f.value != g["expected"]:
            return _gate(g, ProtectionAssessment.UNSUPPORTED_JURISDICTION.value, "JURISDICTION_MISMATCH",
                         f"merchant_account_country={f.value!r}; this rule encodes the {g['expected']} policy only.", [g["fact"]])
        return _gate(g, "PASS", "JURISDICTION_MATCH", f"merchant_account_country={f.value!r} matches {g['expected']}.", [g["fact"]])
    if t == "route":
        route, funding = _fact(case, g["fact"]), _fact(case, g["funding_fact"])
        inputs = [g["fact"], g["funding_fact"]]
        if route is None:
            return _gate(g, ProtectionAssessment.UNKNOWN.value, "ROUTE_MISSING",
                         "route was not supplied (or its provenance is unknown).", inputs)
        allowed = g.get("funding_consistency", {}).get("allowed", {}).get(route.value)
        if allowed and funding is not None and funding.value != "UNKNOWN" and funding.value not in allowed:
            return _gate(g, ProtectionAssessment.UNKNOWN.value, "INCONSISTENT_ROUTE_FUNDING",
                         f"route={route.value} is inconsistent with funding_source={funding.value} (allowed: {allowed}).",
                         inputs, g["passage_ids"])
        action = g["actions"][route.value]
        funding_unknown = funding is None or funding.value == "UNKNOWN"
        if funding_unknown and allowed:
            open_items.append({"open_id": g["gate_id"] + ".funding_source_not_supplied", "kind": "UNKNOWN", "state": "UNKNOWN",
                               "detail": "funding_source is not supplied/unknown; the route's implied card funding is an inference and is "
                                         "recorded here instead of being assumed.", "passage_ids": list(g["passage_ids"]),
                               "inputs_used": inputs})
        if action["action"] == "NOT_COVERED":
            return _gate(g, ProtectionAssessment.NOT_COVERED.value, "ROUTE_EXCLUDED", action["note"], inputs, action["passage_ids"])
        if action["action"] == "UNKNOWN":
            return _gate(g, ProtectionAssessment.UNKNOWN.value, "ROUTE_NOT_ESTABLISHED_BY_POLICY", action["note"], inputs, action["passage_ids"])
        if action["action"] == "EVALUATE_WITH_OPEN_ITEM":
            oi = action["open_item"]
            open_items.append({"open_id": oi["id"], "kind": "UNKNOWN", "state": "UNKNOWN", "detail": oi["text"],
                               "passage_ids": list(action["passage_ids"]), "inputs_used": inputs})
        return _gate(g, "PASS", "ROUTE_EVALUATED", action["note"], inputs, action["passage_ids"])
    if t == "goods_scope":
        f = _fact(case, g["fact"])
        if f is None:
            return _gate(g, ProtectionAssessment.UNKNOWN.value, "GOODS_TYPE_UNKNOWN",
                         "physical_goods was not supplied (or its provenance is unknown).", [g["fact"]])
        if f.value is False:
            return _gate(g, ProtectionAssessment.UNKNOWN.value, "OUT_OF_PHASE1_SCOPE_INTANGIBLE", g["out_of_scope_note"], [g["fact"]])
        return _gate(g, "PASS", "PHYSICAL_GOODS", "physical_goods is True.", [g["fact"]])
    raise ValueError(f"unknown gate type {t}")


# ---- policy conditions on opaque PayPal values --------------------------------------------------------------
def eval_policy_condition(pc: Dict[str, Any], case: Case) -> Dict[str, Any]:
    """The PayPal value is observed and stored as an opaque token. It only satisfies/fails the policy condition if the rule
    carries a mapping established by primary documentation (never the case in Phase 1)."""
    raw = case.fact(pc["fact"])
    if raw is None:
        observation, value = "PAYPAL_STATUS_NOT_SUPPLIED", None
    elif _unknown_provenance(raw):
        observation, value = "PAYPAL_STATUS_PROVENANCE_UNKNOWN", None
    else:
        observation, value = "PAYPAL_STATUS_OBSERVED", raw.value
    m = pc["mapping"]
    if not m["established"]:
        state, mapping = "UNRESOLVED", "UNKNOWN"
    else:
        mapping = "ESTABLISHED"
        if value in m["satisfied_values"]:
            state = "SATISFIED"
        elif value in m["unsatisfied_values"]:
            state = "UNSATISFIED"
        else:
            state = "UNRESOLVED"
    return {"condition_id": pc["condition_id"], "kind": pc["kind"], "description": pc["description"],
            "observation": observation, "observed_value": value,
            "status_semantics": pc["status_semantics"], "POLICY_STATUS_MAPPING": mapping, "state": state,
            "passage_ids": list(pc["passage_ids"]), "mapping_note": m.get("note", "")}


# ---- SNAD exposure --------------------------------------------------------------------------------------
def snad_exposure(rule: Rule, case: Case) -> Dict[str, Any]:
    m = rule.raw["exposure_model"]
    amt, cur = _fact(case, m["floor_fact"]), _fact(case, "currency")
    floor = Decimal(amt.value) if amt is not None else None
    documented: List[Dict[str, Any]] = []
    unknown: List[Dict[str, Any]] = []
    additive = Decimal(0)
    for ct in m["documented_cost_types"]:
        f = _fact(case, ct["fact"])
        documented.append({"cost_id": ct["cost_id"], "condition": ct["condition"], "additive_to_floor": ct["additive_to_floor"],
                           "amount": f.value if f else None, "amount_status": "PROVIDED" if f else "AMOUNT_UNKNOWN",
                           "passage_ids": list(ct["passage_ids"]), "note": ct["note"]})
        if f is None:
            unknown.append({"cost_id": ct["cost_id"], "reason": "AMOUNT_UNKNOWN"})
        elif ct["additive_to_floor"] is True:
            additive += Decimal(f.value)
    if floor is None:
        unknown.append({"cost_id": "transaction_amount", "reason": "AMOUNT_UNKNOWN"})
    unknown.append({"cost_id": "other_costs_not_modeled", "reason": "NOT_BOUNDED_BY_SOURCES"})
    return {"currency": cur.value if cur else None,
            "exposure_floor": str(floor) if floor is not None else None,
            "floor_note": m["floor_note"], "floor_passage_ids": list(m["floor_passage_ids"]),
            "documented_additional_costs": documented, "unknown_additional_costs": unknown,
            "known_lower_bound": str(floor + additive) if floor is not None else None,
            "total_exposure": m["total_exposure"]}


# ---- assessment ----------------------------------------------------------------------------------------
def observed_inputs(case: Case) -> Dict[str, Any]:
    """Every key dimension is listed explicitly, including when it is NOT_SUPPLIED. Nothing is defaulted."""
    out: Dict[str, Any] = {}
    for n in OBSERVED_NAMES:
        raw = case.fact(n)
        if raw is None:
            out[n] = {"state": "NOT_SUPPLIED", "value": None}
        elif _unknown_provenance(raw):
            out[n] = {"state": "PROVENANCE_UNKNOWN", "value": None}
        else:
            out[n] = {"state": "SUPPLIED", "value": raw.value}
        if n == "paypal_seller_protection_status":
            out[n]["status_semantics"] = "UNKNOWN"
    return out


def _finish(case: Case, rule: Optional[Rule], pa: ProtectionAssessment, efa: EvidenceFieldsAssessment, reasons: List[str],
            gates: List[GateResult], conditions: List[Dict[str, Any]], exclusions: List[Dict[str, Any]],
            checks: List[EvidenceAssessment], open_items: List[Dict[str, Any]], exposure: Optional[Dict[str, Any]],
            explanation: List[str]) -> Assessment:
    rule_info = None
    if rule is not None:
        rule_info = {"rule_id": rule.rule_id, "version": rule.version, "status": rule.status,
                     "jurisdiction": rule.jurisdiction, "file_sha256": rule.file_sha256,
                     "sources": [s.to_dict() for s in rule.sources],
                     "policy_effect": rule.raw["policy_effect"], "eligibility_determination": rule.raw["eligibility_determination"]}
    timing = next((o["state"] for o in open_items if o["open_id"].endswith("timing_requirement")), None)
    review = any(c.needs_human_review for c in checks) or any(e.get("needs_human_review") for e in exclusions)
    uncorroborated = tuple(c.check_id for c in checks
                           if c.status == EvidenceStatus.DEMONSTRATED and c.corroboration == "MERCHANT_ASSERTED_ONLY")
    status = rule.status if rule is not None else "NO_RULE_SELECTED"
    notice = UNREVIEWED_NOTICE if status in ("UNREVIEWED", "NO_RULE_SELECTED") else (
        "Rule is marked REVIEWED internally; this is still not a PayPal determination.")
    expl = [f"policy_status={status}. {notice}"] + list(explanation)
    a = Assessment(case.case_id, status, notice, rule_info, pa, efa, PAYPAL_ACCEPTANCE_NOT_ESTABLISHED,
                   tuple(dict.fromkeys(reasons)), observed_inputs(case), tuple(gates), tuple(conditions), tuple(exclusions),
                   tuple(checks), uncorroborated, tuple(open_items), tuple(rule.raw["not_modeled"]) if rule else (),
                   tuple(u.to_dict() for u in rule.unknowns()) if rule else (), review, timing, exposure, tuple(expl))
    digest = sha256_hex(canonical({"case": case.snapshot(), "assessment": a.core_dict()}))
    return Assessment(**{**a.__dict__, "digest": digest})


def assess(registry: PolicyRegistry, case: Case) -> Assessment:
    NE = EvidenceFieldsAssessment.NOT_EVALUATED
    cat = _fact(case, "claim_category")
    if cat is None:
        return _finish(case, None, ProtectionAssessment.UNKNOWN, NE, ["CLAIM_CATEGORY_MISSING"], [], [], [], [], [], None,
                       ["No claim_category was supplied (or its provenance is unknown), so no policy rule can be selected -> UNKNOWN."])
    rule = registry.rule_for(cat.value)
    if rule is None:
        return _finish(case, None, ProtectionAssessment.UNKNOWN, NE, ["NO_RULE_FOR_CATEGORY"], [], [], [], [], [], None,
                       [f"No rule is registered for {cat.value} -> UNKNOWN."])
    d = rule.raw
    gates: List[GateResult] = []
    conditions: List[Dict[str, Any]] = []
    open_items: List[Dict[str, Any]] = []
    exclusions: List[Dict[str, Any]] = []
    expl: List[str] = [f"Rule {rule.rule_id} v{rule.version} [{rule.status}], jurisdiction {rule.jurisdiction}; "
                       f"policy_effect={d['policy_effect']['value']}, eligibility_determination={d['eligibility_determination']['value']}."]

    def tag(pids) -> str:
        return " [" + ", ".join(pids) + "]" if pids else ""

    for g in d["gates"]:
        r = run_gate(g, case, open_items)
        gates.append(r)
        expl.append(f"Gate {r.gate_id}: {r.outcome} ({r.reason_code}). {r.detail}{tag(r.passage_ids)}"
                    + (" (interpretation)" if r.interpretation else ""))
        if r.terminal:
            expl.append(f"Result: {r.outcome} - assessment stopped at gate {r.gate_id}.")
            return _finish(case, rule, ProtectionAssessment(r.outcome), NE, [r.reason_code], gates, conditions, exclusions, [],
                           open_items, None, expl)

    if d["mode"] == "NOT_COVERED":
        x = d["exclusions"][0]
        exposure = snad_exposure(rule, case)
        exclusions.append({"exclusion_id": x["exclusion_id"], "state": "TRIGGERED", "reason_code": "CATEGORY_EXCLUDED",
                           "passage_ids": list(x["passage_ids"]), "needs_human_review": False})
        expl.append(f"Exclusion {x['exclusion_id']}: TRIGGERED. {x['note']}{tag(x['passage_ids'])}")
        expl.append("Result: NOT_COVERED. No protection calculation, requirement check or probability is run.")
        expl.append(f"Exposure: floor={exposure['exposure_floor']} {exposure['currency'] or ''}; known lower bound="
                    f"{exposure['known_lower_bound']}; total exposure={exposure['total_exposure']}. "
                    f"{len(exposure['unknown_additional_costs'])} cost item(s) have unknown amounts.")
        return _finish(case, rule, ProtectionAssessment.NOT_COVERED, NE, ["CATEGORY_EXCLUDED"], gates, conditions, exclusions, [],
                       open_items, exposure, expl)

    unresolved: List[str] = []
    for pc in d["policy_conditions"]:
        c = eval_policy_condition(pc, case)
        conditions.append(c)
        expl.append(f"Policy condition {c['condition_id']}: {c['state']}. {c['observation']}"
                    + (f" ({c['observed_value']!r})" if c["observed_value"] is not None else "")
                    + f"; status_semantics={c['status_semantics']}; POLICY_STATUS_MAPPING={c['POLICY_STATUS_MAPPING']}. "
                    + f"The PayPal value is stored as an opaque token and does not satisfy or fail the policy condition.{tag(c['passage_ids'])}"
                    if c["state"] == "UNRESOLVED" else
                    f"Policy condition {c['condition_id']}: {c['state']} via a mapping established by primary documentation.{tag(c['passage_ids'])}")
        if c["state"] == "UNSATISFIED":
            expl.append("Result: NOT_COVERED - the policy condition is unsatisfied under an established mapping.")
            return _finish(case, rule, ProtectionAssessment.NOT_COVERED, NE, ["POLICY_CONDITION_UNSATISFIED"], gates, conditions,
                           exclusions, [], open_items, None, expl)
        if c["state"] == "UNRESOLVED":
            unresolved.append("POLICY_STATUS_MAPPING_UNKNOWN")
            if c["observation"] != "PAYPAL_STATUS_OBSERVED":
                unresolved.append("PAYPAL_STATUS_MISSING")

    for x in d["exclusions"]:
        res = resolve(case, x["evidence"])
        if res.state == "VALUE" and res.value == x["triggered_when"]:
            exclusions.append({"exclusion_id": x["exclusion_id"], "state": "TRIGGERED", "reason_code": "EXCLUSION_TRIGGERED",
                               "passage_ids": list(x["passage_ids"]), "needs_human_review": False})
            expl.append(f"Exclusion {x['exclusion_id']}: TRIGGERED ({x['evidence']}={res.value}).{tag(x['passage_ids'])}")
            expl.append("Result: NOT_COVERED - a listed exclusion applies.")
            return _finish(case, rule, ProtectionAssessment.NOT_COVERED, NE, ["EXCLUSION_TRIGGERED"], gates, conditions,
                           exclusions, [], open_items, None, expl)
        state = {"VALUE": "CLEARED", "MISSING": "NOT_EVALUATED", "REVIEW_ONLY": "NOT_EVALUATED", "CONFLICT": "NOT_EVALUATED"}[res.state]
        reason = {"VALUE": "EXCLUSION_NOT_TRIGGERED", "MISSING": "MISSING_FACT", "REVIEW_ONLY": res.reason or "ONLY_UNREVIEWED_EXTRACTION",
                  "CONFLICT": "CONFLICTING_EVIDENCE"}[res.state]
        exclusions.append({"exclusion_id": x["exclusion_id"], "state": state, "reason_code": reason,
                           "passage_ids": list(x["passage_ids"]), "needs_human_review": res.state in ("REVIEW_ONLY", "CONFLICT")})
        expl.append(f"Exclusion {x['exclusion_id']}: {state} ({reason}).{tag(x['passage_ids'])}")
        if state == "NOT_EVALUATED":
            unresolved.append("UNRESOLVED_EXCLUSION")   

    checks: List[EvidenceAssessment] = []
    for c in d["checks"]:
        r = EVALUATORS[c["evaluator"]](case, c)
        checks.append(r)
        expl.append(f"Requirement {r.check_id} [{r.kind}]: {r.status.value} ({r.reason_code}). {r.detail}{tag(r.passage_ids)}"
                    + (f" Establishes: {r.establishes}. Corroboration: {r.corroboration}. PayPal acceptance: {r.paypal_acceptance}."
                       if r.status == EvidenceStatus.DEMONSTRATED else "")
                    + (" (interpretation)" if r.interpretation else ""))
    for o in d["open_requirements"]:
        oi = OPEN_EVALUATORS[o["evaluator"]](case, o)
        open_items.append(oi)
        expl.append(f"Open requirement {oi['open_id']}: {oi['state']}. {oi['detail']}{tag(oi['passage_ids'])}")

    blocking = [c for c in checks if c.status not in NON_BLOCKING]
    efa = (EvidenceFieldsAssessment.REQUIREMENT_FIELDS_NOT_DEMONSTRATED if blocking
           else EvidenceFieldsAssessment.REQUIREMENT_FIELDS_DEMONSTRATED)
    if blocking:
        pa, reasons = ProtectionAssessment.REQUIREMENTS_NOT_DEMONSTRATED, [c.reason_code for c in blocking]
        expl.append(f"Result: REQUIREMENTS_NOT_DEMONSTRATED - {len(blocking)} modeled requirement(s) not demonstrated: "
                    + ", ".join(f"{c.check_id} ({c.status.value}/{c.reason_code})" for c in blocking) + ".")
    elif unresolved:
        pa, reasons = ProtectionAssessment.UNKNOWN, unresolved
        expl.append("Result: UNKNOWN - the requirement fields are demonstrated, but the overall assessment cannot be resolved: "
                    + ", ".join(dict.fromkeys(unresolved)) + ". Unknowns are never defaulted into a pass.")
    else:
        pa, reasons = ProtectionAssessment.REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES, ["MODELED_REQUIREMENTS_DEMONSTRATED"]
        expl.append("Result: REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES - the fields of every modeled requirement are demonstrated. "
                    "This is not a finding that PayPal accepts the artifacts as sufficient proof, and PayPal determines "
                    "eligibility in its sole discretion [SP.discretion].")
    expl.append(f"evidence_fields_assessment={efa.value}; paypal_acceptance={PAYPAL_ACCEPTANCE_NOT_ESTABLISHED}.")
    expl.append(f"Not evaluated: {len(open_items)} open item(s), {len(d['not_modeled'])} not-modeled item(s), "
                f"{len(d['unknowns'])} unknown(s). See `open_items`, `not_modeled`, `unknowns`.")
    return _finish(case, rule, pa, efa, reasons, gates, conditions, exclusions, checks, open_items, None, expl)


# ---- counterfactuals -------------------------------------------------------------------------------------
def facts_view(case: Case) -> Dict[str, Any]:
    """CURRENT_FACTS / COUNTERFACTUAL_FACTS: transaction facts and evidence, with provenance, keyed by layer and name."""
    v: Dict[str, List[Dict[str, Any]]] = {}
    for f in case.transaction_facts:
        v.setdefault(f"TRANSACTION_FACT:{f.name}", []).append(
            {"value": f.value, "source_type": f.provenance.source_type.value, "provenance_status": f.provenance.status.value})
    for e in case.evidence:
        v.setdefault(f"EVIDENCE:{e.name}", []).append(
            {"value": e.value, "source_type": e.provenance.source_type.value, "provenance_status": e.provenance.status.value})
    return {k: sorted(x, key=canonical) for k, x in sorted(v.items())}


@dataclass(frozen=True)
class CounterfactualReport:
    label: str
    changes_applied: Tuple[str, ...]
    current_facts: Dict[str, Any]
    counterfactual_facts: Dict[str, Any]
    changed_facts: Tuple[Dict[str, Any], ...]
    current: Assessment
    counterfactual: Assessment
    changed_gates: Tuple[Dict[str, Any], ...]
    changed_conditions: Tuple[Dict[str, Any], ...]
    changed_requirements: Tuple[Dict[str, Any], ...]
    result_change: Dict[str, Any]
    still_blocking: Tuple[str, ...]
    explanation: Tuple[str, ...]

    @property
    def result_changed(self) -> bool:
        return self.result_change["changed"]

    def to_dict(self) -> Dict[str, Any]:
        return {"label": self.label, "changes_applied": list(self.changes_applied),
                "CURRENT_FACTS": self.current_facts, "COUNTERFACTUAL_FACTS": self.counterfactual_facts,
                "changed_facts": list(self.changed_facts), "CHANGED_REQUIREMENTS": list(self.changed_requirements),
                "changed_gates": list(self.changed_gates), "changed_conditions": list(self.changed_conditions),
                "RESULT_CHANGE": self.result_change, "still_blocking": list(self.still_blocking),
                "explanation": list(self.explanation),
                "current_digest": self.current.digest, "counterfactual_digest": self.counterfactual.digest}


def counterfactual(registry: PolicyRegistry, case: Case, changes: Changes) -> CounterfactualReport:
    """Re-run the SAME rules on a modified copy of the case. Policy rules cannot be changed from here.
    Reports CURRENT_FACTS, COUNTERFACTUAL_FACTS, the policy requirements whose assessment changed, and the result change."""
    cf_case = case.with_changes(changes.set_facts, changes.remove_facts, changes.set_evidence, changes.remove_evidence)
    before, after = assess(registry, case), assess(registry, cf_case)
    fb, fa = facts_view(case), facts_view(cf_case)
    changed_facts = [{"key": k, "before": fb.get(k), "after": fa.get(k)} for k in dict.fromkeys(list(fb) + list(fa)) if fb.get(k) != fa.get(k)]
    desc = {}
    for a in (before, after):
        if a.rule:
            for c in registry.rules[a.rule["rule_id"]].raw["checks"]:
                desc[c["check_id"]] = (c["kind"], c["description"])

    def gmap(a: Assessment):
        return {g.gate_id: (g.outcome, g.reason_code, g.passage_ids) for g in a.gates}

    def cmap(a: Assessment):
        return {c.check_id: (c.status.value, c.reason_code, c.passage_ids) for c in a.checks}

    def pmap(a: Assessment):
        return {c["condition_id"]: (c["state"], c["observation"], tuple(c["passage_ids"])) for c in a.policy_conditions}

    gb, ga, cb, ca, pb, pa_ = gmap(before), gmap(after), cmap(before), cmap(after), pmap(before), pmap(after)
    ne = ("NOT_EVALUATED", None, ())
    changed_gates = [{"gate_id": k, "before": gb.get(k, ne)[:2], "after": ga.get(k, ne)[:2], "passage_ids": list(ga.get(k, gb.get(k))[2])}
                     for k in dict.fromkeys(list(gb) + list(ga)) if gb.get(k, ne)[:2] != ga.get(k, ne)[:2]]
    changed_conditions = [{"condition_id": k, "before": pb.get(k, ne)[:2], "after": pa_.get(k, ne)[:2]}
                          for k in dict.fromkeys(list(pb) + list(pa_)) if pb.get(k, ne)[:2] != pa_.get(k, ne)[:2]]
    changed_reqs = [{"check_id": k, "kind": desc.get(k, ("", ""))[0], "requirement": desc.get(k, ("", ""))[1],
                     "before": cb.get(k, ne)[:2], "after": ca.get(k, ne)[:2], "passage_ids": list(ca.get(k, cb.get(k))[2])}
                    for k in dict.fromkeys(list(cb) + list(ca)) if cb.get(k, ne)[:2] != ca.get(k, ne)[:2]]
    still = tuple(f"{c.check_id} ({c.status.value}/{c.reason_code})" for c in after.blocking())
    rc = {"protection_assessment": {"before": before.protection_assessment.value, "after": after.protection_assessment.value},
          "evidence_fields_assessment": {"before": before.evidence_fields_assessment.value, "after": after.evidence_fields_assessment.value},
          "reason_codes": {"before": list(before.reason_codes), "after": list(after.reason_codes)},
          "changed": before.protection_assessment != after.protection_assessment}
    rc["evidence_fields_changed"] = rc["evidence_fields_assessment"]["before"] != rc["evidence_fields_assessment"]["after"]
    ex = [f"COUNTERFACTUAL '{changes.label}': " + ("; ".join(changes.describe()) or "no edits") + "."]
    ex.append("CHANGED FACTS: " + (", ".join(f["key"] for f in changed_facts) if changed_facts else "none") + ".")
    if changed_gates:
        for g in changed_gates:
            ex.append(f"CHANGED GATE {g['gate_id']}: {g['before'][0]} ({g['before'][1]}) -> {g['after'][0]} ({g['after'][1]}) [{', '.join(g['passage_ids'])}]")
    if changed_conditions:
        for c in changed_conditions:
            ex.append(f"CHANGED POLICY CONDITION {c['condition_id']}: {c['before'][0]} ({c['before'][1]}) -> {c['after'][0]} ({c['after'][1]})")
    if changed_reqs:
        for c in changed_reqs:
            ex.append(f"CHANGED REQUIREMENT - policy requirement {c['check_id']} [{c['kind']}] \"{c['requirement']}\": "
                      f"{c['before'][0]} ({c['before'][1]}) -> {c['after'][0]} ({c['after'][1]}) [{', '.join(c['passage_ids'])}]")
    else:
        ex.append("CHANGED REQUIREMENTS: none. No policy requirement changed its assessment.")
    pb_, pa2 = rc["protection_assessment"]["before"], rc["protection_assessment"]["after"]
    ex.append(f"RESULT CHANGE: protection_assessment {pb_} -> {pa2}" + ("" if rc["changed"] else " (unchanged)")
              + f"; evidence_fields_assessment {rc['evidence_fields_assessment']['before']} -> {rc['evidence_fields_assessment']['after']}"
              + ("" if rc["evidence_fields_changed"] else " (unchanged)") + ".")
    ex.append("STILL BLOCKING after the change: " + (", ".join(still) if still else "none") + ".")
    if after.protection_assessment == ProtectionAssessment.UNKNOWN and after.reason_codes:
        ex.append("STILL UNRESOLVED after the change: " + ", ".join(after.reason_codes) + ".")
    ex.append("UNCHANGED BY ANY COUNTERFACTUAL: PayPal determines eligibility in its sole discretion [SP.discretion]; PayPal acceptance of any "
              "artifact is NOT_ESTABLISHED; open items, not-modeled items and unknowns remain; policy_status stays "
              f"{after.policy_status}.")
    return CounterfactualReport(changes.label, tuple(changes.describe()), fb, fa, tuple(changed_facts), before, after,
                                tuple(changed_gates), tuple(changed_conditions), tuple(changed_reqs), rc, still, tuple(ex))


def default_registry() -> PolicyRegistry:
    return PolicyRegistry(evaluator_names=ALL_EVALUATOR_NAMES)
