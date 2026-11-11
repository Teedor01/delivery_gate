"""Exposure components: three different quantities that must never be conflated.

  original_transaction_value  the capture's amount (Orders v2). What was paid. It is NOT a disputed amount and NOT a bound on exposure.
  disputed_amount             `dispute_amount` from the Disputes API: what the customer actually disputed. PayPal documents that it may be less than the
                              original transaction's gross or net amount. UNKNOWN unless a dispute that links to this capture has been observed.
  potential_seller_exposure   what the seller could lose. UNKNOWN in Phase 3: no reviewed policy rule defines it, so nothing here derives it
                              (not from the capture amount, and not from the disputed amount either).

This is a read-only view over observations. It never touches the Phase 1 engine, and it deliberately uses no 'floor' or 'minimum' vocabulary.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

from .adapter import CaptureObservation
from . import disputes as dmod
from .disputes import DisputeObservation

TERMS = ("original_transaction_value", "disputed_amount", "potential_seller_exposure")


def _component(state: str, value: Optional[str] = None, currency: Optional[str] = None, source: Optional[str] = None, reason: Optional[str] = None,
               api_semantics_ref: Optional[str] = None, note: str = "") -> Dict[str, Any]:
    return {"state": state, "value": value, "currency": currency, "source_observation": source, "reason": reason,
            "api_semantics_ref": api_semantics_ref, "note": note}


@dataclass(frozen=True)
class ExposureComponents:
    original_transaction_value: Dict[str, Any]
    disputed_amount: Dict[str, Any]
    potential_seller_exposure: Dict[str, Any]
    linkage: Dict[str, Any]
    flags: tuple

    def to_dict(self) -> Dict[str, Any]:
        return {"original_transaction_value": self.original_transaction_value, "disputed_amount": self.disputed_amount,
                "potential_seller_exposure": self.potential_seller_exposure, "linkage": self.linkage, "flags": list(self.flags)}


def _original(cap: CaptureObservation) -> Dict[str, Any]:
    v, c = cap.find("amount.value"), cap.find("amount.currency_code")
    if v is None or v.normalized_value is None:
        return _component("UNKNOWN", reason="CAPTURE_AMOUNT_NOT_OBSERVED_OR_UNUSABLE")
    return _component("OBSERVED", v.normalized_value, c.normalized_value if c is not None else None, v.observation_id, None, v.api_semantics_ref,
                      "The amount of this capture. Refunds are not reflected; the capture may be one of several on the order.")


def _disputed(cap: CaptureObservation, dispute: Optional[DisputeObservation], flags: list, linkage: Dict[str, Any]) -> Dict[str, Any]:
    if dispute is None:
        return _component("UNKNOWN", reason="NO_DISPUTE_OBSERVED", note="No dispute exists or none has been read; the disputed amount is not assumed from the transaction value.")
    linked = dmod.is_linked(cap.capture_id, dispute)
    linkage.update({"capture_id": cap.capture_id, "dispute_id": dispute.dispute_id, "dispute_seller_transaction_ids": list(dispute.seller_transaction_ids),
                    "linked": linked, "basis": "IDENTIFIER_EQUALITY_ONLY: PayPal's docs do not state that a capture id and a dispute's seller_transaction_id share a namespace"})
    if not linked:
        return _component("UNKNOWN", reason="DISPUTE_NOT_LINKED_TO_CAPTURE")
    v, c = dispute.find("dispute_amount.value"), dispute.find("dispute_amount.currency_code")
    if v is None or v.normalized_value is None:
        return _component("UNKNOWN", reason="DISPUTE_AMOUNT_NOT_OBSERVED_OR_UNUSABLE")
    orig_c = cap.find("amount.currency_code")
    if c is None or c.normalized_value is None or orig_c is None or orig_c.normalized_value != c.normalized_value:
        flags.append("CURRENCY_MISMATCH_OR_UNKNOWN")
        return _component("UNKNOWN", reason="CURRENCY_MISMATCH_OR_UNKNOWN", note="Disputed and original currencies could not be confirmed equal, so no value is presented.")
    return _component("OBSERVED", v.normalized_value, c.normalized_value, v.observation_id, None, v.api_semantics_ref,
                      "What the customer originally disputed; documented as possibly less than the original transaction's gross or net amount.")


def _potential(original: Dict[str, Any], disputed: Dict[str, Any]) -> Dict[str, Any]:
    return _component("UNKNOWN", reason="NO_REVIEWED_POLICY_RULE_DEFINES_POTENTIAL_SELLER_EXPOSURE",
                      note="Not derived from the original transaction value or from the disputed amount. Defining it needs a separately reviewed policy change.")


def build_exposure(cap: CaptureObservation, dispute: Optional[DisputeObservation] = None) -> ExposureComponents:
    flags: list = []
    linkage: Dict[str, Any] = {}
    original = _original(cap)
    disputed = _disputed(cap, dispute, flags, linkage)
    if original["state"] == "OBSERVED" and disputed["state"] == "OBSERVED":
        from decimal import Decimal
        if Decimal(disputed["value"]) > Decimal(original["value"]):
            flags.append("DISPUTED_AMOUNT_EXCEEDS_CAPTURE_AMOUNT")
    return ExposureComponents(original, disputed, _potential(original, disputed), linkage, tuple(flags))
