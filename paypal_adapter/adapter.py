"""PayPal observation adapter (Orders v2 capture). Pure observation: it records WHAT PayPal returned and WHERE, nothing about policy.

Rules enforced here (each has a test and at least one mutation check):
  * every value keeps its raw form, field path, documentation reference, response hash and observation time (if the caller supplied one);
  * a missing field is recorded as ABSENT and never receives a default;
  * an unknown enum token is preserved exactly and flagged; it is never normalised into a meaning;
  * malformed structure raises MalformedPayPalResponse and yields no partial output;
  * output is a pure function of the input: nothing is generated (no clock, no random ids), so it is deterministic.
This module imports nothing from delivery_gate.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Tuple

from . import api_semantics as sem
from .inventory import (CAPTURE_DEF, SP_DEF, ORDERS_SPEC, DOCUMENTED_CAPTURE_STATUSES, DOCUMENTED_DISPUTE_CATEGORIES,
                        DOCUMENTED_STATUS_REASONS, DOCUMENTED_STATUS_TOKENS, Semantics)

ORIGINS = ("FIXTURE", "SANDBOX", "PRODUCTION")
API_NAME = "PayPal Orders v2"
SOURCE = "PAYPAL_API"
AMOUNT_RE = re.compile(r"^((-?[0-9]+)|(-?([0-9]+)?[.][0-9]+))$")      # the pattern PayPal documents for money.value
CURRENCY_RE = re.compile(r"^[A-Z]{3}$")
ADDRESS_KEY_MAP = {"address_line_1": "line1", "address_line_2": "line2", "admin_area_2": "city", "admin_area_1": "region",
                   "postal_code": "postal_code", "country_code": "country"}


class MalformedPayPalResponse(ValueError):
    def __init__(self, reasons):
        self.reasons = list(reasons)
        super().__init__("; ".join(self.reasons))


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ---- records ---------------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Observation:
    observation_id: str
    source: str
    origin: str                 # FIXTURE | SANDBOX | PRODUCTION: a fixture is never presented as a live response
    api: str
    doc_ref: str
    resource_ref: str
    field_path: str             # full path inside the response
    local_path: str             # path relative to the capture
    raw_value: Any
    normalized_value: Any       # None when no deterministic normalisation exists or the raw value is not usable
    normalization: str
    semantics: str              # Semantics value from the inventory
    enum_state: Optional[str]   # DOCUMENTED_TOKEN | UNDOCUMENTED_TOKEN for enum fields
    observed_at: Optional[str]  # supplied by the caller from the actual retrieval; never generated here
    response_sha256: str
    api_semantics_ref: Optional[str] = None   # id of the documented-meaning row in api_semantics (what PayPal says it means); NOT a policy mapping

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class Absence:
    field_path: str
    local_path: str
    reason: str = "ABSENT_IN_RESPONSE"

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class Anomaly:
    field_path: str
    kind: str
    detail: str
    raw_value: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass(frozen=True)
class CaptureObservation:
    capture_id: str
    order_id: Optional[str]
    resource_ref: str
    origin: str
    observed_at: Optional[str]
    response_sha256: str
    observations: Tuple[Observation, ...]
    absent: Tuple[Absence, ...]
    anomalies: Tuple[Anomaly, ...]

    def find(self, local_path: str) -> Optional[Observation]:
        for o in self.observations:
            if o.local_path == local_path:
                return o
        return None

    def to_dict(self) -> Dict[str, Any]:
        return {"capture_id": self.capture_id, "order_id": self.order_id, "resource_ref": self.resource_ref, "origin": self.origin,
                "observed_at": self.observed_at, "response_sha256": self.response_sha256,
                "observations": [o.to_dict() for o in self.observations], "absent": [a.to_dict() for a in self.absent],
                "anomalies": [a.to_dict() for a in self.anomalies]}


@dataclass(frozen=True)
class OrderObservation:
    order_id: str
    origin: str
    observed_at: Optional[str]
    response_sha256: str
    captures: Tuple[CaptureObservation, ...]

    def select_capture(self, capture_id: Optional[str] = None) -> CaptureObservation:
        if capture_id is not None:
            for c in self.captures:
                if c.capture_id == capture_id:
                    return c
            raise KeyError(f"no capture {capture_id!r} in order {self.order_id}")
        if len(self.captures) != 1:
            raise MalformedPayPalResponse([f"order {self.order_id} has {len(self.captures)} captures; select one explicitly (never guessed)"])
        return self.captures[0]

    def to_dict(self) -> Dict[str, Any]:
        return {"order_id": self.order_id, "origin": self.origin, "observed_at": self.observed_at,
                "response_sha256": self.response_sha256, "captures": [c.to_dict() for c in self.captures]}


# ---- normalisation hooks (module-level so mutation checks can sabotage each one) --------------------------------------
def _norm_amount_value(raw: Any) -> Tuple[Optional[str], Optional[Tuple[str, str]]]:
    if not isinstance(raw, str):
        return None, ("TYPE_NOT_STRING", "money.value is documented as a string")
    if not AMOUNT_RE.match(raw):
        return None, ("PATTERN_MISMATCH", "does not match the documented money.value pattern")
    try:
        d = Decimal(raw)
    except InvalidOperation:
        return None, ("PATTERN_MISMATCH", "not a decimal")
    if d <= 0:
        return None, ("NOT_POSITIVE", "the capture amount is documented as a positive number")
    return str(d), None


def _norm_currency(raw: Any) -> Tuple[Optional[str], Optional[Tuple[str, str]]]:
    if not isinstance(raw, str) or not CURRENCY_RE.match(raw):
        return None, ("NOT_ISO_4217_SHAPE", "documented as a three-character ISO-4217 code")
    return raw, None


def _norm_status_token(raw: Any) -> Tuple[Optional[str], Optional[str], Optional[Tuple[str, str]]]:
    """The seller-protection token is OPAQUE: normalised value == raw value (no case folding, no mapping).
    Only a label says whether PayPal documents that token; the label carries no meaning."""
    if not isinstance(raw, str) or not raw:
        return None, None, ("TYPE_NOT_NONEMPTY_STRING", "seller_protection.status is documented as an enum string")
    if raw in DOCUMENTED_STATUS_TOKENS:
        return raw, "DOCUMENTED_TOKEN", None
    return raw, "UNDOCUMENTED_TOKEN", ("UNDOCUMENTED_ENUM_VALUE", "token is not in PayPal's documented enum; kept verbatim, no meaning attached")


def _norm_categories(raw: Any) -> Tuple[Optional[List[str]], Optional[Tuple[str, str]]]:
    if not isinstance(raw, list) or not all(isinstance(x, str) for x in raw):
        return None, ("TYPE_NOT_STRING_ARRAY", "dispute_categories is documented as an array of enum strings")
    unknown = sorted({x for x in raw if x not in DOCUMENTED_DISPUTE_CATEGORIES})
    if unknown:
        return None, ("UNDOCUMENTED_ENUM_VALUE", f"undocumented category token(s) {unknown}; raw array preserved, no normalisation")
    return sorted(set(raw)), None


def _norm_address(raw: Any) -> Tuple[Optional[Dict[str, str]], Optional[Tuple[str, str]]]:
    """A key-renamed CANDIDATE only: the renaming rests on primary samples, not a retrieved definition (see inventory)."""
    if not isinstance(raw, dict):
        return None, ("TYPE_NOT_OBJECT", "shipping.address should be an object")
    bad = sorted(k for k in raw if k not in ADDRESS_KEY_MAP)
    if bad or not all(isinstance(v, str) for v in raw.values()):
        return None, ("UNEXPECTED_ADDRESS_SHAPE", f"unexpected keys {bad} or non-string values; raw preserved, nothing normalised")
    return {ADDRESS_KEY_MAP[k]: raw[k] for k in ADDRESS_KEY_MAP if k in raw and raw[k] != ""}, None


# ---- observation construction -------------------------------------------------------------------------------------------
@dataclass
class _Ctx:
    origin: str
    resource_ref: str
    response_sha: str
    observed_at: Optional[str]
    base: str                                  # path of the resource inside the response
    obs: List[Observation]
    absent: List[Absence]
    anomalies: List[Anomaly]
    api: str = API_NAME


def _make_obs(ctx: _Ctx, local: str, raw: Any, normalized: Any, normalization: str, semantics: Semantics, doc_ref: str,
              enum_state: Optional[str] = None, full_path: Optional[str] = None, api_semantics_ref: Optional[str] = None) -> Observation:
    path = full_path or f"{ctx.base}.{local}"
    return Observation(observation_id=f"{ctx.resource_ref}#{local}", source=SOURCE, origin=ctx.origin, api=ctx.api, doc_ref=doc_ref,
                       resource_ref=ctx.resource_ref, field_path=path, local_path=local, raw_value=raw, normalized_value=normalized,
                       normalization=normalization, semantics=semantics.value, enum_state=enum_state, observed_at=ctx.observed_at,
                       response_sha256=ctx.response_sha, api_semantics_ref=api_semantics_ref)


def _absent(ctx: _Ctx, local: str, full_path: Optional[str] = None) -> None:
    ctx.absent.append(Absence(full_path or f"{ctx.base}.{local}", local))


def _anomaly(ctx: _Ctx, local: str, anomaly: Tuple[str, str], raw: Any, full_path: Optional[str] = None) -> None:
    ctx.anomalies.append(Anomaly(full_path or f"{ctx.base}.{local}", anomaly[0], anomaly[1], raw))


def _extract_money(ctx: _Ctx, parent: Any, local: str, doc_ref: str, semantics: Semantics, sem_field: Optional[str] = None) -> None:
    """local is e.g. 'amount' -> records local.value and local.currency_code."""
    if parent is None:
        _absent(ctx, local)
        return
    if not isinstance(parent, dict):
        _anomaly(ctx, local, ("TYPE_NOT_OBJECT", "money object expected"), parent)
        return
    if "value" not in parent:
        _absent(ctx, f"{local}.value")
    else:
        n, a = _norm_amount_value(parent["value"])
        ctx.obs.append(_make_obs(ctx, f"{local}.value", parent["value"], n, "DECIMAL_STRING" if n is not None else "NONE", semantics, doc_ref,
                                 api_semantics_ref=sem.ref_for(sem_field, "*") if sem_field else None))
        if a:
            _anomaly(ctx, f"{local}.value", a, parent["value"])
    if "currency_code" not in parent:
        _absent(ctx, f"{local}.currency_code")
    else:
        n, a = _norm_currency(parent["currency_code"])
        ctx.obs.append(_make_obs(ctx, f"{local}.currency_code", parent["currency_code"], n, "NONE", semantics, doc_ref))
        if a:
            _anomaly(ctx, f"{local}.currency_code", a, parent["currency_code"])


def _extract_seller_protection(ctx: _Ctx, cap: Dict[str, Any]) -> None:
    if "seller_protection" not in cap:
        _absent(ctx, "seller_protection")
        return
    sp = cap["seller_protection"]
    if not isinstance(sp, dict):
        _anomaly(ctx, "seller_protection", ("TYPE_NOT_OBJECT", "seller_protection is documented as an object"), sp)
        return
    if "status" not in sp:
        _absent(ctx, "seller_protection.status")
    else:
        n, state, a = _norm_status_token(sp["status"])
        ctx.obs.append(_make_obs(ctx, "seller_protection.status", sp["status"], n, "NONE_OPAQUE_TOKEN", Semantics.OBSERVED_AND_DOCUMENTED,
                                 CAPTURE_DEF, enum_state=state, api_semantics_ref=sem.ref_for(sem.SPS, sp["status"])))
        if a:
            _anomaly(ctx, "seller_protection.status", a, sp["status"])
    if "dispute_categories" not in sp:
        _absent(ctx, "seller_protection.dispute_categories")
    else:
        n, a = _norm_categories(sp["dispute_categories"])
        ctx.obs.append(_make_obs(ctx, "seller_protection.dispute_categories", sp["dispute_categories"], n,
                                 "SORTED_SET" if n is not None else "NONE", Semantics.OBSERVED_AND_DOCUMENTED, SP_DEF))
        if a:
            _anomaly(ctx, "seller_protection.dispute_categories", a, sp["dispute_categories"])


def _extract_enum(ctx: _Ctx, parent: Dict[str, Any], key: str, local: str, documented: frozenset, sem_field: Optional[str] = None) -> None:
    if key not in parent:
        _absent(ctx, local)
        return
    raw = parent[key]
    if not isinstance(raw, str) or not raw:
        ctx.obs.append(_make_obs(ctx, local, raw, None, "NONE", Semantics.OBSERVED_AND_DOCUMENTED, CAPTURE_DEF))
        _anomaly(ctx, local, ("TYPE_NOT_NONEMPTY_STRING", "documented as an enum string"), raw)
        return
    state = "DOCUMENTED_TOKEN" if raw in documented else "UNDOCUMENTED_TOKEN"
    ctx.obs.append(_make_obs(ctx, local, raw, raw, "NONE", Semantics.OBSERVED_AND_DOCUMENTED, CAPTURE_DEF, enum_state=state,
                             api_semantics_ref=sem.ref_for(sem_field, raw) if sem_field else None))
    if state == "UNDOCUMENTED_TOKEN":
        _anomaly(ctx, local, ("UNDOCUMENTED_ENUM_VALUE", "token is not in PayPal's documented enum; kept verbatim"), raw)


def _observe_capture(cap: Any, base: str, order_id: Optional[str], origin: str, observed_at: Optional[str], response_sha: str,
                     unit: Optional[Dict[str, Any]], unit_base: Optional[str], order: Optional[Dict[str, Any]]) -> CaptureObservation:
    if not isinstance(cap, dict):
        raise MalformedPayPalResponse([f"{base} is not an object"])
    cid = cap.get("id")
    if not isinstance(cid, str) or not cid:
        raise MalformedPayPalResponse([f"{base}.id is missing or not a non-empty string"])
    ctx = _Ctx(origin, f"{origin.lower()}:paypal-capture:{cid}", response_sha, observed_at, base, [], [], [])
    ctx.obs.append(_make_obs(ctx, "id", cid, cid, "NONE", Semantics.OBSERVED_AND_DOCUMENTED, CAPTURE_DEF))
    _extract_enum(ctx, cap, "status", "status", DOCUMENTED_CAPTURE_STATUSES, sem.CS)
    sd = cap.get("status_details")
    if sd is None:
        _absent(ctx, "status_details")
    elif not isinstance(sd, dict):
        _anomaly(ctx, "status_details", ("TYPE_NOT_OBJECT", "status_details is documented as an object"), sd)
    else:
        _extract_enum(ctx, sd, "reason", "status_details.reason", DOCUMENTED_STATUS_REASONS, sem.SDR)
    _extract_money(ctx, cap.get("amount"), "amount", CAPTURE_DEF, Semantics.OBSERVED_AND_DOCUMENTED, sem.CA)
    _extract_seller_protection(ctx, cap)
    srb = cap.get("seller_receivable_breakdown")
    if isinstance(srb, dict) and "paypal_fee" in srb:
        _extract_money(ctx, srb["paypal_fee"], "seller_receivable_breakdown.paypal_fee", CAPTURE_DEF, Semantics.OBSERVED_SEMANTICS_UNKNOWN)
    for t in ("create_time", "update_time"):
        if t in cap:
            ok = isinstance(cap[t], str) and bool(cap[t])
            ctx.obs.append(_make_obs(ctx, t, cap[t], cap[t] if ok else None, "NONE", Semantics.OBSERVED_SEMANTICS_UNKNOWN, CAPTURE_DEF))
            if not ok:
                _anomaly(ctx, t, ("TYPE_NOT_NONEMPTY_STRING", "documented as an RFC 3339 date-time string"), cap[t])
        else:
            _absent(ctx, t)
    if unit is not None:                       # context that lives on the purchase unit / order, not on the capture
        ship_path = f"{unit_base}.shipping.address"
        shipping = unit.get("shipping")
        addr = shipping.get("address") if isinstance(shipping, dict) else None
        if addr is None:
            _absent(ctx, "unit.shipping.address", ship_path)
        else:
            n, a = _norm_address(addr)
            ctx.obs.append(_make_obs(ctx, "unit.shipping.address", addr, n, "KEY_RENAME_CANDIDATE_UNVERIFIED" if n is not None else "NONE",
                                     Semantics.NOT_VERIFIED, ORDERS_SPEC, full_path=ship_path))
            if a:
                _anomaly(ctx, "unit.shipping.address", a, addr, ship_path)
        ps = order.get("payment_source") if order else None
        if isinstance(ps, dict):                   # record the TYPE KEYS only: the object itself carries payer details we do not need
            ctx.obs.append(_make_obs(ctx, "order.payment_source.types", sorted(ps), sorted(ps), "KEYS_ONLY", Semantics.NOT_VERIFIED,
                                     ORDERS_SPEC, full_path="payment_source"))
        else:
            _absent(ctx, "order.payment_source.types", "payment_source")
    return CaptureObservation(cid, order_id, ctx.resource_ref, origin, observed_at, response_sha, tuple(ctx.obs), tuple(ctx.absent),
                              tuple(ctx.anomalies))


def _prepare(response: Any, origin: str, observed_at: Optional[str]) -> str:
    if origin not in ORIGINS:
        raise MalformedPayPalResponse([f"origin must be one of {ORIGINS}"])
    if observed_at is not None and (not isinstance(observed_at, str) or not observed_at):
        raise MalformedPayPalResponse(["observed_at, when given, must be a non-empty string"])
    if not isinstance(response, dict):
        raise MalformedPayPalResponse(["response is not a JSON object"])
    try:
        return sha256_hex(canonical(response))
    except (TypeError, ValueError) as e:
        raise MalformedPayPalResponse([f"response is not JSON-serialisable: {e}"])


def observe_order(response: Any, *, origin: str, observed_at: Optional[str] = None) -> OrderObservation:
    """Observe an Orders v2 order response (capture-order / show-order). One CaptureObservation per capture found."""
    sha = _prepare(response, origin, observed_at)
    oid = response.get("id")
    if not isinstance(oid, str) or not oid:
        raise MalformedPayPalResponse(["order.id is missing or not a non-empty string"])
    units = response.get("purchase_units", [])
    if not isinstance(units, list):
        raise MalformedPayPalResponse(["purchase_units is not an array"])
    caps: List[CaptureObservation] = []
    seen = set()
    for i, unit in enumerate(units):
        if not isinstance(unit, dict):
            raise MalformedPayPalResponse([f"purchase_units[{i}] is not an object"])
        pay = unit.get("payments", {})
        if not isinstance(pay, dict):
            raise MalformedPayPalResponse([f"purchase_units[{i}].payments is not an object"])
        lst = pay.get("captures", [])
        if not isinstance(lst, list):
            raise MalformedPayPalResponse([f"purchase_units[{i}].payments.captures is not an array"])
        for j, cap in enumerate(lst):
            base = f"purchase_units[{i}].payments.captures[{j}]"
            co = _observe_capture(cap, base, oid, origin, observed_at, sha, unit, f"purchase_units[{i}]", response)
            if co.capture_id in seen:
                raise MalformedPayPalResponse([f"duplicate capture id {co.capture_id}"])
            seen.add(co.capture_id)
            caps.append(co)
    return OrderObservation(oid, origin, observed_at, sha, tuple(caps))


def observe_capture_resource(response: Any, *, origin: str, observed_at: Optional[str] = None) -> CaptureObservation:
    """Observe a standalone capture object (GET /v2/payments/captures/{id}); no order or purchase-unit context exists."""
    sha = _prepare(response, origin, observed_at)
    return _observe_capture(response, "capture", None, origin, observed_at, sha, None, None, None)
