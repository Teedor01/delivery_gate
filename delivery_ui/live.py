"""Live PayPal SANDBOX observations for the UI. Kept apart from the fixture analyses on purpose.

Nothing here feeds the policy engine, and a live observation never replaces or merges into a fixture payment.
It is a read-only view of what PayPal's sandbox returned, with the real retrieval provenance. Credentials come from the
process environment and are never returned, rendered or stored.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List, Mapping, Optional

from paypal_adapter.adapter import MalformedPayPalResponse
from paypal_adapter.sandbox_client import (DISPLAY_ORIGIN, SANDBOX_HOST, ENV_CLIENT_ID, ENV_CLIENT_SECRET, LiveFetch, PayPalSandboxClient,
                                           SandboxConfigError, SandboxRequestError, audit_record, observe_live)

ClientFactory = Callable[[Mapping[str, str]], PayPalSandboxClient]


class LiveError(Exception):
    def __init__(self, code: str, message: str, status: Optional[int] = None, debug_id: Optional[str] = None):
        super().__init__(message)
        self.code, self.status, self.debug_id = code, status, debug_id


class LiveSandboxService:
    def __init__(self, env: Optional[Mapping[str, str]] = None, client_factory: Optional[ClientFactory] = None):
        self._env = os.environ if env is None else env
        self._factory = client_factory or (lambda e: PayPalSandboxClient.from_env(e))
        self.history: List[Dict[str, Any]] = []          # newest first; in memory only

    def configured(self) -> bool:
        return all((self._env.get(n) or "").strip() for n in (ENV_CLIENT_ID, ENV_CLIENT_SECRET))

    def observe(self, kind: str, rid: str, select: Optional[str] = None) -> Dict[str, Any]:
        if kind not in ("capture", "order"):
            raise LiveError("bad_kind", "Choose capture or order.")
        try:
            client = self._factory(self._env)
            fetch: LiveFetch = client.fetch_capture(rid.strip()) if kind == "capture" else client.fetch_order(rid.strip())
        except SandboxConfigError as e:
            raise LiveError("not_configured", str(e))
        except SandboxRequestError as e:
            raise LiveError("request_failed", str(e), e.status, e.debug_id)
        try:
            cap = observe_live(fetch, (select or "").strip() or None)
        except (MalformedPayPalResponse, KeyError) as e:
            raise LiveError("not_observable", f"PayPal answered (HTTP {fetch.http_status}, debug id {fetch.paypal_debug_id}) but the response could not be observed: {e}",
                            fetch.http_status, fetch.paypal_debug_id)
        rec = {"origin": DISPLAY_ORIGIN, "host": SANDBOX_HOST, "request_path": fetch.path, "http_status": fetch.http_status,
               "paypal_debug_id": fetch.paypal_debug_id, "observed_at": fetch.observed_at, "resource": fetch.resource, "resource_id": fetch.resource_id,
               "response_sha256": audit_record(fetch)["response_sha256"], "observation": cap.to_dict()}
        self.history.insert(0, rec)
        del self.history[20:]
        return rec
