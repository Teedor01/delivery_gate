from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional, Tuple

RETRIEVED = "2026-11-01"
CAPTURE = "https://developer.paypal.com/api/orders/v2/definitions/capture"
DISPUTES_REF = "https://developer.paypal.com/docs/api/customer-disputes/v1/"
DISPUTE_SEARCH = "https://developer.paypal.com/api/customer-disputes/v1/definitions/dispute_search"
DISPUTES_OVERVIEW = "https://developer.paypal.com/disputes/overview"
DISPUTES_WEBHOOKS = "https://developer.paypal.com/docs/disputes/webhooks"
DISPUTES_GUIDE = "https://developer.paypal.com/docs/disputes/integration-guide/"
DISPUTE_REPORT = "https://developer.paypal.com/docs/reports/sftp-reports/dispute-detail-custom/"

EQUIVALENCE_NOTE_STATUS = (
    "The API describes the effect on the seller's PayPal balance for the claim types named. That is not shown to be the same as the "
    "'eligible'/'partially eligible' mark on the Transaction Details page that the legal policy refers to, no PayPal document links the two, "
    "and the policy says PayPal decides at dispute time. A differently-scoped description of a similarly named value exists on another PayPal "
    "surface (see CROSS_SURFACE_NOTES), so equivalence across surfaces cannot be assumed.")

CROSS_SURFACE_NOTES: Tuple[Dict[str, str], ...] = (
    {"note_id": "report.partially_eligible_unauth_only",
     "surface": "Dispute Detail Custom report (SFTP, approved merchants)", "source": DISPUTE_REPORT + "#case-fields",
     "says": "Its 'Seller Protection' column defines 'Partially Eligible Unauth Only' as protection for Unauthorized Payment only, 'Eligible' as "
             "Unauthorized Payment and Item Not Received, and 'Ineligible' as not protected.",
     "bearing": "Compare with the Orders v2 description of PARTIALLY_ELIGIBLE (item-not-received only). Different surfaces, different scope: the "
                "token/label equivalence is not established and Delivery Gate does not assume it."},
)


@dataclass(frozen=True)
class ApiValueSemantics:
    semantics_id: str
    api: str
    field: str
    value: str
    meaning_status: str                       
    documented_meaning: Optional[str]
    described_claim_types: Tuple[str, ...] 
    sources: Tuple[str, ...]
    legal_policy_equivalence: str = "NOT_ESTABLISHED"
    equivalence_note: str = ""
    retrieved: str = RETRIEVED

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["described_claim_types"], d["sources"] = list(self.described_claim_types), list(self.sources)
        return d


_NOT_RECEIVED, _NOT_AUTHORIZED = "customer did not receive an item", "account holder did not authorize the payment"
_ROWS: Dict[Tuple[str, str], ApiValueSemantics] = {}


def _add(field_id: str, api: str, field: str, value: str, meaning: Optional[str], claims: Tuple[str, ...], sources: Tuple[str, ...], note: str = "") -> None:
    sid = f"{field_id}={value}"
    _ROWS[(field_id, value)] = ApiValueSemantics(sid, api, field, value, "DOCUMENTED" if meaning else "NAME_ONLY", meaning, claims, sources, "NOT_ESTABLISHED", note)


O2 = "PayPal Orders v2"
SPS = "orders_v2.capture.seller_protection.status"
_add(SPS, O2, "capture.seller_protection.status", "ELIGIBLE",
     "PayPal states the seller's PayPal balance remains intact if the customer claims they did not receive an item OR the account holder claims they did not authorize the payment.",
     (_NOT_RECEIVED, _NOT_AUTHORIZED), (CAPTURE + "#seller_protection.status",), EQUIVALENCE_NOTE_STATUS)
_add(SPS, O2, "capture.seller_protection.status", "PARTIALLY_ELIGIBLE",
     "PayPal states the seller's PayPal balance remains intact if the customer claims they did not receive an item (the unauthorized-payment case is not described).",
     (_NOT_RECEIVED,), (CAPTURE + "#seller_protection.status",), EQUIVALENCE_NOTE_STATUS)
_add(SPS, O2, "capture.seller_protection.status", "NOT_ELIGIBLE",
     "PayPal states the transaction is not eligible for seller protection.", (), (CAPTURE + "#seller_protection.status",), EQUIVALENCE_NOTE_STATUS)

CS = "orders_v2.capture.status"
for v, m in (("COMPLETED", "The funds for this captured payment were credited to the payee's PayPal account."),
             ("DECLINED", "The funds could not be captured."),
             ("PARTIALLY_REFUNDED", "An amount less than the captured payment's amount was refunded to the payer."),
             ("PENDING", "The funds were not yet credited to the payee's PayPal account (see status_details)."),
             ("REFUNDED", "An amount greater than or equal to the captured payment's amount was refunded to the payer."),
             ("FAILED", "There was an error while capturing the payment.")):
    _add(CS, O2, "capture.status", v, m, (), (CAPTURE + "#status",))

SDR = "orders_v2.capture.status_details.reason"
_add(SDR, O2, "capture.status_details.reason", "BUYER_COMPLAINT", "The payer initiated a dispute for this captured payment with PayPal.", (), (CAPTURE + "#status_details.reason",),
     "Documented only for captures whose status is PENDING or DENIED. Not read as a Delivery Gate dispute route.")
_add(SDR, O2, "capture.status_details.reason", "CHARGEBACK",
     "The captured funds were reversed in response to the payer disputing this captured payment with the issuer of the financial instrument used to pay.",
     (), (CAPTURE + "#status_details.reason",), "Documented only for captures whose status is PENDING or DENIED. Not read as a Delivery Gate dispute route.")

D = "PayPal Disputes v1"
CH = "disputes_v1.dispute.dispute_channel"
_add(CH, D, "dispute.dispute_channel", "INTERNAL", "The customer contacts PayPal to file a dispute with the merchant (PayPal's overview: filed through the PayPal Resolution Center).",
     (), (DISPUTES_REF + "#dispute_channel", DISPUTES_OVERVIEW + "#internal-disputes"))
_add(CH, D, "dispute.dispute_channel", "EXTERNAL",
     "The customer contacts their card issuer or bank to request a refund. PayPal's overview says external disputes include both card chargebacks and ACH returns (bank reversals).",
     (), (DISPUTES_REF + "#dispute_channel", DISPUTES_OVERVIEW + "#external-disputes"))
_add(CH, D, "dispute.dispute_channel", "ALERT", "A pre-chargeback alert when the customer contacts their card issuer to request a refund.",
     (), (DISPUTES_REF + "#dispute_channel", DISPUTES_OVERVIEW + "#types-of-external-disputes"))

RS = "disputes_v1.dispute.reason"
_add(RS, D, "dispute.reason", "MERCHANDISE_OR_SERVICE_NOT_RECEIVED", "The customer did not receive the merchandise or service.", (_NOT_RECEIVED,),
     (DISPUTES_WEBHOOKS, DISPUTES_GUIDE))
_add(RS, D, "dispute.reason", "UNAUTHORISED", "The customer did not authorize the purchase of the merchandise or service.", (_NOT_AUTHORIZED,),
     (DISPUTES_REF + "#dispute_info", DISPUTES_GUIDE))
_add(RS, D, "dispute.reason", "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED", None, (), (DISPUTES_GUIDE,),
     "The value is listed in PayPal's Disputes API docs but no PayPal description of it was retrieved; it is not normalised from its name.")
for v in ("CREDIT_NOT_PROCESSED", "DUPLICATE_TRANSACTION", "INCORRECT_AMOUNT", "PAYMENT_BY_OTHER_MEANS", "CANCELED_RECURRING_BILLING", "PROBLEM_WITH_REMITTANCE", "OTHER"):
    _add(RS, D, "dispute.reason", v, None, (), (DISPUTES_REF,), "Listed value; no primary description retrieved; out of Delivery Gate's claim scope.")

LS = "disputes_v1.dispute.dispute_life_cycle_stage"
_add(LS, D, "dispute.dispute_life_cycle_stage", "INQUIRY",
     "The customer and merchant try to resolve the dispute without escalation to PayPal (a 20-day period); PayPal's docs say this occurs only for the INTERNAL channel.",
     (), (DISPUTES_WEBHOOKS, DISPUTES_OVERVIEW + "#dispute-lifecycle-and-stages"))
for v in ("CHARGEBACK", "PRE_ARBITRATION", "ARBITRATION"):
    _add(LS, D, "dispute.dispute_life_cycle_stage", v, None, (), (DISPUTE_SEARCH,), "Listed stage; no per-value description retrieved. A lifecycle stage is not a dispute route.")

DA = "disputes_v1.dispute.dispute_amount"
_add(DA, D, "dispute.dispute_amount", "*", "The amount in the transaction that the customer originally disputed. Customers can dispute only part of a payment, so it may differ from the "
     "total gross or net amount of the original transaction.", (), (DISPUTE_SEARCH,), "")

CA = "orders_v2.capture.amount"
_add(CA, O2, "capture.amount", "*", "The total order amount (with an optional breakdown) for the capture; must be a positive number. It is the capture's amount, not a disputed amount.",
     (), (CAPTURE + "#amount",), "")


def lookup(field_id: str, value: Any) -> Optional[ApiValueSemantics]:
    if not isinstance(value, str):
        return None
    return _ROWS.get((field_id, value)) or _ROWS.get((field_id, "*"))


def ref_for(field_id: str, value: Any) -> Optional[str]:
    row = lookup(field_id, value)
    return row.semantics_id if row else None


def all_rows() -> Tuple[ApiValueSemantics, ...]:
    return tuple(_ROWS[k] for k in sorted(_ROWS))
