from __future__ import annotations

from typing import Any, Dict

from .models import Case, EvidenceFact, Provenance, ProvStatus, SourceType, TransactionFact

TD_ADDR = {"line1": "1 Market St", "city": "San Francisco", "region": "CA", "postal_code": "94105", "country": "US"}
TD_ADDR_FORMATTED_DIFFERENTLY = {"line1": "1 MARKET ST.", "city": "san francisco", "region": "ca",
                                 "postal_code": "94105", "country": "us"}
WRONG_ADDR = {"line1": "99 Elm Ave", "city": "Austin", "region": "TX", "postal_code": "78701", "country": "US"}


def tf(name: str, value: Any, st: SourceType = SourceType.PAYPAL_API, ref: str = "fixture:paypal-capture-FX1",
       ps: ProvStatus = ProvStatus.SYSTEM_RECORD, **kw) -> TransactionFact:
    return TransactionFact(name, value, Provenance(st, ref, ps, **kw))


def ev(name: str, value: Any, st: SourceType = SourceType.CARRIER_API, ref: str = "fixture:carrier-FX1",
       ps: ProvStatus = ProvStatus.SYSTEM_RECORD, **kw) -> EvidenceFact:
    return EvidenceFact(name, value, Provenance(st, ref, ps, **kw))


def merchant(name: str, value: Any, ref: str = "fixture:merchant-FX1") -> EvidenceFact:
    return ev(name, value, SourceType.MERCHANT_INPUT, ref, ProvStatus.MERCHANT_ASSERTED)


def _facts(category: str, route: str = "PAYPAL_DISPUTE", country: str = "US", funding: str = "CARD",
           amount: str = "1200.00", **extra: Any):
    facts = {"merchant_account_country": country, "claim_category": category, "route": route,
             "funding_source": funding, "transaction_amount": amount, "currency": "USD", "physical_goods": True,
             "transaction_details_address": TD_ADDR, "pre_order_or_made_to_order": False}
    facts.update(extra)
    return facts


def build(case_id: str, facts: Dict[str, Any], evidence: tuple) -> Case:
    return Case(case_id, tuple(tf(k, v) for k, v in facts.items() if v is not None), tuple(evidence))


def inr_evidence() -> tuple:
    return (
        ev("delivery_record", True), ev("tracking_number", "1Z999AA10123456784"),
        ev("delivery_date", "2026-10-20"), ev("delivered_status", "DELIVERED"),
        ev("recipient_address", TD_ADDR_FORMATTED_DIFFERENTLY),
        merchant("shipped_to_transaction_address", True),
        ev("redirect_detected", False), merchant("response_to_paypal", "NO_REQUEST_OUTSTANDING"),
        merchant("shipped_after_advised_not_to_release", False),
    )


def inr_case(case_id: str = "INR-FX-1", **fact_overrides: Any) -> Case:
    return build(case_id, _facts("ITEM_NOT_RECEIVED", **fact_overrides), inr_evidence())


def unauth_evidence() -> tuple:
    return (
        ev("shipment_record", True), ev("tracking_number", "1Z999AA10123456785"), ev("shipment_date", "2026-10-18"),
        ev("recipient_address", TD_ADDR), merchant("shipped_to_transaction_address", True),
        ev("redirect_detected", False), merchant("response_to_paypal", "NO_REQUEST_OUTSTANDING"),
        merchant("shipped_after_advised_not_to_release", False),
    )


def unauth_case(case_id: str = "UNAUTH-FX-1", status: Any = "ELIGIBLE", **fact_overrides: Any) -> Case:
    return build(case_id, _facts("UNAUTHORIZED_TRANSACTION", paypal_seller_protection_status=status, **fact_overrides),
                 unauth_evidence())


def snad_case(case_id: str = "SNAD-FX-1", **fact_overrides: Any) -> Case:
    f = _facts("SIGNIFICANTLY_NOT_AS_DESCRIBED", amount="480.00", **fact_overrides)
    return build(case_id, f, ())
