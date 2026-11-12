from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from delivery_extraction.schema import FACT_VOCAB, UNKNOWN
from delivery_gate.engine import UNREVIEWED_NOTICE
from paypal_adapter import api_semantics as sem
from delivery_ui.service import Analysis, DeliveryGateService, WhatIfResult

# ---- vocabulary --------------------------------------------------------------------------------------------------------------
FORBIDDEN_PHRASES = (
    "you are protected", "you're protected", "you will be protected", "paypal will approve", "will be approved", "you will win", "you'll win",
    "guaranteed seller protection", "guaranteed protection", "we guarantee", "is guaranteed", "are guaranteed", "guarantees you", "likely to qualify", "will qualify", "approved by paypal", "seller protection applies", "you are covered", "stronger protection",
)

PROTECTION_VIEW: Dict[str, Dict[str, str]] = {
    "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES": {
        "label": "Requirements demonstrated", "tone": "green", "icon": "check",
        "message": "Your available evidence demonstrates the requirements currently modeled. PayPal makes the final decision."},
    "REQUIREMENTS_NOT_DEMONSTRATED": {
        "label": "Requirements not demonstrated", "tone": "amber", "icon": "alert",
        "message": "Your current evidence does not demonstrate all the requirements."},
    "UNKNOWN": {
        "label": "Can't be assessed yet", "tone": "slate", "icon": "help",
        "message": "We don't have enough verified information to assess this requirement."},
    "NOT_COVERED": {
        "label": "Not covered", "tone": "slate", "icon": "info",
        "message": "This type of claim is not covered by the Seller Protection rules currently modeled."},
    "UNSUPPORTED_JURISDICTION": {
        "label": "Outside the rules modeled", "tone": "slate", "icon": "info",
        "message": "Delivery Gate currently models U.S. rules only, so this payment can't be assessed here."},
}
NEEDS_REVIEW_VIEW = {"label": "Needs human review", "tone": "amber", "icon": "review",
                     "message": "This information needs to be checked before it can be relied upon."}
CONTRADICTED_MESSAGE = "These records contain conflicting information."

CHECK_VIEW: Dict[str, Dict[str, str]] = {
    "DEMONSTRATED": {"label": "Demonstrated", "tone": "green", "icon": "check", "message": "Your evidence shows this."},
    "NOT_DEMONSTRATED": {"label": "Not demonstrated", "tone": "amber", "icon": "alert", "message": "Your current evidence does not show this yet."},
    "CONTRADICTED": {"label": "Conflicting", "tone": "red", "icon": "x", "message": CONTRADICTED_MESSAGE},
    "NEEDS_HUMAN_REVIEW": {"label": "Needs review", "tone": "amber", "icon": "review", "message": NEEDS_REVIEW_VIEW["message"]},
    "NOT_APPLICABLE": {"label": "Not applicable", "tone": "slate", "icon": "dash", "message": "This does not apply to this order."},
}
STATEMENT_ONLY_VIEW = {"label": "Your statement only", "tone": "amber", "icon": "person",
                       "message": "Stated by you. No carrier document backs it up, so it is not corroborated."}

REASON_TEXT: Dict[str, str] = {
    "MISSING_FACT": "Nothing on file for this yet.",
    "ONLY_UNREVIEWED_EXTRACTION": "Found in your evidence, but a person has not reviewed it yet, so it can't be relied on.",
    "CONFLICTING_EVIDENCE": "Your records disagree with each other on this.",
    "CONDITION_VIOLATED": "A record shows this condition was not met.",
    "RECORD_PRESENT": "A carrier delivery record is on file.",
    "VALUE_PRESENT": "Present in the evidence.",
    "DATE_AND_STATUS_PRESENT": "The record shows a delivery date and a delivered status.",
    "GRANULARITY_MET": "The address has enough detail to compare.",
    "ADDRESS_MATCH": "The delivery address matches the address you entered from your PayPal transaction details.",
    "ADDRESS_MISMATCH": "The delivery address does not match the address you entered.",
    "ADDRESS_TOO_COARSE": "The address is too general to compare.",
    "DERIVED_FROM_RECIPIENT_ADDRESS": "Taken from the delivery address in the carrier record.",
    "ASSERTED_ONLY": "Stated by you, with no carrier record behind it.",
    "ASSERTED_NOT_SHIPPED_TO_TRANSACTION_ADDRESS": "You stated this was not shipped to the transaction address.",
    "STATUS_NOT_DELIVERED": "The record does not show the package as delivered.",
    "SOURCE_TYPE_NOT_CARRIER": "This evidence is not a carrier document.",
    "RECORD_ASSERTED_ABSENT": "A delivery record was stated not to exist.",
    "VALUE_ALLOWED": "The answer you gave is acceptable for this requirement.",
    "CONDITION_NOT_TRIGGERED": "Nothing reported breaks this condition.",
    "CONDITION_DOES_NOT_APPLY": "This does not apply to this order.",
    "PROVENANCE_UNKNOWN": "Where this came from is not known, so it is not used.",
    "UNKNOWN_PROVENANCE": "Where this came from is not known, so it is not used.",
    "VALUE_UNKNOWN": "The value is unknown.",
    "NOT_SUPPLIED": "Not provided.",
}

REQUIREMENTS: Dict[str, Dict[str, str]] = {
    "proof_of_delivery.record": {"title": "Carrier delivery record", "means": "A record from the carrier (such as a delivery email or tracking record) showing the package was delivered.",
                                 "next": "Ask the carrier for a delivery confirmation and add it here, then have it reviewed."},
    "proof_of_delivery.tracking_number": {"title": "Tracking number", "means": "The delivery record includes a tracking number.",
                                          "next": "Make sure the carrier record you add includes the tracking number."},
    "proof_of_delivery.date_and_status": {"title": "Delivery date and status", "means": "The record shows the package was delivered, and when.",
                                          "next": "Add a carrier record that shows a delivery date and a delivered status."},
    "proof_of_delivery.recipient_address_granularity": {"title": "Delivery address detail", "means": "The delivery address is specific enough to compare (for example city and postcode).",
                                                     "next": "Add a carrier record that shows the full delivery address."},
    "proof_of_delivery.recipient_address_matches": {"title": "Delivery address matches", "means": "The address the carrier delivered to matches the shipping address on your PayPal transaction details.",
                                                    "next": "Check the delivery address against the address on your PayPal transaction details."},
    "ship_to_transaction_address": {"title": "Shipped to the transaction address", "means": "The order was shipped to the shipping address shown on the PayPal transaction details.",
                                    "next": "Confirm the address on your PayPal transaction details and add a carrier record that shows delivery to it."},
    "no_redirect": {"title": "No redirect to another address", "means": "Nothing shows the package was redirected to a different address.",
                    "next": "Tell us whether the shipment was redirected, and add carrier evidence if you have it.",
                    "corroborate": "A carrier tracking record could confirm whether the package was redirected."},
    "timely_response": {"title": "Responded to PayPal on time", "means": "You answered PayPal's requests for documents within the time PayPal asked.",
                        "next": "Tell us whether PayPal has asked for documents and whether you responded in time.",
                        "corroborate": "This is based on your own answer. No carrier document can show it, and PayPal holds the record of your responses."},
    "preorder_ship_timing": {"title": "Pre-order shipping time", "means": "Pre-ordered or made-to-order goods shipped within the time stated in the listing.",
                             "next": "Tell us whether the item shipped within the listed timeframe.",
                             "corroborate": "This is based on your own answer."},
}
ALIASES = {"proof.record": "proof_of_delivery.record", "proof.tracking_number": "proof_of_delivery.tracking_number", "proof.date": "proof_of_delivery.date_and_status",
           "proof.recipient_address_granularity": "proof_of_delivery.recipient_address_granularity", "proof.recipient_address_matches": "proof_of_delivery.recipient_address_matches"}

FACT_LABELS = {"tracking_number": "Tracking number", "carrier_name": "Carrier", "delivery_status": "Delivery status", "delivery_date": "Delivery date",
               "delivery_time": "Delivery time", "shipment_date": "Shipment date", "recipient_address": "Delivery address",
               "intended_ship_to_address": "Address the order was meant for", "signature_present": "Signature", "redirect_reported": "Redirect reported",
               "order_reference": "Order reference"}
KIND_LABELS = {"CARRIER_EMAIL": "Carrier email", "TRACKING_PASTE": "Tracking page text", "MERCHANT_STATEMENT": "Merchant statement",
               "CUSTOMER_MESSAGE": "Customer message", "OTHER": "Other document"}
KIND_ICONS = {"CARRIER_EMAIL": "mail", "TRACKING_PASTE": "truck", "MERCHANT_STATEMENT": "person", "CUSTOMER_MESSAGE": "chat", "OTHER": "file"}
ATTRIBUTION_LABELS = {"CARRIER_STATEMENT": "Written as a statement by the carrier", "MERCHANT_STATEMENT": "Written as a statement by the merchant",
                      "CUSTOMER_STATEMENT_RELAYED": "A customer's statement, relayed", "THIRD_PARTY_STATEMENT": "Written as a statement by a third party",
                      "UNKNOWN": "Who made the statement is not clear"}
MODALITY_LABELS = {"DIRECT": "Stated directly", "REPORTED": "Reported second-hand", "HEDGED": "Hedged (\"I think\", \"probably\")"}
CONFIDENCE_LABELS = {"HIGH": "High", "MEDIUM": "Medium", "LOW": "Low"}
PAYMENT_STATUS = {"COMPLETED": ("Paid", "green"), "PARTIALLY_REFUNDED": ("Partially refunded", "amber"), "REFUNDED": ("Refunded", "slate"),
                  "PENDING": ("Pending", "amber"), "DECLINED": ("Declined", "red"), "FAILED": ("Failed", "red")}
DISPUTE_REASONS = {"MERCHANDISE_OR_SERVICE_NOT_RECEIVED": "Item not received", "UNAUTHORISED": "Unauthorized payment",
                   "MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED": "Not as described", "CREDIT_NOT_PROCESSED": "Credit not processed",
                   "DUPLICATE_TRANSACTION": "Duplicate transaction", "INCORRECT_AMOUNT": "Incorrect amount", "OTHER": "Other reason"}
CHANNELS = {"INTERNAL": "Filed through PayPal", "EXTERNAL": "Filed with the card issuer or bank", "ALERT": "Pre-chargeback alert from the card issuer"}
STAGES = {"INQUIRY": "Inquiry", "CHARGEBACK": "Chargeback", "PRE_ARBITRATION": "Pre-arbitration", "ARBITRATION": "Arbitration"}
SP_LABELS = {"ELIGIBLE": "Eligible", "PARTIALLY_ELIGIBLE": "Partially eligible", "NOT_ELIGIBLE": "Not eligible"}
RESPONSE_LABELS = {"NO_REQUEST_OUTSTANDING": "PayPal has not asked for anything", "RESPONDED_WITHIN_REQUESTED_TIME": "I responded within the time asked",
                   "RESPONSE_LATE_OR_MISSING": "My response was late or missing"}

SOURCE_KINDS = {
    "paypal": {"label": "Reported by PayPal", "tone": "navy"},
    "merchant": {"label": "Provided by you", "tone": "slate"},
    "extracted": {"label": "Found in evidence, not reviewed", "tone": "amber"},
    "unused": {"label": "Found in evidence, not used", "tone": "slate"},
    "reviewed": {"label": "Reviewed carrier document", "tone": "green"},
    "assessment": {"label": "Delivery Gate assessment", "tone": "teal"},
}


# ---- formatting --------------------------------------------------------------------------------------------------------------
def money(value: Optional[str], currency: Optional[str]) -> str:
    if value is None:
        return "Unknown"
    cur = currency or ""
    return f"${value} {cur}".strip() if cur == "USD" else f"{value} {cur}".strip()


def when(iso: Optional[str]) -> str:
    if not iso:
        return "Unknown"
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})", iso)
    if not m:
        return iso
    months = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
    y, mo, d, h, mi = (int(x) for x in m.groups())
    return f"{months[mo - 1]} {d}, {y} · {h:02d}:{mi:02d} UTC"


def short_date(iso: Optional[str]) -> str:
    return when(iso).split(" · ")[0] if iso else "Unknown"


def address_text(a: Any) -> str:
    if not isinstance(a, dict):
        return str(a)
    parts = [a.get("line1"), a.get("line2"), a.get("city"), " ".join(x for x in (a.get("region"), a.get("postal_code")) if x), a.get("country")]
    return ", ".join(p for p in parts if p)


def pretty(fact: str, value: Any) -> str:
    if value is None or value == UNKNOWN:
        return "Unknown"
    if isinstance(value, dict):
        return address_text(value)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    if fact == "delivery_status" and isinstance(value, str):
        return value.replace("_", " ").capitalize()
    return str(value)


def requirement_key(check_id: str) -> str:
    k = check_id.split(".", 1)[1] if "." in check_id else check_id
    return ALIASES.get(k, k)


def find_forbidden(text: str) -> List[str]:
    low = re.sub(r"\s+", " ", text.lower())
    return [p for p in FORBIDDEN_PHRASES if p in low]


# ---- assessment status ---------------------------------------------------------------------------------------------------------
def overall(an: Analysis) -> Dict[str, Any]:
    return overall_for(an.assessment, an.dispute)


def overall_for(a: Any, dispute: Any) -> Dict[str, Any]:
    """The engine's result, in words. `needs_human_review` is the engine's own flag."""
    if a is None:
        return {"key": "NEEDS_ORDER_CHOICE", "label": "Choose the order", "tone": "amber", "icon": "review",
                "message": "The evidence mentions more than one order. Choose which one belongs to this payment.", "engine_value": None,
                "needs_human_review": True}
    p = a.protection_assessment.value
    if p == "UNKNOWN" and a.reason_codes and a.reason_codes[0] == "CLAIM_CATEGORY_MISSING":
        if dispute is None:
            return {"key": "NO_DISPUTE", "label": "No dispute to assess", "tone": "slate", "icon": "info", "engine_value": p, "needs_human_review": False,
                    "message": "No dispute has been reported for this payment, so there is nothing to assess yet."}
        return {"key": "UNKNOWN", **PROTECTION_VIEW["UNKNOWN"], "engine_value": p, "needs_human_review": False,
                "message": "PayPal's reason for this dispute is recorded, but it is not matched to a claim type Delivery Gate models, so no rules were applied."}
    if a.needs_human_review and p in ("REQUIREMENTS_NOT_DEMONSTRATED", "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES"):
        return {"key": "NEEDS_HUMAN_REVIEW", **NEEDS_REVIEW_VIEW, "engine_value": p, "needs_human_review": True}
    v = PROTECTION_VIEW[p]
    return {"key": p, **v, "engine_value": p, "needs_human_review": a.needs_human_review}


def bucket(an: Analysis) -> str:
    o = overall(an)["key"]
    if o in ("NEEDS_HUMAN_REVIEW", "NEEDS_ORDER_CHOICE"):
        return "review"
    if o == "REQUIREMENTS_NOT_DEMONSTRATED":
        return "attention"
    if o == "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES":
        return "ready"
    return "unassessable"


def payment_status(capture: Any) -> Dict[str, Any]:
    o = capture.find("status")
    raw = o.raw_value if o is not None else None
    label, tone = PAYMENT_STATUS.get(raw, (str(raw) if raw else "Not reported", "slate"))
    row = sem.lookup(sem.CS, raw)
    return {"label": label, "tone": tone, "raw": raw, "meaning": row.documented_meaning if row else None}


def summary_row(an: Analysis) -> Dict[str, Any]:
    fx = an.state.fixture
    ov = overall(an)
    d = an.dispute
    reason = d.find("reason") if d else None
    return {"ref": an.ref, "order_ref": fx["order_ref"], "amount": money(an.exposure.original_transaction_value["value"], an.exposure.original_transaction_value["currency"]),
            "payment_status": payment_status(an.capture),
            "dispute": (DISPUTE_REASONS.get(reason.raw_value, reason.raw_value) if reason is not None else "No dispute reported"),
            "has_dispute": d is not None, "assessment": {k: ov[k] for k in ("key", "label", "tone", "icon")}, "bucket": bucket(an),
            "scenarios": fx["scenarios"], "created": short_date(an.capture.find("create_time").raw_value if an.capture.find("create_time") else None)}


def counters(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    out = {"attention": 0, "review": 0, "ready": 0, "unassessable": 0}
    for r in rows:
        out[r["bucket"]] += 1
    return out


# ---- facts, artifacts, provenance ------------------------------------------------------------------------------------------------
def _bridged_by_fact(an: Analysis) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    if an.bridge is None:
        return {}, {}
    return ({b["fact_id"]: b for b in an.bridge.bridged}, {n["fact_id"]: n for n in an.bridge.not_bridged})


def authenticity_view(row: Optional[Dict[str, Any]], reviewer: Optional[str] = None, at: Optional[str] = None) -> Dict[str, str]:
    """Content attribution and SOURCE AUTHENTICITY are different things. UNVERIFIED / REVIEWED come from the bridge's own provenance;
    the UI cannot produce 'VERIFIED' (no carrier-API source exists, and a reviewer cannot grant it)."""
    if row is None:
        return {"key": "NOT_USED", "label": "Not used", "tone": "slate", "detail": "This fact is not used by the assessment."}
    st, auth = row["source_type"], row.get("source_authenticity")
    if st == "CARRIER_DOCUMENT" and auth == "REVIEWED":
        by = f" by {reviewer}" if reviewer else ""
        return {"key": "REVIEWED", "label": "Reviewed", "tone": "green",
                "detail": f"A reviewer{by} attested that the document itself is a genuine carrier document. It has not been independently verified with the carrier."}
    if st == "MERCHANT_STATEMENT":
        return {"key": "MERCHANT_STATEMENT", "label": "Your statement", "tone": "slate",
                "detail": "Recorded as the merchant's own statement. A statement from you is not a carrier document and is never treated as corroborated."}
    return {"key": "UNVERIFIED", "label": "Not reviewed", "tone": "amber",
            "detail": "Read from the text by the extraction step. Nobody has checked it, so the assessment does not rely on it yet."}


def fact_view(an: Analysis, f: Any) -> Dict[str, Any]:
    rows, notb = _bridged_by_fact(an)
    row, nb = rows.get(f.fact_id), notb.get(f.fact_id)
    state, why = "unreviewed", None
    if row:
        state = {"CARRIER_DOCUMENT": "carrier_reviewed", "MERCHANT_STATEMENT": "merchant_statement"}.get(row["source_type"], "unreviewed")
    elif nb:
        r = nb["reason"]
        state = {"REJECTED_BY_REVIEWER": "rejected", "NOT_CONSUMED_BY_ENGINE": "not_used", "NORMALIZED_UNKNOWN_REMAINS_MISSING": "unknown_value",
                 "OTHER_ENTITY": "other_order"}.get(r, "not_used")
        why = {"rejected": "Rejected by a reviewer.",
               "not_used": ("Signature confirmation is not used: PayPal's rules about signatures could not be verified, so they are not modeled."
                            if f.fact == "signature_present" else "No requirement currently modeled uses this fact."),
               "unknown_value": "The value could not be read with certainty, so it stays unknown and is not used.",
               "other_order": "This fact belongs to a different order."}[state]
    rec = an.state.artifacts[f.artifact_id]
    last = next((x for x in reversed(an.state.review_log) if x["artifact_id"] == f.artifact_id and x["mode"] != "undo"), None)
    auth = authenticity_view(row, last["reviewer"] if last else None, last["at"] if last else None)
    source_kind = {"carrier_reviewed": "reviewed", "merchant_statement": "merchant", "unreviewed": "extracted"}.get(state, "unused")
    return {"fact_id": f.fact_id, "fact": f.fact, "label": FACT_LABELS.get(f.fact, f.fact), "value": pretty(f.fact, f.normalized_value), "as_written": f.value,
            "artifact_id": f.artifact_id, "artifact_kind": KIND_LABELS[rec.artifact.declared_kind], "attribution": ATTRIBUTION_LABELS[f.attribution],
            "attribution_key": f.attribution, "modality": MODALITY_LABELS[f.modality], "modality_key": f.modality,
            "ambiguity": bool(f.ambiguity), "ambiguity_note": f.ambiguity_note, "confidence": CONFIDENCE_LABELS.get(f.confidence, f.confidence),
            "span": f.source_span, "span_start": f.span_start, "span_end": f.span_end, "state": state, "state_note": why,
            "authenticity": auth, "source_kind": source_kind, "engine_evidence": FACT_VOCAB[f.fact]["engine"], "entity_ref": f.entity_ref,
            "details": {"fact_id": f.fact_id, "fact_key": f.fact, "normalized_value": f.normalized_value, "extractor": rec.extractor_kind,
                        "engine_note": (nb or {}).get("why"),
                        "artifact_sha256": rec.artifact.sha256, "span_offsets": [f.span_start, f.span_end]}}


def contradictions_view(an: Analysis) -> List[Dict[str, Any]]:
    out = []
    for c in an.contradictions:
        out.append({"id": c.contradiction_id, "label": FACT_LABELS.get(c.fact, c.fact), "needs_human_review": c.needs_human_review, "note": c.note,
                    "values": [{"fact_id": v["fact_id"], "artifact_id": v["artifact_id"], "value": pretty(c.fact, v["normalized_value"]), "span": v["source_span"]}
                               for v in c.values], "message": CONTRADICTED_MESSAGE})
    return out


def artifact_view(an: Analysis, aid: str) -> Dict[str, Any]:
    rec = an.state.artifacts[aid]
    facts = [fact_view(an, f) for f in rec.facts]
    used = [f for f in facts if f["state"] in ("carrier_reviewed", "merchant_statement", "unreviewed") and f["engine_evidence"]]
    contested = {fid for c in an.contradictions for fid in c.fact_ids}
    log = [x for x in an.state.review_log if x["artifact_id"] == aid]
    last = next((x for x in reversed(log) if x["mode"] != "undo"), None)
    if aid in an.state.attestations:
        auth = {"key": "REVIEWED", "label": "Reviewed", "tone": "green",
                "detail": f"{an.state.attestations[aid].reviewer} attested that this document itself is a genuine carrier document"
                          + (f" on {when(last['at'])}" if last else "") + ". It has not been independently verified with the carrier."}
    elif any(f["state"] == "merchant_statement" for f in facts):
        auth = {"key": "MERCHANT_STATEMENT", "label": "Your statement", "tone": "slate",
                "detail": "Recorded as the merchant's own statement. It is not corroborated by a carrier document."}
    elif facts and all(f["state"] in ("rejected", "not_used") for f in facts):
        auth = {"key": "NOTHING_RELIED_ON", "label": "Nothing relied on", "tone": "slate", "detail": "The assessment does not rely on anything in this evidence."}
    elif not used:
        auth = {"key": "NOTHING_TO_REVIEW", "label": "Nothing to review", "tone": "slate", "detail": "No usable facts were found, so there is nothing to review."}
    else:
        auth = {"key": "UNVERIFIED", "label": "Not reviewed", "tone": "amber", "detail": "Nobody has checked this evidence yet, so the assessment does not rely on it."}
    conflict = any(f["fact_id"] in contested for f in facts)
    if rec.status in ("UNAVAILABLE", "FAILED"):
        chip = {"label": "Not read", "tone": "red" if rec.status == "FAILED" else "amber"}
    elif conflict:
        chip = {"label": "Conflict", "tone": "red"}
    elif rec.status == "NO_FACTS":
        chip = {"label": "No usable facts", "tone": "slate"}
    else:
        chip = {"label": auth["label"], "tone": auth["tone"]}
    steps = [{"label": "Read the document", "done": True}, {"label": "Extracted facts", "done": rec.status in ("EXTRACTED", "NO_FACTS")},
             {"label": "Checked against the allowed fact types", "done": rec.result is not None},
             {"label": "Checked for contradictions", "done": rec.result is not None}]
    return {"artifact_id": aid, "kind": rec.artifact.declared_kind, "kind_label": KIND_LABELS[rec.artifact.declared_kind], "icon": KIND_ICONS[rec.artifact.declared_kind],
            "source_label": rec.source_label, "added_at": when(rec.added_at), "added_at_iso": rec.added_at, "text": rec.artifact.text, "extraction_status": rec.status,
            "extraction_message": rec.message, "extractor_kind": rec.extractor_kind,
            "extractor_note": ("Replayed from a recorded extraction. No live model was called." if rec.extractor_kind == "RECORDED_ASSISTANT_OUTPUT"
                               else ("Read by the configured extraction model." if rec.extractor_kind in ("ANTHROPIC_API", "GROQ_API") else None)),
            "facts": facts, "fact_count": len(facts), "rejected_count": len(rec.rejected), "authenticity": auth, "chip": chip,
            "in_conflict": conflict, "reviews": [{**x, "at_text": when(x["at"])} for x in log], "is_sample": rec.recognized_sample, "fixture": rec.fixture, "steps": steps,
            "can_attest": rec.artifact.declared_kind in ("CARRIER_EMAIL", "TRACKING_PASTE"), "sha256": rec.artifact.sha256,
            "usable_fact_count": len(used)}


# ---- requirements ---------------------------------------------------------------------------------------------------------------
def _g(obj: Any, key: str, default: Any = None) -> Any:
    return obj.get(key, default) if isinstance(obj, dict) else getattr(obj, key, default)


def _policy_sources(svc: DeliveryGateService, passage_ids: List[str]) -> List[Dict[str, Any]]:
    out = []
    for pid in passage_ids:
        p = svc.registry.passages.get(pid)
        if not p:
            continue
        src_id = _g(p, "source")
        s = svc.registry.sources.get(src_id)
        out.append({"passage_id": pid, "title": _g(s, "title", src_id), "section": _g(p, "section_locator"), "updated": _g(s, "last_updated"),
                    "url": _g(s, "url"), "review_status": "Policy text not independently reviewed"})
    return out


def requirement_view(svc: DeliveryGateService, an: Analysis, c: Dict[str, Any]) -> Dict[str, Any]:
    key = requirement_key(c["check_id"])
    info = REQUIREMENTS.get(key, {"title": c.get("establishes") or c["check_id"], "means": c.get("establishes") or "", "next": "Review this requirement."})
    stat = c["status"]
    cv = dict(CHECK_VIEW[stat])
    statement_only = stat == "DEMONSTRATED" and c.get("corroboration") == "MERCHANT_ASSERTED_ONLY"
    if statement_only:
        cv = dict(STATEMENT_ONLY_VIEW)
    idx = (an.bridge.evidence_index if an.bridge else {})
    facts_by_id = {f.fact_id: f for f in an.candidates}
    support = []
    for name in c.get("inputs_used", []):
        for fid in idx.get(name, []):
            f = facts_by_id.get(fid)
            if f is not None:
                support.append(fact_view(an, f))
            elif fid.endswith("#attestation"):
                aid = fid.split("#")[0]
                support.append({"fact_id": fid, "label": "Reviewer attestation", "value": "Document attested as genuine", "artifact_id": aid,
                                "artifact_kind": KIND_LABELS[an.state.artifacts[aid].artifact.declared_kind],
                                "authenticity": authenticity_view({"source_type": "CARRIER_DOCUMENT", "source_authenticity": "REVIEWED"},
                                                                  an.state.attestations[aid].reviewer if aid in an.state.attestations else None),
                                "span": None, "state": "carrier_reviewed", "source_kind": "reviewed", "attribution": "Recorded by a reviewer", "ambiguity": False})
    merchant_inputs = [(k, v) for k, v in sorted(an.state.merchant["answers"].items()) if k in c.get("inputs_used", []) and v is not None]
    missing = None
    if stat in ("NOT_DEMONSTRATED", "NEEDS_HUMAN_REVIEW", "CONTRADICTED"):
        missing = REASON_TEXT.get(c["reason_code"], "See details.")
    return {"check_id": c["check_id"], "key": key, "title": info["title"], "means": info["means"], "next": info["next"],
            "corroborate": info.get("corroborate", "A carrier document would back this up if one can show it."), "status": stat, "tone": cv["tone"],
            "label": cv["label"], "icon": cv["icon"], "message": cv["message"], "statement_only": statement_only,
            "reason": REASON_TEXT.get(c["reason_code"], "See details."), "missing": missing, "support": support,
            "merchant_inputs": [{"name": k, "value": (RESPONSE_LABELS.get(v) if k == "response_to_paypal" else pretty(k, v))} for k, v in merchant_inputs],
            "policy_sources": _policy_sources(svc, c.get("passage_ids", [])),
            "interpretation_note": c.get("interpretation_note") if c.get("interpretation") else None,
            "details": {"check_id": c["check_id"], "reason_code": c["reason_code"], "corroboration": c.get("corroboration"), "inputs_used": c.get("inputs_used", []),
                        "passage_ids": c.get("passage_ids", []), "establishes": c.get("establishes")}}


def next_steps(reqs: List[Dict[str, Any]], an: Analysis, ov: Dict[str, Any]) -> List[Dict[str, str]]:
    steps, seen = [], set()

    def add(kind, text):
        if text not in seen:
            seen.add(text)
            steps.append({"kind": kind, "text": text})
    a = an.assessment
    codes = list(a.reason_codes) if a else []
    if ov["key"] == "NEEDS_ORDER_CHOICE":
        add("review", "Choose which order this evidence belongs to.")
    if ov["key"] == "NO_DISPUTE":
        add("info", "Nothing to do until a dispute is reported.")
    if ov["key"] == "UNKNOWN":                                      
        if "CLAIM_CATEGORY_MISSING" in codes and an.dispute is not None:
            r = an.dispute.find("reason")
            add("info", f"PayPal recorded the reason “{DISPUTE_REASONS.get(r.raw_value, r.raw_value) if r else 'unknown'}” for this dispute, but it is not matched to a claim type "
                        "Delivery Gate models, so no rules were applied. Nothing you add changes that.")
        if "ROUTE_MISSING" in codes:
            add("info", "This dispute went to a card issuer or bank. PayPal's records don't tell us the route precisely enough to apply the rules, so nothing more can be assessed here.")
        if "POLICY_STATUS_MAPPING_UNKNOWN" in codes:
            add("info", "PayPal reports a protection status, but how it relates to this claim's policy condition is not established. Nothing you add changes that.")
    if any(r["status"] == "CONTRADICTED" for r in reqs) or an.contradictions:
        add("review", "Check the records that disagree. Delivery Gate shows the conflict but does not decide which record is right.")
    for r in reqs:
        if r["status"] == "NEEDS_HUMAN_REVIEW" or any(s.get("state") == "unreviewed" for s in r["support"]):
            add("review", "Review the evidence that was found but not yet checked, and record whether it is a genuine carrier document.")
    for r in reqs:
        if r["status"] == "NOT_DEMONSTRATED":
            add("add", r["next"])
    for r in reqs:
        if r["statement_only"]:
            add("corroborate", f"“{r['title']}” rests on your own statement. {r['corroborate']}")
    if ov["key"] == "REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES":
        add("info", "Keep your evidence together and respond to PayPal within the time it asks. PayPal makes the final decision.")
    return steps


def exposure_view(an: Analysis) -> Dict[str, Any]:
    e = an.exposure.to_dict()

    def comp(c, label, hint):
        return {"label": label, "hint": hint, "state": c["state"], "text": money(c["value"], c["currency"]) if c["state"] == "OBSERVED" else "Unknown", "reason": c["reason"], "note": c["note"]}
    return {"original": comp(e["original_transaction_value"], "Original transaction value", "What the customer paid, as PayPal reports the capture."),
            "disputed": comp(e["disputed_amount"], "Disputed amount", "What the customer disputed. It can be less than the original amount."),
            "potential": comp(e["potential_seller_exposure"], "Potential seller exposure", "What you could lose. It is not calculated here."), "flags": e["flags"]}


def _paypal_view(an: Analysis) -> Dict[str, Any]:
    cap, d = an.capture, an.dispute
    sp = cap.find("seller_protection.status")
    sp_row = sem.lookup(sem.SPS, sp.raw_value) if sp is not None else None
    cats = cap.find("seller_protection.dispute_categories")
    out = {"payment_status": payment_status(cap), "created": when(cap.find("create_time").raw_value if cap.find("create_time") else None),
           "capture_id": cap.capture_id, "order_id": cap.order_id,
           "seller_protection": ({"label": SP_LABELS.get(sp.raw_value, str(sp.raw_value)), "raw": sp.raw_value, "documented": bool(sp_row),
                                  "meaning": sp_row.documented_meaning if sp_row else None,
                                  "categories": (cats.raw_value if cats is not None else None)} if sp is not None else None),
           "dispute": None}
    if d is not None:
        r, ch, st, amt = d.find("reason"), d.find("dispute_channel"), d.find("dispute_life_cycle_stage"), an.exposure.to_dict()["disputed_amount"]
        out["dispute"] = {"id": d.dispute_id, "reason": DISPUTE_REASONS.get(r.raw_value, r.raw_value) if r else None, "reason_raw": r.raw_value if r else None,
                          "reason_normalised": r.normalized_value if r else None,
                          "channel": CHANNELS.get(ch.raw_value, ch.raw_value) if ch else None, "channel_raw": ch.raw_value if ch else None,
                          "route_known": bool(ch and ch.normalized_value), "stage": STAGES.get(st.raw_value, st.raw_value) if st else None,
                          "created": when(d.find("create_time").raw_value if d.find("create_time") else None),
                          "disputed_amount": money(amt["value"], amt["currency"]) if amt["state"] == "OBSERVED" else "Unknown"}
    return out


def _merchant_view(an: Analysis) -> Dict[str, Any]:
    m = an.state.merchant
    a = m["answers"]
    return {"country": m.get("country"), "address": address_text(m["address"]) if m.get("address") else None, "address_fields": dict(m.get("address") or {}),
            "physical_goods": m.get("physical_goods"),
            "answers": [{"key": "redirect_detected", "label": "Was the shipment redirected to another address?",
                         "value": {True: "Yes, a redirect was requested", False: "No redirect that I know of", None: "Not answered"}[a.get("redirect_detected")], "raw": a.get("redirect_detected")},
                        {"key": "response_to_paypal", "label": "Have you responded to PayPal's requests?",
                         "value": RESPONSE_LABELS.get(a.get("response_to_paypal"), "Not answered"), "raw": a.get("response_to_paypal")},
                        {"key": "shipped_after_advised_not_to_release", "label": "Did you ship after PayPal advised you not to?",
                         "value": {True: "Yes", False: "No", None: "Not answered"}[a.get("shipped_after_advised_not_to_release")], "raw": a.get("shipped_after_advised_not_to_release")}]}


COUNTRY_NAMES = {"US": "the United States"}


def _gate_text(key: str, outcome: str, an: Analysis) -> str:
    c = an.state.merchant.get("country")
    if key == "jurisdiction":
        if outcome == "PASS":
            return f"Your business is based in {COUNTRY_NAMES.get(c, c)}, as you entered. Delivery Gate models U.S. rules."
        if outcome == "UNSUPPORTED_JURISDICTION":
            return "Delivery Gate models U.S. rules only."
        return "Where your business is based has not been entered."
    if key == "route":
        if outcome == "PASS":
            return "The dispute was filed through PayPal."
        if outcome == "UNKNOWN":
            return ("PayPal's records don't tell us precisely how this dispute was filed. A dispute with a card issuer or bank can be a chargeback or a "
                    "bank return, so the rules can't be applied.")
        return "Disputes filed this way are not covered by the rules currently modeled."
    if key == "goods_scope":
        return "These are physical goods, as you entered." if outcome == "PASS" else "Only physical goods are modeled."
    return ""


def _gates_view(an: Analysis) -> List[Dict[str, Any]]:
    a = an.assessment
    if a is None:
        return []
    labels = {"jurisdiction": "Where your business is based", "route": "How the dispute was filed", "goods_scope": "Type of goods"}
    done = {"PASS": ("Within the rules modeled", "green"), "UNKNOWN": ("Not known", "slate"), "NOT_COVERED": ("Not covered", "slate"),
            "UNSUPPORTED_JURISDICTION": ("Outside the rules modeled", "slate")}
    out = []
    for g in a.gates:
        gt = g.gate_id.split(".")[-1]
        label, tone = done.get(g.outcome, (g.outcome.replace("_", " ").capitalize(), "slate"))
        out.append({"key": gt, "label": labels.get(gt, gt), "outcome": label, "tone": tone, "detail": _gate_text(gt, g.outcome, an),
                    "technical": {"gate_id": g.gate_id, "outcome": g.outcome, "reason_code": g.reason_code, "engine_detail": g.detail}})
    return out


CONDITION_TEXT = {"unauth.condition.paypal_mark": ("PayPal's eligibility mark",
                  "For unauthorized-payment claims, the policy requires the payment to be marked “eligible” or “partially eligible” on the PayPal Transaction Details page.")}


def conditions_view(svc: DeliveryGateService, an: Analysis) -> List[Dict[str, Any]]:
    a = an.assessment
    out = []
    for c in (a.policy_conditions if a else []):
        title, means = CONDITION_TEXT.get(c["condition_id"], ("A policy condition", c.get("description", "")))
        unresolved = c["state"] == "UNRESOLVED"
        tok = c.get("observed_value")
        label = SP_LABELS.get(tok, tok) if tok else None
        detail_txt = (f"PayPal's API reports “{label}” for this payment. No PayPal document establishes that this value is the same as the mark the policy refers to, "
                      "so it neither satisfies nor fails the condition and the result stays unresolved." if unresolved and label else
                      "PayPal returned no value for this, so the condition can't be checked." if unresolved else "")
        out.append({"id": c["condition_id"], "title": title, "means": means, "unresolved": unresolved, "outcome": "Can't be resolved" if unresolved else c["state"].replace("_", " ").capitalize(),
                    "tone": "slate" if unresolved else "green", "detail": detail_txt, "policy_sources": _policy_sources(svc, c.get("passage_ids", [])),
                    "technical": {"condition_id": c["condition_id"], "state": c["state"], "observation": c.get("observation"), "observed_value": tok,
                                  "mapping": c.get("POLICY_STATUS_MAPPING"), "mapping_note": c.get("mapping_note")}})
    return out


def detail(svc: DeliveryGateService, an: Analysis) -> Dict[str, Any]:
    fx, ov = an.state.fixture, overall(an)
    a = an.assessment
    reqs = [requirement_view(svc, an, c.to_dict() if hasattr(c, "to_dict") else c) for c in (a.checks if a else [])]
    missing = [{"title": r["title"], "reason": r["missing"], "tone": r["tone"], "kind": "missing"} for r in reqs if r["status"] == "NOT_DEMONSTRATED"]
    arts = [artifact_view(an, aid) for aid in an.state.artifacts]
    gates = _gates_view(an)
    uncorr = [r["title"] for r in reqs if r["statement_only"]]
    unknown_inputs = []
    if a is not None:
        for k, v in a.observed_inputs.items():
            if isinstance(v, dict) and v.get("state") in ("NOT_SUPPLIED", "UNKNOWN") and k in ("transaction_details_address", "route", "claim_category"):
                unknown_inputs.append(k)
    return {"ref": an.ref, "order_ref": fx["order_ref"], "merchant_name": svc.merchant_name, "overall": ov, "summary": summary_row(an),
            "scenario": {"title": fx["scenario_title"], "summary": fx["scenario_summary"], "numbers": fx["scenarios"]},
            "paypal": _paypal_view(an), "live_paypal": an.state.external_paypal, "merchant": _merchant_view(an), "conditions": conditions_view(svc, an), "exposure": exposure_view(an), "gates": gates, "requirements": reqs,
            "evidence": arts, "contradictions": contradictions_view(an), "missing": missing, "statement_only": uncorr,
            "next_steps": next_steps(reqs, an, ov), "unknown_inputs": unknown_inputs,
            "display_notice": a.display_notice if a else UNREVIEWED_NOTICE, "policy_status": a.policy_status if a else "UNREVIEWED",
            "paypal_acceptance": a.paypal_acceptance if a else "NOT_ESTABLISHED",
            "unknowns": [{"id": u["id"], "text": u["text"]} for u in (a.unknowns if a else [])],
            "not_modeled": [{"id": n["id"], "text": n["reason"]} for n in (a.not_modeled if a else [])],
            "digest": a.digest if a else None,
            "events": [{**e, "at_text": when(e["at"])} for e in sorted(an.state.events, key=lambda e: e["at"], reverse=True)],
            "entities": an.entities, "needs_entity_choice": an.needs_entity_choice, "entity_ref": an.state.entity_ref,
            "counts": {"met": sum(r["status"] == "DEMONSTRATED" and not r["statement_only"] for r in reqs),
                       "statement_only": len(uncorr), "not_met": sum(r["status"] == "NOT_DEMONSTRATED" for r in reqs),
                       "conflict": sum(r["status"] == "CONTRADICTED" for r in reqs), "review": sum(r["status"] == "NEEDS_HUMAN_REVIEW" for r in reqs),
                       "total": sum(r["status"] != "NOT_APPLICABLE" for r in reqs)}}


def what_if_view(svc: DeliveryGateService, an: Analysis, res: WhatIfResult) -> Dict[str, Any]:
    r = res.report
    current_ids = {b["fact_id"] for b in (an.bridge.bridged if an.bridge else [])}
    before, after = overall_for(r.current, an.dispute), overall_for(r.counterfactual, an.dispute)
    changes = []
    for c in r.changed_requirements:
        key = requirement_key(c["check_id"])
        info = REQUIREMENTS.get(key, {"title": c.get("requirement") or c["check_id"]})
        b, a2 = CHECK_VIEW[c["before"][0]], CHECK_VIEW[c["after"][0]]
        changes.append({"title": info["title"], "before": {"label": b["label"], "tone": b["tone"]}, "after": {"label": a2["label"], "tone": a2["tone"]},
                        "reason": REASON_TEXT.get(c["after"][1], "")})
    return {"option": {"id": res.option.option_id, "label": res.option.label, "detail": res.option.detail, "kind": res.option.kind, "artifact_id": res.option.artifact_id},
            "before": before, "after": after, "changed": bool(r.result_change["changed"]), "changes": changes,
            "still_blocking": [REQUIREMENTS.get(requirement_key(x), {"title": x})["title"] for x in r.still_blocking],
            "added": [{"label": FACT_LABELS.get(b["fact"], "Reviewer attestation" if b["fact"] == "reviewer_attestation" else b["fact"]),
                       "value": ("Document attested as genuine" if b["fact"] == "reviewer_attestation" else pretty(b["fact"], b["engine_value"])),
                       "artifact_id": b["artifact_id"]}
                      for b in res.hypothetical_bridge.bridged if b["fact_id"] not in current_ids],
            "hypothetical_notice": "Nothing has changed on this payment until the evidence is actually added and reviewed.",
            "final_notice": "PayPal makes the final decision.", "digests": {"current": r.current.digest, "hypothetical": r.counterfactual.digest}}
