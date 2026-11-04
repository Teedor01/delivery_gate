from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from delivery_gate.models import Case, Provenance, ProvStatus, SourceType, TransactionFact
from .adapter import CaptureObservation, Observation, observe_order
from . import disputes as dmod
from .disputes import DisputeObservation
from .inventory import INVENTORY, Handoff

HANDOFF_PLAN: Tuple[Tuple[str, str], ...] = (
    ("paypal_seller_protection_status", "seller_protection.status"),
    ("currency", "amount.currency_code"),
)
DISPUTE_HANDOFF_PLAN: Tuple[Tuple[str, str], ...] = (
    ("claim_category", "reason"),
    ("route", "dispute_channel"),
)
ALLOWED_FACTS = frozenset(f for f, _ in HANDOFF_PLAN + DISPUTE_HANDOFF_PLAN)
WITHHELD_LOCAL_PATHS = {
    "unit.shipping.address": ("transaction_details_address", "MAPPING_NOT_ESTABLISHED_BY_PRIMARY_DOCUMENTATION"),
    "order.payment_source.types": ("funding_source", "MAPPING_NOT_ESTABLISHED_BY_PRIMARY_DOCUMENTATION"),
    "seller_receivable_breakdown.paypal_fee.value": ("paypal_fee_amount", "MAPPING_NOT_ESTABLISHED_BY_PRIMARY_DOCUMENTATION"),
    "seller_receivable_breakdown.paypal_fee.currency_code": ("paypal_fee_amount", "MAPPING_NOT_ESTABLISHED_BY_PRIMARY_DOCUMENTATION"),
    "amount.value": ("transaction_amount", "ENGINE_TREATS_AMOUNT_AS_AN_EXPOSURE_BOUND_BUT_DISPUTED_AMOUNT_MAY_BE_LOWER"),
}
_INVENTORY_PATH = {"unit.shipping.address": "purchase_units[].shipping.address.*",
                   "order.payment_source.types": "order.payment_source.<type>",
                   "seller_receivable_breakdown.paypal_fee.value": "capture.seller_receivable_breakdown.paypal_fee",
                   "seller_receivable_breakdown.paypal_fee.currency_code": "capture.seller_receivable_breakdown.paypal_fee",
                   "amount.value": "capture.amount.value"}


@dataclass(frozen=True)
class HandoffResult:
    case: Case
    handed_off: Tuple[Dict[str, Any], ...]
    withheld: Tuple[Dict[str, Any], ...]
    observation_only: Tuple[Dict[str, Any], ...]
    absent: Tuple[Dict[str, Any], ...]
    cautions: Tuple[str, ...]
    anomalies: Tuple[Dict[str, Any], ...]
    linkage: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {"case": self.case.snapshot(), "handed_off": list(self.handed_off), "withheld": list(self.withheld),
                "observation_only": list(self.observation_only), "absent": list(self.absent), "cautions": list(self.cautions),
                "anomalies": list(self.anomalies), "linkage": self.linkage}


def _provenance(o: Observation) -> Provenance:
    return Provenance(SourceType.PAYPAL_API, o.observation_id, ProvStatus.SYSTEM_RECORD, None, o.observed_at)


def _note_for(local: str) -> str:
    want = _INVENTORY_PATH.get(local)
    return next((f.note for f in INVENTORY if f.path == want), "")


def merchant_jurisdiction_fact(country: Optional[str], *, source_ref: str) -> Optional[TransactionFact]:
    """Jurisdiction is merchant-asserted unless an independently verified PayPal account source is established (none is, yet). No value, no fact."""
    if not isinstance(country, str) or not country.strip():
        return None
    return TransactionFact("merchant_account_country", country.strip(), Provenance(SourceType.MERCHANT_INPUT, source_ref, ProvStatus.MERCHANT_ASSERTED))


def _hand(plan, find, facts: List[TransactionFact], handed: List[Dict[str, Any]]) -> None:
    for fact_name, local in plan:
        o = find(local)
        if o is None or o.normalized_value is None:
            continue                                         # missing stays missing: no default, no fallback
        facts.append(TransactionFact(fact_name, o.normalized_value, _provenance(o)))
        handed.append({"fact": fact_name, "value": o.normalized_value, "observation_id": o.observation_id, "field_path": o.field_path,
                       "raw_value": o.raw_value, "doc_ref": o.doc_ref, "semantics": o.semantics, "enum_state": o.enum_state,
                       "normalization": o.normalization, "api_semantics_ref": o.api_semantics_ref})


def to_case(cap: CaptureObservation, *, case_id: Optional[str] = None, dispute: Optional[DisputeObservation] = None,
            merchant_country: Optional[TransactionFact] = None) -> HandoffResult:
    facts: List[TransactionFact] = []
    handed: List[Dict[str, Any]] = []
    cautions: List[str] = []
    _hand(HANDOFF_PLAN, cap.find, facts, handed)
    linkage: Optional[Dict[str, Any]] = None
    anomalies = [a.to_dict() for a in cap.anomalies]
    absent = [{**a.to_dict(), "handoff": "NOTHING_DEFAULTED"} for a in cap.absent]
    withheld = [{"observation_id": o.observation_id, "field_path": o.field_path, "would_feed": WITHHELD_LOCAL_PATHS[o.local_path][0],
                 "reason": WITHHELD_LOCAL_PATHS[o.local_path][1], "note": _note_for(o.local_path)}
                for o in cap.observations if o.local_path in WITHHELD_LOCAL_PATHS]
    used = {h["observation_id"] for h in handed}
    only = [{"observation_id": o.observation_id, "field_path": o.field_path, "reason": "NO_ENGINE_CONSUMER"}
            for o in cap.observations if o.observation_id not in used and o.local_path not in WITHHELD_LOCAL_PATHS]
    if dispute is not None:
        linked = dmod.is_linked(cap.capture_id, dispute)
        linkage = {"capture_id": cap.capture_id, "dispute_id": dispute.dispute_id, "linked": linked,
                   "basis": "IDENTIFIER_EQUALITY_ONLY: PayPal's docs do not state that a capture id and seller_transaction_id share a namespace"}
        anomalies += [a.to_dict() for a in dispute.anomalies]
        absent += [{**a.to_dict(), "handoff": "NOTHING_DEFAULTED"} for a in dispute.absent]
        if linked:
            before = len(handed)
            _hand(DISPUTE_HANDOFF_PLAN, dispute.find, facts, handed)
            used |= {h["observation_id"] for h in handed[before:]}
            only += [{"observation_id": o.observation_id, "field_path": o.field_path, "reason": "NO_ENGINE_CONSUMER"}
                     for o in dispute.observations if o.observation_id not in used]
            for fact_name, local in DISPUTE_HANDOFF_PLAN:
                o = dispute.find(local)
                if o is not None and o.normalized_value is None and o.raw_value is not None:
                    cautions.append(f"dispute {local} {o.raw_value!r} was observed but not normalised ({o.normalization}); {fact_name} stays unknown")
        else:
            withheld += [{"observation_id": o.observation_id, "field_path": o.field_path, "would_feed": "claim_category/route",
                          "reason": "DISPUTE_NOT_LINKED_TO_CAPTURE", "note": ""} for o in dispute.observations if o.local_path in ("reason", "dispute_channel")]
            cautions.append(f"dispute {dispute.dispute_id} does not list capture {cap.capture_id}; none of its facts were handed over")
    if merchant_country is not None:
        facts.append(merchant_country)
        handed.append({"fact": "merchant_account_country", "value": merchant_country.value, "observation_id": merchant_country.provenance.source_ref,
                       "field_path": None, "raw_value": merchant_country.value, "doc_ref": None, "semantics": "MERCHANT_ASSERTED",
                       "enum_state": None, "normalization": "NONE", "api_semantics_ref": None})
    st = cap.find("status")
    if st is not None and st.raw_value != "COMPLETED":
        cautions.append(f"capture status is {st.raw_value!r}; refund/pending states are not reflected anywhere in the engine")
    sp = cap.find("seller_protection.status")
    if sp is not None and sp.enum_state == "UNDOCUMENTED_TOKEN":
        cautions.append(f"seller_protection.status {sp.raw_value!r} is not a documented token; passed through verbatim as an opaque value")
    return HandoffResult(Case(case_id or f"paypal-{cap.capture_id}", tuple(facts)), tuple(handed), tuple(withheld), tuple(only),
                         tuple(absent), tuple(cautions), tuple(anomalies), linkage)


class PayPalFixtureSource:
    """TransactionDataSource over fixtures/paypal/<ref>.json ({"_fixture": {...}, "response": {...}, "observed_at": null}).
    Fixtures are hand-written from documented response shapes and are labelled origin=FIXTURE everywhere. There is NO live-sandbox source yet."""
    def __init__(self, fixture_dir: Path):
        self.dir = Path(fixture_dir)

    def load_wrapper(self, ref: str) -> Dict[str, Any]:
        return json.loads((self.dir / f"{ref}.json").read_text())

    def load_case(self, ref: str) -> Case:
        w = self.load_wrapper(ref)
        order = observe_order(w["response"], origin="FIXTURE", observed_at=w.get("observed_at"))
        return to_case(order.select_capture()).case
