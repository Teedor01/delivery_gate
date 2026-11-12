"""Run ONE real, read-only retrieval against the PayPal SANDBOX and print what came back.

    export PAYPAL_SANDBOX_CLIENT_ID=...     # sandbox REST app credentials (never production)
    export PAYPAL_SANDBOX_CLIENT_SECRET=...
    python3 -m paypal_adapter.sandbox_check --capture <CAPTURE_ID> [--save live_captures]
    python3 -m paypal_adapter.sandbox_check --order <ORDER_ID> [--select <CAPTURE_ID>] [--save live_captures]

Exit codes: 0 success, 2 configuration error (no request was made), 3 request failed, 4 response could not be observed.
Nothing is interpreted: opaque PayPal statuses are printed as received and are not mapped to any policy outcome.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import IO, Mapping, Optional, Sequence

from .adapter import MalformedPayPalResponse
from .sandbox_client import (DISPLAY_ORIGIN, SANDBOX_HOST, LiveFetch, PayPalSandboxClient, SandboxConfigError, SandboxRequestError, Transport,
                             audit_record, observe_live)


def _show(v, n=70):
    s = json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
    return s if len(s) <= n else s[: n - 1] + "…"


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None, transport: Optional[Transport] = None,
         out: Optional[IO[str]] = None) -> int:
    out = out or sys.stdout
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="python3 -m paypal_adapter.sandbox_check", description="Read-only PayPal SANDBOX retrieval.")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--capture", metavar="CAPTURE_ID")
    g.add_argument("--order", metavar="ORDER_ID")
    ap.add_argument("--select", metavar="CAPTURE_ID", help="with --order: which capture to observe (never guessed when several exist)")
    ap.add_argument("--save", metavar="DIR", help="save the audit record (response + request metadata, no credentials) into DIR")
    a = ap.parse_args(argv)
    p = lambda s="": print(s, file=out)

    try:
        client = PayPalSandboxClient.from_env(env, transport)
        fetch: LiveFetch = client.fetch_capture(a.capture) if a.capture else client.fetch_order(a.order)
    except SandboxConfigError as e:
        p(f"CONFIGURATION ERROR (no request was made): {e}")
        return 2
    except SandboxRequestError as e:
        p(f"REQUEST FAILED: {e}" + (f"  [paypal-debug-id: {e.debug_id}]" if e.debug_id else ""))
        return 3

    p(f"ORIGIN: {DISPLAY_ORIGIN}   (a real request to https://{SANDBOX_HOST}; not a fixture)")
    p(f"GET {fetch.path}  ->  HTTP {fetch.http_status}")
    p(f"paypal-debug-id: {fetch.paypal_debug_id}")
    p(f"observed_at   : {fetch.observed_at}")
    try:
        cap = observe_live(fetch, a.select)
    except (MalformedPayPalResponse, KeyError) as e:
        p(f"RESPONSE RECEIVED BUT COULD NOT BE OBSERVED: {e}")
        return 4
    p(f"response sha256 (canonical JSON): {cap.response_sha256}")
    p(f"capture {cap.capture_id}" + (f" in order {cap.order_id}" if cap.order_id else "") + f"   adapter origin token: {cap.origin}")
    p()
    p(f"{'field path':44} {'raw value (verbatim)':40} {'enum state'}")
    for o in cap.observations:
        p(f"{o.local_path[:44]:44} {_show(o.raw_value, 40):40} {o.enum_state or ''}")
    if cap.absent:
        p("\nfields absent from the response (unknown, not assumed): " + ", ".join(x.to_dict().get("local_path", "?") for x in cap.absent))
    if cap.anomalies:
        p("\nanomalies: " + "; ".join(str(x.to_dict()) for x in cap.anomalies))
    p("\nNothing above is a Seller Protection decision. PayPal status values are opaque observations; PayPal makes the final decision.")

    if a.save:
        d = Path(a.save)
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"{fetch.resource}_{fetch.resource_id}_{fetch.observed_at.replace(':', '')}.json"
        path.write_text(json.dumps(audit_record(fetch), indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
        try:
            path.chmod(0o600)
        except OSError:
            pass
        p(f"\nsaved audit record: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
