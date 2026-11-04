from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional, Protocol, Set

REQUIRED_HEADERS = ("PAYPAL-TRANSMISSION-ID", "PAYPAL-TRANSMISSION-TIME", "PAYPAL-CERT-URL", "PAYPAL-AUTH-ALGO", "PAYPAL-TRANSMISSION-SIG")
DISPUTE_EVENTS = frozenset({"CUSTOMER.DISPUTE.CREATED", "CUSTOMER.DISPUTE.UPDATED", "CUSTOMER.DISPUTE.RESOLVED"})
DOC_REFS = ("https://developer.paypal.com/api/webhooks/v1/verify-webhook-signature-post", "https://developer.paypal.com/docs/disputes/webhooks")


class SignatureVerifier(Protocol):
    def verify(self, headers: Mapping[str, str], event: Dict[str, Any], webhook_id: str) -> str:
        """Return 'SUCCESS' or 'FAILURE' (PayPal's documented verification_status values)."""


class UnconfiguredVerifier:
    """Fails closed. A real verifier would call PayPal's verify-webhook-signature endpoint; none is built in Phase 3."""
    def verify(self, headers, event, webhook_id) -> str:
        return "FAILURE"


@dataclass(frozen=True)
class ReadRequest:
    dispute_id: str
    event_id: str
    event_type: str
    purpose: str = "FRESH_DISPUTES_API_READ"


@dataclass(frozen=True)
class WebhookDecision:
    accepted: bool
    reason: str
    read_request: Optional[ReadRequest] = None


class WebhookReceiver:
    def __init__(self, verifier: SignatureVerifier, webhook_id: str):
        if not webhook_id:
            raise ValueError("webhook_id is required")
        self._verifier, self._webhook_id = verifier, webhook_id
        self._seen: Set[str] = set()

    def receive(self, headers: Mapping[str, str], event: Any) -> WebhookDecision:
        h = {str(k).upper(): v for k, v in (headers or {}).items()}
        for name in REQUIRED_HEADERS:
            if not isinstance(h.get(name), str) or not h[name]:
                return WebhookDecision(False, f"MISSING_HEADER:{name}")
        if not isinstance(event, dict):
            return WebhookDecision(False, "MALFORMED_EVENT")
        if not self._verified(h, event):
            return WebhookDecision(False, "SIGNATURE_NOT_VERIFIED")
        eid, etype = event.get("id"), event.get("event_type")
        if not isinstance(eid, str) or not eid or not isinstance(etype, str):
            return WebhookDecision(False, "MALFORMED_EVENT")
        if etype not in DISPUTE_EVENTS:
            return WebhookDecision(False, "EVENT_TYPE_NOT_HANDLED")
        resource = event.get("resource")
        did = resource.get("dispute_id") if isinstance(resource, dict) else None
        if not isinstance(did, str) or not did:
            return WebhookDecision(False, "NO_DISPUTE_ID")
        if eid in self._seen:
            return WebhookDecision(False, "DUPLICATE_EVENT")
        self._seen.add(eid)
        return WebhookDecision(True, "VERIFIED_NOTIFICATION", self._make_request(did, eid, etype))

    def _verified(self, headers: Mapping[str, str], event: Dict[str, Any]) -> bool:
        try:
            return self._verifier.verify(headers, event, self._webhook_id) == "SUCCESS"
        except Exception:                             
            return False

    @staticmethod
    def _make_request(dispute_id: str, event_id: str, event_type: str) -> ReadRequest:
        return ReadRequest(dispute_id, event_id, event_type)
