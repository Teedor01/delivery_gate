from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Tuple


class Layer(str, Enum):
    POLICY_REQUIREMENT = "POLICY_REQUIREMENT"
    TRANSACTION_FACT = "TRANSACTION_FACT"
    EVIDENCE_ASSESSMENT = "EVIDENCE_ASSESSMENT"
    PROTECTION_ASSESSMENT = "PROTECTION_ASSESSMENT"
    UNKNOWN = "UNKNOWN"


class ClaimCategory(str, Enum):
    ITEM_NOT_RECEIVED = "ITEM_NOT_RECEIVED"
    UNAUTHORIZED_TRANSACTION = "UNAUTHORIZED_TRANSACTION"
    SIGNIFICANTLY_NOT_AS_DESCRIBED = "SIGNIFICANTLY_NOT_AS_DESCRIBED"


class Route(str, Enum):
    PAYPAL_DISPUTE = "PAYPAL_DISPUTE"
    CARD_ISSUER_CHARGEBACK = "CARD_ISSUER_CHARGEBACK"
    OTHER_UNKNOWN = "OTHER_UNKNOWN"


class FundingSource(str, Enum):
    CARD = "CARD"
    BANK = "BANK"
    PAYPAL_BALANCE = "PAYPAL_BALANCE"
    UNKNOWN = "UNKNOWN"


class ProtectionAssessment(str, Enum):
    """Allowed protection outputs. There is deliberately no 'protected' member."""
    NOT_COVERED = "NOT_COVERED"
    REQUIREMENTS_NOT_DEMONSTRATED = "REQUIREMENTS_NOT_DEMONSTRATED"
    REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES = "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES"
    UNSUPPORTED_JURISDICTION = "UNSUPPORTED_JURISDICTION"
    UNKNOWN = "UNKNOWN"


class EvidenceStatus(str, Enum):
    DEMONSTRATED = "DEMONSTRATED"
    NOT_DEMONSTRATED = "NOT_DEMONSTRATED"
    CONTRADICTED = "CONTRADICTED"
    NEEDS_HUMAN_REVIEW = "NEEDS_HUMAN_REVIEW"
    NOT_APPLICABLE = "NOT_APPLICABLE"


NON_BLOCKING = {EvidenceStatus.DEMONSTRATED, EvidenceStatus.NOT_APPLICABLE}


class EvidenceFieldsAssessment(str, Enum):
    """What the system itself can establish about the supplied artifacts: that the FIELDS a policy requirement
    names are present / consistent. It is never a statement that PayPal accepts the artifact as sufficient proof."""
    REQUIREMENT_FIELDS_DEMONSTRATED = "REQUIREMENT_FIELDS_DEMONSTRATED"
    REQUIREMENT_FIELDS_NOT_DEMONSTRATED = "REQUIREMENT_FIELDS_NOT_DEMONSTRATED"
    NOT_EVALUATED = "NOT_EVALUATED"


PAYPAL_ACCEPTANCE_NOT_ESTABLISHED = "NOT_ESTABLISHED"
NOT_ESTABLISHED_CLAIM = "PAYPAL_ACCEPTS_THIS_ARTIFACT_AS_SUFFICIENT_PROOF"


class SourceType(str, Enum):
    PAYPAL_API = "PAYPAL_API"
    MERCHANT_INPUT = "MERCHANT_INPUT"
    CARRIER_DOCUMENT = "CARRIER_DOCUMENT"
    CARRIER_API = "CARRIER_API"
    MERCHANT_STATEMENT = "MERCHANT_STATEMENT"
    EXTRACTED_FROM_TEXT = "EXTRACTED_FROM_TEXT"
    SYSTEM_DERIVED = "SYSTEM_DERIVED"
    UNKNOWN = "UNKNOWN"


class ProvStatus(str, Enum):
    SYSTEM_RECORD = "SYSTEM_RECORD"
    HUMAN_CONFIRMED = "HUMAN_CONFIRMED"
    MERCHANT_ASSERTED = "MERCHANT_ASSERTED"
    EXTRACTED_UNREVIEWED = "EXTRACTED_UNREVIEWED"
    UNKNOWN = "UNKNOWN"


# ---- names -------------------------------------------------------------------------------------
TRANSACTION_FACT_NAMES = frozenset({
    "merchant_account_country", "claim_category", "route", "funding_source",
    "transaction_amount", "currency", "physical_goods", "transaction_details_address",
    "pre_order_or_made_to_order", "paypal_seller_protection_status",
    "paypal_notification_timestamp",
    "paypal_fee_amount", "return_shipping_cost", "dispute_fee_amount",
})
EVIDENCE_NAMES = frozenset({
    "delivery_record", "shipment_record", "tracking_number", "delivery_date", "shipment_date",
    "delivered_status", "recipient_address", "shipped_to_transaction_address",
    "redirect_detected", "response_to_paypal", "shipment_timing", "shipment_timestamp",
    "shipped_after_advised_not_to_release",
})
BOOL_NAMES = frozenset({"physical_goods", "pre_order_or_made_to_order", "delivery_record",
                        "shipment_record", "shipped_to_transaction_address", "redirect_detected",
                        "shipped_after_advised_not_to_release"})
MONEY_NAMES = frozenset({"transaction_amount", "paypal_fee_amount", "return_shipping_cost",
                         "dispute_fee_amount"})
DATE_NAMES = frozenset({"delivery_date", "shipment_date"})
ADDRESS_NAMES = frozenset({"transaction_details_address", "recipient_address"})
ENUMS = {
    "claim_category": {c.value for c in ClaimCategory},
    "route": {r.value for r in Route},
    "funding_source": {f.value for f in FundingSource},
    "delivered_status": {"DELIVERED", "IN_TRANSIT", "RETURNED", "UNDELIVERABLE", "UNKNOWN"},
    "response_to_paypal": {"NO_REQUEST_OUTSTANDING", "RESPONDED_WITHIN_REQUESTED_TIME",
                           "RESPONSE_LATE_OR_MISSING", "UNKNOWN"},
    "shipment_timing": {"WITHIN_LISTED_TIMEFRAME", "OUTSIDE_LISTED_TIMEFRAME", "UNKNOWN"},
}
ADDRESS_KEYS = ("line1", "line2", "city", "region", "postal_code", "country")


def norm_text(s: Any) -> str:
    s = unicodedata.normalize("NFKC", str(s)).casefold()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_address(a: Dict[str, Any]) -> Dict[str, str]:
    return {k: norm_text(a[k]) for k in ADDRESS_KEYS if a.get(k) not in (None, "")}


def _validate_value(name: str, value: Any) -> Any:
    """Validate and canonicalise a value for a known name. Returns a JSON-safe canonical value."""
    if name in BOOL_NAMES:
        if not isinstance(value, bool):
            raise ValueError(f"{name} must be a bool")
        return value
    if name in MONEY_NAMES:
        try:
            d = Decimal(str(value))
        except InvalidOperation as e:
            raise ValueError(f"{name} must be a decimal amount") from e
        if d < 0:
            raise ValueError(f"{name} must not be negative")
        return str(d)
    if name in DATE_NAMES:
        date.fromisoformat(str(value))  
        return str(value)
    if name in ADDRESS_NAMES:
        if not isinstance(value, dict) or not set(value) <= set(ADDRESS_KEYS):
            raise ValueError(f"{name} must be a dict with keys from {ADDRESS_KEYS}")
        return {k: value[k] for k in ADDRESS_KEYS if k in value}
    if name in ENUMS:
        if value not in ENUMS[name]:
            raise ValueError(f"{name}={value!r} not in {sorted(ENUMS[name])}")
        return value
    if name == "paypal_seller_protection_status":
        if not isinstance(value, str) or not value:
            raise ValueError("paypal_seller_protection_status must be a non-empty string")
        return value
    if name in ("merchant_account_country", "currency", "tracking_number",
                "paypal_notification_timestamp", "shipment_timestamp"):
        if not isinstance(value, str) or not value:
            raise ValueError(f"{name} must be a non-empty string")
        return value
    raise ValueError(f"unknown name {name}")


@dataclass(frozen=True)
class Provenance:
    source_type: SourceType
    source_ref: str
    status: ProvStatus
    confidence: Optional[float] = None  
    timestamp: Optional[str] = None
    text_span: Optional[str] = None

    def __post_init__(self):
        if not self.source_ref:
            raise ValueError("provenance.source_ref is required")
        if self.source_type == SourceType.EXTRACTED_FROM_TEXT and not self.text_span:
            raise ValueError("text_span is required for EXTRACTED_FROM_TEXT provenance")

    def to_dict(self) -> Dict[str, Any]:
        return {"source_type": self.source_type.value, "source_ref": self.source_ref,
                "status": self.status.value, "confidence": self.confidence,
                "timestamp": self.timestamp, "text_span": self.text_span}


@dataclass(frozen=True)
class _Fact:
    name: str
    value: Any
    provenance: Provenance

    def __post_init__(self):
        object.__setattr__(self, "value", _validate_value(self.name, self.value))

    def to_dict(self) -> Dict[str, Any]:
        return {"layer": self.LAYER.value, "name": self.name, "value": self.value,
                "provenance": self.provenance.to_dict()}


@dataclass(frozen=True)
class TransactionFact(_Fact):
    """Layer TRANSACTION_FACT: what is known about the transaction itself."""
    LAYER = Layer.TRANSACTION_FACT

    def __post_init__(self):
        if self.name not in TRANSACTION_FACT_NAMES:
            raise ValueError(f"{self.name!r} is not a transaction-fact name")
        _Fact.__post_init__(self)


@dataclass(frozen=True)
class EvidenceFact(_Fact):
    """Merchant-supplied evidence item. The engine derives EvidenceAssessments from these."""
    LAYER = Layer.EVIDENCE_ASSESSMENT

    def __post_init__(self):
        if self.name not in EVIDENCE_NAMES:
            raise ValueError(f"{self.name!r} is not an evidence name")
        _Fact.__post_init__(self)


@dataclass(frozen=True)
class Case:
    case_id: str
    transaction_facts: Tuple[TransactionFact, ...] = ()
    evidence: Tuple[EvidenceFact, ...] = ()

    def __post_init__(self):
        seen = set()
        for f in self.transaction_facts:
            if f.name in seen:
                raise ValueError(f"duplicate transaction fact {f.name}")
            seen.add(f.name)

    def fact(self, name: str) -> Optional[TransactionFact]:
        for f in self.transaction_facts:
            if f.name == name:
                return f
        return None

    def evidence_items(self, name: str) -> Tuple[EvidenceFact, ...]:
        return tuple(e for e in self.evidence if e.name == name)

    def with_changes(self, set_facts: Iterable[TransactionFact] = (), remove_facts: Iterable[str] = (),
                     set_evidence: Iterable[EvidenceFact] = (), remove_evidence: Iterable[str] = ()) -> "Case":
        set_facts, set_evidence = tuple(set_facts), tuple(set_evidence)
        drop_f = set(remove_facts) | {f.name for f in set_facts}
        drop_e = set(remove_evidence) | {e.name for e in set_evidence}
        return Case(self.case_id,
                    tuple(f for f in self.transaction_facts if f.name not in drop_f) + set_facts,
                    tuple(e for e in self.evidence if e.name not in drop_e) + set_evidence)

    def snapshot(self) -> Dict[str, Any]:
        tf = sorted((f.to_dict() for f in self.transaction_facts), key=lambda d: d["name"])
        ev = sorted((e.to_dict() for e in self.evidence), key=lambda d: (d["name"], canonical(d["value"])))
        return {"case_id": self.case_id, "transaction_facts": tf, "evidence": ev}


@dataclass(frozen=True)
class Changes:
    """A counterfactual: a named set of edits to facts/evidence. Policy rules are never editable here."""
    label: str
    set_facts: Tuple[TransactionFact, ...] = ()
    remove_facts: Tuple[str, ...] = ()
    set_evidence: Tuple[EvidenceFact, ...] = ()
    remove_evidence: Tuple[str, ...] = ()

    def describe(self) -> List[str]:
        out = [f"set transaction fact {f.name} = {f.value!r}" for f in self.set_facts]
        out += [f"remove transaction fact {n}" for n in self.remove_facts]
        out += [f"set evidence {e.name} = {e.value!r} [{e.provenance.source_type.value}]" for e in self.set_evidence]
        out += [f"remove evidence {n}" for n in self.remove_evidence]
        return out


@dataclass(frozen=True)
class UnknownItem:
    """Layer UNKNOWN. Carried through to every assessment; never auto-resolved."""
    item_id: str
    text: str
    passage_ids: Tuple[str, ...] = ()

    def to_dict(self) -> Dict[str, Any]:
        return {"layer": Layer.UNKNOWN.value, "id": self.item_id, "text": self.text,
                "passage_ids": list(self.passage_ids)}


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()
