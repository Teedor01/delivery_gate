from __future__ import annotations

import argparse
import json
import os
import sys
import uuid
from typing import IO, Any, Dict, Mapping, Optional, Sequence

from paypal_adapter.sandbox_client import SANDBOX_BASE, SandboxConfigError, SandboxRequestError, PayPalSandboxClient, default_transport, load_credentials, _validate_id


class Flow:
    def __init__(self, env: Mapping[str, str], transport=None):
        cid, sec = load_credentials(env)
        self._client = PayPalSandboxClient(cid, sec, transport)       # reused only for its OAuth token
        self._t = transport or default_transport

    def _call(self, method: str, path: str, body: Optional[Dict[str, Any]] = None, request_id: Optional[str] = None):
        if not path.startswith("/v2/checkout/orders"):
            raise SandboxRequestError("refused: unsupported path")
        h = {"Authorization": "Bearer " + self._client._access_token(), "Accept": "application/json", "Content-Type": "application/json"}
        if request_id:
            h["PayPal-Request-Id"] = request_id
        data = json.dumps(body).encode() if body is not None else (b"{}" if method == "POST" else None)
        status, hdrs, raw = self._t(method, SANDBOX_BASE + path, h, data)
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except ValueError:
            parsed = {}
        return status, hdrs.get("paypal-debug-id"), parsed

    def create(self, amount: str, currency: str, return_url: str, cancel_url: str, description: str = ""):
        unit = {"amount": {"currency_code": currency, "value": amount}}
        if description: unit["description"] = description[:127]
        body = {"intent": "CAPTURE", "purchase_units": [unit],
                "payment_source": {"paypal": {"experience_context": {"payment_method_preference": "IMMEDIATE_PAYMENT_REQUIRED", "user_action": "PAY_NOW",
                                                                    "return_url": return_url, "cancel_url": cancel_url}}}}
        return self._call("POST", "/v2/checkout/orders", body, str(uuid.uuid4()))

    def status(self, oid: str):
        return self._call("GET", f"/v2/checkout/orders/{_validate_id('order', oid)}")

    def capture(self, oid: str):
        return self._call("POST", f"/v2/checkout/orders/{_validate_id('order', oid)}/capture", None, str(uuid.uuid4()))


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None, transport=None, out: Optional[IO[str]] = None) -> int:
    out = out or sys.stdout
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="python3 -m tools.sandbox_order_flow", description="Explicit PayPal SANDBOX order create/approve/capture test workflow.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create"); c.add_argument("--amount", default="10.00"); c.add_argument("--currency", default="USD")
    c.add_argument("--return-url", default="https://example.com/return"); c.add_argument("--cancel-url", default="https://example.com/cancel")
    sub.add_parser("status").add_argument("order_id")
    k = sub.add_parser("capture"); k.add_argument("order_id"); k.add_argument("--yes-capture", action="store_true", help="required: confirms you intend to capture this SANDBOX order")
    a = ap.parse_args(argv)
    p = lambda s="": print(s, file=out)
    if a.cmd == "capture" and not a.yes_capture:
        p("Refusing to capture without --yes-capture. Nothing was sent.")
        return 2
    try:
        f = Flow(env, transport)
        st, dbg, body = f.create(a.amount, a.currency, a.return_url, a.cancel_url) if a.cmd == "create" else f.status(a.order_id) if a.cmd == "status" else f.capture(a.order_id)
    except SandboxConfigError as e:
        p(f"CONFIGURATION ERROR (no request was made): {e}")
        return 2
    except SandboxRequestError as e:
        p(f"REQUEST FAILED: {e}" + (f" [paypal-debug-id: {e.debug_id}]" if e.debug_id else ""))
        return 3
    p(f"HTTP {st}   paypal-debug-id: {dbg}")
    if st not in (200, 201):
        p("PayPal refused: " + json.dumps({k2: body.get(k2) for k2 in ("name", "message", "details") if k2 in body}, ensure_ascii=False))
        return 3
    p(f"order id: {body.get('id')}   status: {body.get('status')}")
    if a.cmd == "create":
        link = next((l["href"] for l in body.get("links", []) if l.get("rel") in ("payer-action", "approve")), None)
        p("Buyer approval link (open while signed in to a SANDBOX personal account): " + str(link))
        p("After approving, run: capture ORDER_ID --yes-capture")
    if a.cmd == "capture":
        caps = [c2.get("id") for pu in body.get("purchase_units", []) for c2 in pu.get("payments", {}).get("captures", [])]
        p("capture id(s): " + ", ".join(map(str, caps)) if caps else "no capture id in the response")
    return 0


if __name__ == "__main__":
    sys.exit(main())
