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
    """A reviewer attests the ARTIFACT ITSELF is a genuine carrier document (the model can never make this claim).
    This is a statement about the source, not agreement with the extracted text, and it can only ever grant REVIEWED
    authenticity: VERIFIED is reserved for an independent corroboration source (e.g. a carrier API) kept as a separate
    provenance source, so a reviewer cannot grant it."""
    artifact_id: str
    reviewer: str
    attested_source_type: str = "CARRIER_DOCUMENT"
    authenticity: str = "REVIEWED"

    def __post_init__(self):
        if self.authenticity != "REVIEWED":
            raise ReviewError(f"a reviewer attestation can only confer REVIEWED authenticity, not {self.authenticity!r}")
