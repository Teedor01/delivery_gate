from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class SourceRole:
    input_name: str
    source: str
    role: str                 
    provenance: str           
    mandatory: bool        
    implemented: str         
    reaches_engine_as: str
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


ROLES: Tuple[SourceRole, ...] = (
    SourceRole("original_transaction_value", "Orders v2 capture: amount.value / currency_code", "PRIMARY", "PAYPAL_API / SYSTEM_RECORD", True, "IMPLEMENTED_FIXTURES",
               "currency only; the amount is held in the exposure view and NOT handed to the engine",
               "The Phase 1 SNAD rule would treat a handed-over amount as a lower bound of exposure; PayPal documents that disputes can be partial."),
    SourceRole("disputed_amount", "Disputes API show-dispute-details: dispute_amount", "PRIMARY", "PAYPAL_API / SYSTEM_RECORD", False, "IMPLEMENTED_FIXTURES",
               "not handed to the engine (no engine consumer); reported in the exposure view", "UNKNOWN until a dispute linked to the capture has been read."),
    SourceRole("claim_category / reason", "Disputes API: reason (raw value preserved)", "PRIMARY", "PAYPAL_API / SYSTEM_RECORD", False, "IMPLEMENTED_FIXTURES",
               "claim_category, only where the normalization table marks the reason established", "CLAIM_REASON_TABLE_V1; NOT_AS_DESCRIBED is not normalised yet."),
    SourceRole("lifecycle_stage", "Disputes API: dispute_life_cycle_stage (separate field)", "PRIMARY", "PAYPAL_API / SYSTEM_RECORD", False, "IMPLEMENTED_FIXTURES",
               "observation only (the engine has no lifecycle fact)", "Never merged with reason or route; a stage is not a route."),
    SourceRole("dispute_route", "Disputes API: dispute_channel (the only explicit, documented channel field)", "PRIMARY", "PAYPAL_API / SYSTEM_RECORD", False, "IMPLEMENTED_FIXTURES",
               "route = PAYPAL_DISPUTE for INTERNAL only; EXTERNAL and ALERT leave route unknown", "Never inferred from the claim reason or the lifecycle stage."),
    SourceRole("merchant_account_country", "Merchant-asserted configuration", "ASSERTED", "MERCHANT_INPUT / MERCHANT_ASSERTED", False, "IMPLEMENTED_INTERFACE_ONLY",
               "merchant_account_country, or missing if not asserted",
               "PayPal documents a partner-only 'show seller status' call that returns a country for onboarded sellers; whether it applies to a direct-merchant "
               "integration, and what 'country' means, was not established. Not implemented."),
    SourceRole("webhook notification", "CUSTOMER.DISPUTE.CREATED / UPDATED / RESOLVED", "TRIGGER_ONLY", "none: the payload yields no facts", False, "IMPLEMENTED_INTERFACE_ONLY",
               "nothing; a verified notification yields a request for a fresh Disputes API read",
               "Verification is an injected interface (PayPal's verify-webhook-signature); no live verifier exists; default fails closed."),
    SourceRole("Dispute Detail Custom report", "SFTP report for approved merchants", "SUPPLEMENTARY", "n/a", False, "NOT_IMPLEMENTED",
               "nothing", "Reconciliation only. Not a dependency of any assessment."),
    SourceRole("transaction_details_address", "none established", "UNKNOWN", "n/a", False, "NOT_IMPLEMENTED", "nothing",
               "The Orders shipping address is recorded as an observation but is not treated as the Transaction Details address."),
    SourceRole("funding_source", "none exposed on the capture resource", "UNKNOWN", "n/a", False, "NOT_IMPLEMENTED", "nothing", "Stays an open UNKNOWN in the engine."),
)


def source_roles():
    return [r.to_dict() for r in ROLES]
