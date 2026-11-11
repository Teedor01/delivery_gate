"""Disputes API observation adapter (GET /v1/customer/disputes/{id}, 'show dispute details'). Observation only, like adapter.py.

Source roles (decided by the reviewer, enforced here):
  claim reason      -> `reason`, raw value always preserved; normalised to a Delivery Gate claim category ONLY where the table says established
  lifecycle stage   -> `dispute_life_cycle_stage`, its own observation, never merged with reason or route
  dispute route     -> UNKNOWN unless PayPal explicitly exposes and documents it: only `dispute_channel` does, and only INTERNAL is normalised
  disputed amount   -> `dispute_amount`, kept apart from the original transaction value
Nothing is inferred from the claim reason: the route never depends on `reason`, and `reason` never depends on the channel or stage.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from . import api_semantics as sem
from .adapter import (Absence, Anomaly, MalformedPayPalResponse, Observation, _Ctx, _absent, _anomaly, _extract_money, _make_obs, _prepare)
from .inventory import Semantics

API_NAME = "PayPal Disputes v1"
DOC = sem.DISPUTES_REF
DOCUMENTED_REASONS = frozenset({"MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", "UNAUTHORISED", "CREDIT_NOT_PROCESSED",
                                "DUPLICATE_TRANSACTION", "INCORRECT_AMOUNT", "PAYMENT_BY_OTHER_MEANS", "CANCELED_RECURRING_BILLING",
                                "PROBLEM_WITH_REMITTANCE", "OTHER"})
DOCUMENTED_STATUSES = frozenset({"OPEN", "WAITING_FOR_BUYER_RESPONSE", "WAITING_FOR_SELLER_RESPONSE", "UNDER_REVIEW", "RESOLVED", "OTHER"})
DOCUMENTED_STATES = frozenset({"OPEN_INQUIRIES", "REQUIRED_ACTION", "REQUIRED_OTHER_PARTY_ACTION", "UNDER_PAYPAL_REVIEW", "APPEALABLE", "RESOLVED"})
DOCUMENTED_STAGES = frozenset({"INQUIRY", "CHARGEBACK", "PRE_ARBITRATION", "ARBITRATION"})
DOCUMENTED_CHANNELS = frozenset({"INTERNAL", "EXTERNAL", "ALERT"})


@dataclass(frozen=True)
class Normalization:
    delivery_gate_value: Optional[str]   # None = no normalisation: the Delivery Gate fact stays missing
    established: bool                    # True only where PayPal's documentation states the meaning the normalisation relies on
    basis: Tuple[str, ...]
    note: str

    def to_dict(self) -> Dict[str, Any]:
        return {"delivery_gate_value": self.delivery_gate_value, "established": self.established, "basis": list(self.basis), "note": self.note}


# reason -> Delivery Gate claim category. Documented normalisation, table version 1.
CLAIM_REASON_TABLE_V1: Dict[str, Normalization] = {
    "MERCHANDISE_OR_SERVICE_NOT_RECEIVED": Normalization("ITEM_NOT_RECEIVED", True, (sem.DISPUTES_WEBHOOKS, sem.DISPUTES_GUIDE),
                                                          "PayPal describes the reason as the customer not receiving the merchandise or service."),
    "UNAUTHORISED": Normalization("UNAUTHORIZED_TRANSACTION", True, (sem.DISPUTES_REF + "#dispute_info", sem.DISPUTES_GUIDE),
                                  "PayPal describes the reason as the customer not authorizing the purchase."),
    "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": Normalization("SIGNIFICANTLY_NOT_AS_DESCRIBED", False, (sem.DISPUTES_GUIDE,),
                                                              "NOT applied: the value is listed but no PayPal description of it was retrieved, and 'not as described' vs the policy's "
                                                              "'significantly not as described' is not established by name alone. Set established=True only after a primary description is recorded."),
}
# dispute_channel -> Delivery Gate route. Only INTERNAL is normalised.
CHANNEL_ROUTE_TABLE_V1: Dict[str, Normalization] = {
    "INTERNAL": Normalization("PAYPAL_DISPUTE", True, (sem.DISPUTES_REF + "#dispute_channel", sem.DISPUTES_OVERVIEW + "#internal-disputes"),
                              "PayPal documents INTERNAL as the customer contacting PayPal to file a dispute with the merchant."),
    "EXTERNAL": Normalization(None, False, (sem.DISPUTES_OVERVIEW + "#external-disputes",),
                              "NOT applied: PayPal documents external disputes as including card chargebacks AND ACH returns, and the policy text retrieved does not establish "
                              "Item Not Received handling for other routes such as bank reversals. Route stays unknown."),
    "ALERT": Normalization(None, False, (sem.DISPUTES_OVERVIEW + "#types-of-external-disputes",),
                           "NOT applied: a pre-chargeback alert is a notification about a potential chargeback, not a filed dispute. Route stays unknown."),
}


def normalization_tables() -> Dict[str, Any]:
    return {"claim_reason_table_v1": {k: v.to_dict() for k, v in CLAIM_REASON_TABLE_V1.items()},
            "channel_route_table_v1": {k: v.to_dict() for k, v in CHANNEL_ROUTE_TABLE_V1.items()}}


# ---- hooks (module-level so mutation checks can sabotage them) ----------------------------------------------------------------
def _claim_category_for(reason: Any) -> Tuple[Optional[str], str]:
    rule = CLAIM_REASON_TABLE_V1.get(reason) if isinstance(reason, str) else None
    if rule is None:
        return None, "NONE"
    return (rule.delivery_gate_value if rule.established else None), f"CLAIM_REASON_TABLE_V1:{'ESTABLISHED' if rule.established else 'NOT_ESTABLISHED'}"


def _route_for(channel: Any, reason: Any) -> Tuple[Optional[str], str]:
    """The route depends on the channel alone. The claim reason is passed in only so that a mistaken dependency on it can be detected."""
    rule = CHANNEL_ROUTE_TABLE_V1.get(channel) if isinstance(channel, str) else None
    if rule is None:
        return None, "NONE"
    return (rule.delivery_gate_value if rule.established else None), f"CHANNEL_ROUTE_TABLE_V1:{'ESTABLISHED' if rule.established else 'NOT_ESTABLISHED'}"


def is_linked(capture_id: str, dispute: "DisputeObservation") -> bool:
    """A dispute is tied to a capture only by an observed identifier: the capture id appears among the dispute's seller_transaction_ids."""
    return capture_id in dispute.seller_transaction_ids


# ---- records ------------------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class DisputeObservation:
    dispute_id: str
    origin: str
    observed_at: Optional[str]
    response_sha256: str
    resource_ref: str
    seller_transaction_ids: Tuple[str, ...]
    observations: Tuple[Observation, ...]
    absent: Tuple[Absence, ...]
    anomalies: Tuple[Anomaly, ...]

    def find(self, local_path: str) -> Optional[Observation]:
        return next((o for o in self.observations if o.local_path == local_path), None)

    def to_dict(self) -> Dict[str, Any]:
        return {"dispute_id": self.dispute_id, "origin": self.origin, "observed_at": self.observed_at, "response_sha256": self.response_sha256,
                "resource_ref": self.resource_ref, "seller_transaction_ids": list(self.seller_transaction_ids),
                "observations": [o.to_dict() for o in self.observations], "absent": [a.to_dict() for a in self.absent],
                "anomalies": [a.to_dict() for a in self.anomalies]}


def _enum(ctx: _Ctx, d: Dict[str, Any], key: str, documented: frozenset, sem_field: Optional[str], semantics: Semantics,
          normalizer=None) -> None:
    if key not in d:
        _absent(ctx, key)
        return
    raw = d[key]
    if not isinstance(raw, str) or not raw:
        ctx.obs.append(_make_obs(ctx, key, raw, None, "NONE", semantics, DOC))
        _anomaly(ctx, key, ("TYPE_NOT_NONEMPTY_STRING", "documented as an enum string"), raw)
        return
    state = "DOCUMENTED_TOKEN" if raw in documented else "UNDOCUMENTED_TOKEN"
    norm, how = (normalizer(raw) if normalizer else (raw, "NONE"))
    ctx.obs.append(_make_obs(ctx, key, raw, norm, how if normalizer else "NONE", semantics, DOC, enum_state=state,
                             api_semantics_ref=sem.ref_for(sem_field, raw) if sem_field else None))
    if state == "UNDOCUMENTED_TOKEN":
        _anomaly(ctx, key, ("UNDOCUMENTED_ENUM_VALUE", "token is not in PayPal's documented enum; kept verbatim, nothing normalised"), raw)


def observe_dispute(response: Any, *, origin: str, observed_at: Optional[str] = None) -> DisputeObservation:
    sha = _prepare(response, origin, observed_at)
    did = response.get("dispute_id")
    if not isinstance(did, str) or not did:
        raise MalformedPayPalResponse(["dispute_id is missing or not a non-empty string"])
    txs = response.get("disputed_transactions")
    if txs is not None and (not isinstance(txs, list) or not all(isinstance(t, dict) for t in txs)):
        raise MalformedPayPalResponse(["disputed_transactions is not an array of objects"])
    ctx = _Ctx(origin, f"{origin.lower()}:paypal-dispute:{did}", sha, observed_at, "dispute", [], [], [], API_NAME)
    ctx.obs.append(_make_obs(ctx, "dispute_id", did, did, "NONE", Semantics.OBSERVED_SEMANTICS_UNKNOWN, DOC))
    reason = response.get("reason")
    _enum(ctx, response, "reason", DOCUMENTED_REASONS, sem.RS, Semantics.OBSERVED_AND_DOCUMENTED, _claim_category_for)
    _enum(ctx, response, "dispute_life_cycle_stage", DOCUMENTED_STAGES, sem.LS, Semantics.OBSERVED_AND_DOCUMENTED)
    _enum(ctx, response, "dispute_channel", DOCUMENTED_CHANNELS, sem.CH, Semantics.OBSERVED_AND_DOCUMENTED,
          lambda ch: _route_for(ch, reason))
    _enum(ctx, response, "status", DOCUMENTED_STATUSES, None, Semantics.OBSERVED_SEMANTICS_UNKNOWN)
    _enum(ctx, response, "dispute_state", DOCUMENTED_STATES, None, Semantics.OBSERVED_SEMANTICS_UNKNOWN)
    _extract_money(ctx, response.get("dispute_amount"), "dispute_amount", sem.DISPUTE_SEARCH, Semantics.OBSERVED_AND_DOCUMENTED, sem.DA)
    for t in ("create_time", "update_time"):
        if t in response:
            ok = isinstance(response[t], str) and bool(response[t])
            ctx.obs.append(_make_obs(ctx, t, response[t], response[t] if ok else None, "NONE", Semantics.OBSERVED_SEMANTICS_UNKNOWN, DOC))
            if not ok:
                _anomaly(ctx, t, ("TYPE_NOT_NONEMPTY_STRING", "documented as a date-time string"), response[t])
        else:
            _absent(ctx, t)
    ids: List[str] = []
    if txs is None:
        _absent(ctx, "disputed_transactions")
    for i, t in enumerate(txs or []):
        sid = t.get("seller_transaction_id")
        if isinstance(sid, str) and sid:
            ids.append(sid)
            ctx.obs.append(_make_obs(ctx, f"disputed_transactions[{i}].seller_transaction_id", sid, sid, "NONE", Semantics.NOT_VERIFIED, DOC))
        else:
            _absent(ctx, f"disputed_transactions[{i}].seller_transaction_id")
        _extract_money(ctx, t.get("gross_amount"), f"disputed_transactions[{i}].gross_amount", DOC, Semantics.NOT_VERIFIED)
    return DisputeObservation(did, origin, observed_at, sha, ctx.resource_ref, tuple(ids), tuple(ctx.obs), tuple(ctx.absent), tuple(ctx.anomalies))
