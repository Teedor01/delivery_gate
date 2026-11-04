from __future__ import annotations

from dataclasses import dataclass, asdict
from enum import Enum
from typing import Any, Dict, Optional, Tuple

CAPTURE_DEF = "https://developer.paypal.com/api/orders/v2/definitions/capture"
SP_DEF = "https://developer.paypal.com/api/orders/v2/definitions/seller_protection"
ORDERS_SPEC = "https://developer.paypal.com/api/orders/v2/schema.json"
DISPUTE_REPORT = "https://developer.paypal.com/docs/reports/sftp-reports/dispute-detail-custom/"
SP_POLICY = "https://www.paypal.com/us/legalhub/paypal/seller-protection"


class Semantics(str, Enum):
    OBSERVED_AND_DOCUMENTED = "OBSERVED_AND_DOCUMENTED"
    OBSERVED_SEMANTICS_UNKNOWN = "OBSERVED_SEMANTICS_UNKNOWN"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    NOT_VERIFIED = "NOT_VERIFIED"


class Handoff(str, Enum):
    ENGINE_FACT = "ENGINE_FACT"
    OBSERVATION_ONLY = "OBSERVATION_ONLY"
    WITHHELD = "WITHHELD"
    NOT_COLLECTED = "NOT_COLLECTED"


@dataclass(frozen=True)
class FieldSpec:
    path: str
    semantics: Semantics
    doc_ref: str
    documented_meaning: str           
    delivery_gate_fact: Optional[str] 
    engine_consumer: Optional[str]     
    handoff: Handoff
    policy_equivalence: str = "NOT_ESTABLISHED"      
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["semantics"], d["handoff"] = self.semantics.value, self.handoff.value
        return d


S, H = Semantics, Handoff
DISPUTES_REF = "https://developer.paypal.com/docs/api/customer-disputes/v1/"
DISPUTES_OVERVIEW = "https://developer.paypal.com/disputes/overview"
DISPUTE_SEARCH = "https://developer.paypal.com/api/customer-disputes/v1/definitions/dispute_search"
INVENTORY: Tuple[FieldSpec, ...] = (
    FieldSpec("capture.id", S.OBSERVED_AND_DOCUMENTED, CAPTURE_DEF, "The PayPal-generated ID for the captured payment.",
              None, None, H.OBSERVATION_ONLY, "NOT_APPLICABLE", "Identifier only: used for provenance references, the case id and (by equality only) dispute linkage."),
    FieldSpec("capture.status", S.OBSERVED_AND_DOCUMENTED, CAPTURE_DEF,
              "Status of the captured payment; each value is described (COMPLETED = funds credited to the payee's PayPal account; PARTIALLY_REFUNDED / REFUNDED = "
              "refunded to the payer; PENDING, DECLINED, FAILED). Per-value meanings are in api_semantics.",
              None, None, H.OBSERVATION_ONLY, "NOT_APPLICABLE", "No current rule consumes payment status. Refund states are not reflected in the engine."),
    FieldSpec("capture.status_details.reason", S.OBSERVED_AND_DOCUMENTED, CAPTURE_DEF,
              "Reason a capture is PENDING or DENIED; includes BUYER_COMPLAINT (payer disputed with PayPal) and CHARGEBACK (funds reversed after the payer disputed with the issuer).",
              None, None, H.OBSERVATION_ONLY,
              note="Observation only. It is present only for some statuses and is not read as a dispute route."),
    FieldSpec("capture.amount.value", S.OBSERVED_AND_DOCUMENTED, CAPTURE_DEF,
              "Decimal string; the capture's total amount (item_total + tax + shipping + handling + insurance - discounts when a breakdown is given); must be positive.",
              "transaction_amount", "engine.snad_exposure (the Phase 1 rule treats it as a conservative lower bound of exposure)", H.WITHHELD, "NOT_APPLICABLE",
              "Recorded as 'original transaction value' in the exposure view and NOT handed to the engine. PayPal documents that a dispute's amount may be less than the original "
              "transaction's gross or net amount, so the capture amount is not a minimum disputed exposure. Changing the engine's treatment needs a separately reviewed policy change."),
    FieldSpec("capture.amount.currency_code", S.OBSERVED_AND_DOCUMENTED, CAPTURE_DEF, "Three-character ISO-4217 currency code.",
              "currency", "engine.snad_exposure (currency label)", H.ENGINE_FACT, "NOT_APPLICABLE",
              "Handed over as a label. PayPal's Dispute Detail report documents that a disputed currency matches the original payment's currency."),
    FieldSpec("capture.seller_protection", S.OBSERVED_AND_DOCUMENTED, SP_DEF,
              "The level of protection offered as defined by PayPal Seller Protection for Merchants. Optional object.", None, None, H.OBSERVATION_ONLY, "NOT_APPLICABLE"),
    FieldSpec("capture.seller_protection.status", S.OBSERVED_AND_DOCUMENTED, CAPTURE_DEF + "#seller_protection.status",
              "API semantics (documented, see api_semantics.py): whether the transaction is eligible for seller protection. ELIGIBLE = the seller's PayPal balance remains intact if the "
              "customer claims they did not receive an item or the account holder claims they did not authorize the payment; PARTIALLY_ELIGIBLE = item-not-received only; "
              "NOT_ELIGIBLE = not eligible for seller protection.",
              "paypal_seller_protection_status", "engine.eval_policy_condition (opaque token, resolves to UNRESOLVED)", H.ENGINE_FACT,
              "NOT_ESTABLISHED",
              note="The API meaning is recorded in the API-semantics layer. Equivalence with the Transaction Details eligibility mark that the legal policy names is NOT established: no "
                   "PayPal document links them, the descriptions concern the PayPal balance, the policy says PayPal decides at dispute time, and another PayPal surface (the Dispute Detail report) "
                   "describes a similarly named value with different scope. The token is therefore passed to the engine unchanged and opaque."),
    FieldSpec("capture.seller_protection.dispute_categories[]", S.OBSERVED_AND_DOCUMENTED, SP_DEF,
              "Array of conditions covered for the transaction; documented values ITEM_NOT_RECEIVED, UNAUTHORIZED_TRANSACTION.",
              None, None, H.OBSERVATION_ONLY,
              note="Observed and preserved. No engine fact or consumer exists for it; adding one would be new policy interpretation."),
    FieldSpec("capture.seller_receivable_breakdown.paypal_fee", S.OBSERVED_SEMANTICS_UNKNOWN, CAPTURE_DEF,
              "Typed only as a currency+amount ('money'); no primary doc retrieved states what it represents.",
              "paypal_fee_amount", "engine.snad_exposure (documented additional costs)", H.WITHHELD,
              note="An engine fact name exists, but equating them from the field NAME is the inference the rules forbid."),
    FieldSpec("capture.create_time / capture.update_time", S.OBSERVED_SEMANTICS_UNKNOWN, CAPTURE_DEF,
              "Documented only as an RFC 3339 date-time; which event each timestamp marks is not stated.", None, None, H.OBSERVATION_ONLY,
              note="Recorded raw. Not used for any window or timer (no such rule is modelled)."),
    FieldSpec("purchase_units[].shipping.address.*", S.NOT_VERIFIED, ORDERS_SPEC,
              "Appears in primary samples; no definition text retrieved this session.",
              "transaction_details_address", "engine: ship-to-transaction-address and recipient-address checks", H.WITHHELD,
              note="PayPal does not state that the order's shipping address IS the address on the Transaction Details page. Recorded (raw plus a key-renamed candidate) "
                   "and never handed to the engine."),
    FieldSpec("order.payment_source.<type>", S.NOT_VERIFIED, ORDERS_SPEC, "A key naming the payment source type appears in samples; no definition retrieved.",
              "funding_source", "engine route/funding consistency gate", H.WITHHELD,
              note="The type key does not say whether a wallet payment was funded by card, bank or balance, which is what funding_source means."),
    FieldSpec("capture funding instrument (card / bank / balance)", S.NOT_AVAILABLE, CAPTURE_DEF,
              "The retrieved capture definition has no field exposing the funding instrument of a wallet payment.",
              "funding_source", "engine route/funding consistency gate", H.NOT_COLLECTED, note="funding_source stays missing; the engine reports it as an open UNKNOWN."),
    FieldSpec("merchant account country (independently verified PayPal account data)", S.NOT_VERIFIED, "https://developer.paypal.com/platforms/seller-onboarding/before-payment",
              "PayPal documents a partner-only 'show seller status' call (needs the ACCESS_MERCHANT_INFORMATION permission) whose sample response includes country and primary_currency. "
              "What 'country' denotes, and whether a direct-merchant integration can call it, was not established.",
              "merchant_account_country", "engine jurisdiction gate", H.NOT_COLLECTED,
              note="Not implemented. Jurisdiction is merchant-asserted (MERCHANT_INPUT / MERCHANT_ASSERTED) or missing, never presented as PayPal-verified."),
    FieldSpec("order.purchase_units[].items[].category (PHYSICAL_GOODS)", S.NOT_VERIFIED, ORDERS_SPEC,
              "Appears in create-order REQUEST samples (merchant-declared); response behaviour not checked.",
              "physical_goods", "engine goods-scope gate", H.NOT_COLLECTED, note="Merchant-declared, not a PayPal observation."),
    FieldSpec("payer.* (payer_id, name, email, address.country_code)", S.NOT_VERIFIED, ORDERS_SPEC,
              "Appear in samples; no definition retrieved.", None, None, H.NOT_COLLECTED, "NOT_APPLICABLE", "No current rule consumes payer data (data minimisation)."),
    FieldSpec("dispute.reason (Disputes API)", S.OBSERVED_AND_DOCUMENTED, DISPUTES_REF + "#dispute_info",
              "Enum of dispute reasons. Primary descriptions retrieved for MERCHANDISE_OR_SERVICE_NOT_RECEIVED (customer did not receive the merchandise or service) and UNAUTHORISED "
              "(customer did not authorize the purchase). No primary description retrieved for MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED or the other values.",
              "claim_category", "engine claim gate", H.ENGINE_FACT, "NOT_APPLICABLE",
              "Raw value always preserved. Normalised through CLAIM_REASON_TABLE_V1 only where established (NOT_RECEIVED, UNAUTHORISED); NOT_AS_DESCRIBED is not normalised yet; other reasons stay unknown."),
    FieldSpec("dispute.dispute_life_cycle_stage", S.OBSERVED_AND_DOCUMENTED, DISPUTES_REF,
              "The stage in the dispute lifecycle: INQUIRY, CHARGEBACK, PRE_ARBITRATION, ARBITRATION. Only INQUIRY has a retrieved description.",
              None, None, H.OBSERVATION_ONLY, "NOT_APPLICABLE", "Separate field. Never merged with reason or route; the engine has no lifecycle fact."),
    FieldSpec("dispute.dispute_channel", S.OBSERVED_AND_DOCUMENTED, DISPUTES_REF + "#dispute_channel",
              "Where the customer created the dispute: INTERNAL (contacts PayPal), EXTERNAL (contacts their card issuer or bank), ALERT (pre-chargeback alert). PayPal's overview classes "
              "disputes as internal or external, and external includes card chargebacks and ACH returns.",
              "route", "engine route gate", H.ENGINE_FACT, "NOT_APPLICABLE",
              "The only explicitly exposed and documented route-like field. INTERNAL -> PAYPAL_DISPUTE; EXTERNAL and ALERT are not normalised because external disputes include ACH returns, for which the "
              "retrieved policy establishes no Item Not Received handling. Never inferred from the claim reason."),
    FieldSpec("dispute.dispute_amount", S.OBSERVED_AND_DOCUMENTED, DISPUTE_SEARCH,
              "The amount in the transaction that the customer originally disputed; may differ from the total gross or net amount of the original transaction (partial disputes).",
              None, None, H.OBSERVATION_ONLY, "NOT_APPLICABLE", "Held in the exposure view as 'disputed amount'. No engine consumer exists and none is added."),
    FieldSpec("dispute.disputed_transactions[].seller_transaction_id / gross_amount", S.NOT_VERIFIED, DISPUTES_REF,
              "Appear in Disputes API samples; no definition retrieved.", None, None, H.OBSERVATION_ONLY, "NOT_APPLICABLE",
              "Used for linkage by identifier equality only: PayPal's docs do not state that a capture id and a seller_transaction_id share a namespace."),
    FieldSpec("dispute.status / dispute_state / create_time / update_time", S.OBSERVED_SEMANTICS_UNKNOWN, DISPUTES_REF,
              "Enums and timestamps are listed; per-value meanings were not retrieved.", None, None, H.OBSERVATION_ONLY, "NOT_APPLICABLE", "Recorded raw; no consumer."),
    FieldSpec("Disputes webhooks (CUSTOMER.DISPUTE.CREATED / UPDATED / RESOLVED)", S.OBSERVED_AND_DOCUMENTED, "https://developer.paypal.com/docs/disputes/webhooks",
              "PayPal notifies the merchant of dispute events; CREATED includes the dispute id. Notifications carry a signature verified through POST /v1/notifications/verify-webhook-signature "
              "(five transmission headers; verification_status SUCCESS or FAILURE).",
              None, None, H.NOT_COLLECTED, "NOT_APPLICABLE",
              "Trigger only: a verified notification requests a fresh Disputes API read; its payload yields no facts. No live verifier is built."),
    FieldSpec("Dispute Detail Custom report (case type/reason, Seller Protection, disputed amount)", S.OBSERVED_AND_DOCUMENTED, DISPUTE_REPORT,
              "Per-claim SFTP report rows for approved merchants: case type, reason, a Seller Protection column (Eligible / Partially Eligible Unauth Only / Ineligible), the disputed amount "
              "(may be below the transaction amount) and the disputed transaction id.",
              None, None, H.NOT_COLLECTED, "NOT_APPLICABLE",
              "Supplementary / reconciliation source only. Not a dependency of any assessment."),
    FieldSpec("Transaction Search API (protection_eligibility etc.) and the Transaction Details page label", S.NOT_VERIFIED, SP_POLICY,
              "Not retrieved. The policy text itself refers to the label on the Transaction Details page.", None, None,
              H.NOT_COLLECTED, note="Possibly the only place the policy's own eligibility label is exposed; unchecked."),
)

DOCUMENTED_STATUS_TOKENS = frozenset({"ELIGIBLE", "PARTIALLY_ELIGIBLE", "NOT_ELIGIBLE"})
DOCUMENTED_DISPUTE_CATEGORIES = frozenset({"ITEM_NOT_RECEIVED", "UNAUTHORIZED_TRANSACTION"})
DOCUMENTED_CAPTURE_STATUSES = frozenset({"COMPLETED", "DECLINED", "PARTIALLY_REFUNDED", "PENDING", "REFUNDED", "FAILED"})
DOCUMENTED_STATUS_REASONS = frozenset({
    "BUYER_COMPLAINT", "CHARGEBACK", "ECHECK", "INTERNATIONAL_WITHDRAWAL", "OTHER", "PENDING_REVIEW",
    "RECEIVING_PREFERENCE_MANDATES_MANUAL_ACTION", "REFUNDED", "TRANSACTION_APPROVED_AWAITING_FUNDING", "UNILATERAL",
    "VERIFICATION_REQUIRED", "DECLINED_BY_RISK_FRAUD_FILTERS"})


def inventory_rows():
    return [f.to_dict() for f in INVENTORY]


def engine_fact_chains():
    """PayPal API field -> documented meaning -> Delivery Gate fact -> engine consumer, for every field that reaches the engine."""
    return [{"paypal_field": f.path, "documented_meaning": f.documented_meaning, "delivery_gate_fact": f.delivery_gate_fact,
             "engine_consumer": f.engine_consumer, "policy_equivalence": f.policy_equivalence, "doc_ref": f.doc_ref}
            for f in INVENTORY if f.handoff == Handoff.ENGINE_FACT]
