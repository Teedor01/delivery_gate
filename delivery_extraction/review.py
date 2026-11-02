from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReviewAction(str, Enum):
    APPROVE_AS_MERCHANT_ASSERTION = "APPROVE_AS_MERCHANT_ASSERTION"
    APPROVE_AS_CARRIER_DOCUMENT = "APPROVE_AS_CARRIER_DOCUMENT"
    REJECT = "REJECT"


class ReviewError(ValueError):
    pass


@dataclass(frozen=True)
class ReviewDecision:
    fact_id: str
    action: ReviewAction
    reviewer: str
    note: str = ""


@dataclass(frozen=True)
class Attestation:
    """A reviewer attests the artifact itself is an authentic carrier document (the model can never make this claim)."""
    artifact_id: str
    reviewer: str
    attested_source_type: str = "CARRIER_DOCUMENT"
