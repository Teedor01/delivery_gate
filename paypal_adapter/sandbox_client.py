"""Read-only PayPal SANDBOX client. It retrieves a real sandbox capture or order and hands the raw response to the
existing observation adapter with origin="SANDBOX". Nothing here interprets policy.

Hard guarantees (each has a test):
  * Only the sandbox host https://api-m.sandbox.paypal.com can ever be contacted; there is no production URL in this module.
  * Only GET requests to /v2/... resources are made, plus the single OAuth token POST. Nothing is created, captured, refunded or changed.
  * Credentials come from the environment (PAYPAL_SANDBOX_CLIENT_ID / PAYPAL_SANDBOX_CLIENT_SECRET) and are never stored, logged,
    printed, put in an exception message, saved to disk or included in repr().
  * Redirects are refused, so a credential-bearing request cannot be bounced to another host.
  * The raw response is preserved byte-for-byte (raw_body) and parsed unchanged; observed_at is the real retrieval time.

Endpoints (PayPal REST documentation): POST /v1/oauth2/token (client credentials), GET /v2/payments/captures/{capture_id},
GET /v2/checkout/orders/{id}.

LIVE STATUS: this module was written and unit-tested without network access or credentials. A real request has to be run by
someone holding sandbox credentials; see docs/PAYPAL_SANDBOX.md. Until that is done and recorded, the integration is
UNVERIFIED against the live service.
"""
from __future__ import annotations

import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Mapping, Optional, Tuple

from .adapter import CaptureObservation, MalformedPayPalResponse, OrderObservation, observe_capture_resource, observe_order

SANDBOX_HOST = "api-m.sandbox.paypal.com"
SANDBOX_BASE = f"https://{SANDBOX_HOST}"
TOKEN_PATH = "/v1/oauth2/token"
ENV_CLIENT_ID = "PAYPAL_SANDBOX_CLIENT_ID"
ENV_CLIENT_SECRET = "PAYPAL_SANDBOX_CLIENT_SECRET"
DISPLAY_ORIGIN = "LIVE_SANDBOX"          # what the UI/CLI shows; the adapter's own origin token stays "SANDBOX"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]{5,64}$")
_ALLOWED_METHODS = {("POST", TOKEN_PATH)}

Transport = Callable[[str, str, Mapping[str, str], Optional[bytes]], Tuple[int, Dict[str, str], bytes]]


class SandboxConfigError(Exception):
    """Missing or unusable configuration. Names variables, never values."""


class SandboxRequestError(Exception):
    """A request failed. The message carries status and PayPal's debug id only, never a token, secret or response body."""
    def __init__(self, message: str, status: Optional[int] = None, debug_id: Optional[str] = None):
        super().__init__(message)
        self.status, self.debug_id = status, debug_id


def load_credentials(env: Mapping[str, str]) -> Tuple[str, str]:
    missing = [n for n in (ENV_CLIENT_ID, ENV_CLIENT_SECRET) if not (env.get(n) or "").strip()]
    if missing:
        raise SandboxConfigError("missing environment variable(s): " + ", ".join(missing) + " (see .env.example)")
    return env[ENV_CLIENT_ID].strip(), env[ENV_CLIENT_SECRET].strip()


def _validate_id(kind: str, value: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise SandboxConfigError(f"{kind} id must be 5-64 characters of letters, digits, '-' or '_'")
    return value


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # a credential-bearing request must never follow a redirect
        return None


def default_transport(method: str, url: str, headers: Mapping[str, str], body: Optional[bytes]) -> Tuple[int, Dict[str, str], bytes]:
    """The only network code. Refuses any URL that is not https on the sandbox host, and refuses redirects."""
    parts = urllib.parse.urlsplit(url)
    if parts.scheme != "https" or parts.hostname != SANDBOX_HOST or parts.port not in (None, 443) or parts.username or parts.password:
        raise SandboxRequestError("refused: only https://" + SANDBOX_HOST + " may be contacted")
    req = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=20) as r:
            return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
    except urllib.error.HTTPError as e:
        return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise SandboxRequestError(f"network error contacting the sandbox ({type(e).__name__})") from None


@dataclass(frozen=True)
class LiveFetch:
    """One real retrieval, with everything needed to audit it. Contains no credential or token."""
    resource: str                 # "capture" | "order"
    resource_id: str
    path: str
    http_status: int
    paypal_debug_id: Optional[str]
    observed_at: str              # real retrieval time, UTC, ISO-8601
    raw_body: str                 # exactly what PayPal returned
    response: Dict[str, Any]      # raw_body parsed, unmodified


class PayPalSandboxClient:
    def __init__(self, client_id: str, client_secret: str, transport: Optional[Transport] = None, clock: Optional[Callable[[], datetime]] = None):
        if not client_id or not client_secret:
            raise SandboxConfigError("client id and secret are required")
        self._basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
        self._transport = transport or default_transport
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._token: Optional[str] = None

    def __repr__(self) -> str:
        return "PayPalSandboxClient(origin=LIVE_SANDBOX, credentials=<redacted>)"

    __str__ = __repr__

    @classmethod
    def from_env(cls, env: Mapping[str, str], transport: Optional[Transport] = None) -> "PayPalSandboxClient":
        cid, sec = load_credentials(env)
        return cls(cid, sec, transport)

    # -- internals ---------------------------------------------------------------------------------------------------
    def _send(self, method: str, path: str, headers: Dict[str, str], body: Optional[bytes] = None) -> Tuple[int, Dict[str, str], bytes]:
        if method == "GET":
            if not (path.startswith("/v2/payments/captures/") or path.startswith("/v2/checkout/orders/")):
                raise SandboxRequestError("refused: unsupported read path")
        elif (method, path) not in _ALLOWED_METHODS:
            raise SandboxRequestError("refused: this client is read-only")
        return self._transport(method, SANDBOX_BASE + path, headers, body)

    def _access_token(self) -> str:
        if self._token:
            return self._token
        status, hdrs, body = self._send("POST", TOKEN_PATH,
                                        {"Authorization": "Basic " + self._basic, "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
                                        b"grant_type=client_credentials")
        debug = hdrs.get("paypal-debug-id")
        if status != 200:
            raise SandboxRequestError(f"OAuth token request failed (HTTP {status}); check the sandbox client id and secret", status, debug)
        try:
            tok = json.loads(body.decode("utf-8")).get("access_token")
        except (ValueError, AttributeError):
            tok = None
        if not isinstance(tok, str) or not tok:
            raise SandboxRequestError("OAuth token response had no access_token", status, debug)
        self._token = tok
        return tok

    def _get(self, resource: str, rid: str, path: str) -> LiveFetch:
        token = self._access_token()
        status, hdrs, body = self._send("GET", path, {"Authorization": "Bearer " + token, "Accept": "application/json"})
        debug = hdrs.get("paypal-debug-id")
        if status != 200:
            raise SandboxRequestError(f"GET {path} failed (HTTP {status})", status, debug)
        observed_at = self._clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        raw = body.decode("utf-8")
        try:
            parsed = json.loads(raw)
        except ValueError:
            raise SandboxRequestError("PayPal returned a body that is not JSON", status, debug) from None
        if not isinstance(parsed, dict):
            raise SandboxRequestError("PayPal returned JSON that is not an object", status, debug)
        return LiveFetch(resource, rid, path, status, debug, observed_at, raw, parsed)

    # -- public, read-only ---------------------------------------------------------------------------------------------
    def fetch_capture(self, capture_id: str) -> LiveFetch:
        cid = _validate_id("capture", capture_id)
        return self._get("capture", cid, f"/v2/payments/captures/{cid}")

    def fetch_order(self, order_id: str) -> LiveFetch:
        oid = _validate_id("order", order_id)
        return self._get("order", oid, f"/v2/checkout/orders/{oid}")


def observe_live(fetch: LiveFetch, select_capture: Optional[str] = None) -> CaptureObservation:
    """Hand a real response to the existing adapter. origin is always SANDBOX; observed_at is the real retrieval time."""
    if fetch.resource == "capture":
        return observe_capture_resource(fetch.response, origin="SANDBOX", observed_at=fetch.observed_at)
    order: OrderObservation = observe_order(fetch.response, origin="SANDBOX", observed_at=fetch.observed_at)
    return order.select_capture(select_capture)


def audit_record(fetch: LiveFetch) -> Dict[str, Any]:
    """What gets saved to disk: the response and how it was obtained. No credentials, tokens or request headers."""
    from .adapter import canonical, sha256_hex
    return {"_origin": DISPLAY_ORIGIN,
            "_note": "A real response from the PayPal SANDBOX API. Not a fixture. Sandbox data, not production money.",
            "request": {"method": "GET", "host": SANDBOX_HOST, "path": fetch.path},
            "http_status": fetch.http_status, "paypal_debug_id": fetch.paypal_debug_id, "observed_at": fetch.observed_at,
            "response_sha256": sha256_hex(canonical(fetch.response)), "raw_body": fetch.raw_body, "response": fetch.response}
