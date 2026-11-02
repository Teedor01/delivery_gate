from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

UNKNOWN = "UNKNOWN"

# fact -> type, the Phase 1 evidence name it may feed (or None) and why not.
FACT_VOCAB: Dict[str, Dict[str, Any]] = {
    "tracking_number": {"type": "string", "engine": "tracking_number"},
    "carrier_name": {"type": "string", "engine": None, "why": "no policy requirement models the carrier name"},
    "delivery_status": {"type": "enum", "values": ["DELIVERED", "IN_TRANSIT", "RETURNED", "UNDELIVERABLE"], "engine": "delivered_status"},
    "delivery_date": {"type": "date", "engine": "delivery_date"},
    "delivery_time": {"type": "time", "engine": None, "why": "no policy requirement models the delivery time of day"},
    "shipment_date": {"type": "date", "engine": "shipment_date"},
    "recipient_address": {"type": "address", "engine": "recipient_address"},
    "intended_ship_to_address": {"type": "address", "engine": None,
                                 "why": "a merchant-stated intended address is not the PayPal Transaction Details address"},
    "signature_present": {"type": "bool", "engine": None, "why": "signature confirmation is UNVERIFIED: DO NOT MODEL"},
    "redirect_reported": {"type": "bool", "engine": "redirect_detected"},
    "order_reference": {"type": "string", "engine": None, "why": "used only to group facts by order"},
}
ADDRESS_FIELDS = ("line1", "line2", "city", "region", "postal_code", "country")
ATTRIBUTIONS = ("CARRIER_STATEMENT", "MERCHANT_STATEMENT", "CUSTOMER_STATEMENT_RELAYED", "THIRD_PARTY_STATEMENT", "UNKNOWN")
MODALITIES = ("DIRECT", "REPORTED", "HEDGED")
CONFIDENCES = ("HIGH", "MEDIUM", "LOW")
ARTIFACT_KINDS = ("CARRIER_EMAIL", "TRACKING_PASTE", "MERCHANT_STATEMENT", "CUSTOMER_MESSAGE", "OTHER")
FACT_KEYS = ("fact_id", "fact", "value", "normalized_value", "source_span", "confidence", "ambiguity", "ambiguity_note",
             "attribution", "modality", "entity_ref", "artifact_id")
OUTPUT_KEYS = ("artifact_id", "facts", "extraction_notes")
MAX_SPAN_CHARS = 400


@dataclass(frozen=True)
class Artifact:
    artifact_id: str
    text: str
    declared_kind: str = "OTHER"     

    def __post_init__(self):
        if self.declared_kind not in ARTIFACT_KINDS:
            raise ValueError(f"declared_kind must be one of {ARTIFACT_KINDS}")

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class CandidateFact:
    """A validated candidate fact. Confidence describes extraction confidence ONLY and is never consumed downstream."""
    artifact_id: str
    local_id: str
    fact: str
    value: str
    normalized_value: Any
    source_span: str
    span_start: int
    span_end: int
    confidence: str
    ambiguity: bool
    ambiguity_note: Optional[str]
    attribution: str
    modality: str
    entity_ref: Optional[str]
    extraction_status: str = "VALIDATED"

    @property
    def fact_id(self) -> str:
        return f"{self.artifact_id}#{self.local_id}"

    def to_dict(self) -> Dict[str, Any]:
        return {"fact_id": self.fact_id, "artifact_id": self.artifact_id, "fact": self.fact, "value": self.value,
                "normalized_value": self.normalized_value, "source_span": self.source_span,
                "span_start": self.span_start, "span_end": self.span_end, "confidence": self.confidence,
                "ambiguity": self.ambiguity, "ambiguity_note": self.ambiguity_note, "attribution": self.attribution,
                "modality": self.modality, "entity_ref": self.entity_ref, "extraction_status": self.extraction_status}
