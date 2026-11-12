from __future__ import annotations

import json
import mimetypes
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from delivery_ui import presenter as P
from delivery_ui import render as R
from delivery_ui.live import LiveError, LiveSandboxService
from delivery_ui.checkout import CheckoutError, SandboxCheckoutService
from delivery_ui.service import DeliveryGateService, NotFound, ServiceError

STATIC = Path(__file__).resolve().parent / "static"
MAX_BODY = 1_000_000
CSP = "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
HEADERS = {"Content-Security-Policy": CSP, "X-Content-Type-Options": "nosniff", "Referrer-Policy": "no-referrer", "X-Frame-Options": "DENY", "Cache-Control": "no-store"}
API_FIELDS = {
    "artifacts": {"text", "kind", "source_label"},
    "review": {"mode", "reviewer", "note", "fact_id"},
    "merchant-info": {"country", "address", "answers"},
    "entity": {"entity_ref"},
}
Response = Tuple[int, Dict[str, str], bytes]


def _html(status: int, body: str) -> Response:
    return status, {"Content-Type": "text/html; charset=utf-8", **HEADERS}, body.encode("utf-8")


def _json(status: int, obj: Any) -> Response:
    return status, {"Content-Type": "application/json; charset=utf-8", **HEADERS}, json.dumps(obj, indent=1, sort_keys=True).encode("utf-8")


def _redirect(location: str) -> Response:
    return 303, {"Location": location, **HEADERS}, b""


class BadRequest(ServiceError):
    pass


class App:
    def __init__(self, service: Optional[DeliveryGateService] = None, live: Optional[LiveSandboxService] = None, checkout: Optional[SandboxCheckoutService] = None):
        self.checkout = checkout or SandboxCheckoutService()
        self.svc = service or DeliveryGateService(db_path=self.checkout.db_path)
        self.live = live or LiveSandboxService()
        self.lock = threading.RLock()
        # Rehydrate the stable PayPal-order -> assessment-case association after restart.
        for order in self.checkout.orders.values():
            case_id = order.get("case_id")
            if case_id:
                self.svc.register_paypal_case(case_id, order)

    # -- entry point -----------------------------------------------------------------------------------------------------------------
    def handle(self, method: str, raw_path: str, body: bytes = b"", content_type: str = "") -> Response:
        u = urlparse(raw_path)
        path = unquote(u.path)
        q = {k: v[-1] for k, v in parse_qs(u.query, keep_blank_values=True).items()}
        is_api = path.startswith("/api/")
        try:
            if len(body) > MAX_BODY:
                raise BadRequest("body_too_large", "That request is too large.")
            with self.lock:
                return self._route(method, path, q, body, content_type)
        except NotFound as e:
            return self._error(404, "Not found", str(e), is_api, e.code)
        except ServiceError as e:
            if is_api:
                return _json(400, {"error": e.code, "message": str(e)})
            return self._flash_back(raw_path, path, str(e), body, content_type)
        except Exception:                                                # noqa: BLE001 - never leak internals
            return self._error(500, "Something went wrong", "The request could not be completed. Nothing was changed.", is_api, "internal_error")

    def _error(self, status: int, title: str, message: str, is_api: bool, code: str) -> Response:
        if is_api:
            return _json(status, {"error": code, "message": message})
        return _html(status, R.page_error(status, title, message))

    def _flash_back(self, raw_path: str, path: str, message: str, body: bytes, ctype: str) -> Response:
        """A refused HTML form post goes back to the page it came from, with the reason shown."""
        m = re.match(r"^/payments/([^/]+)/(evidence(?:/[^/]+)?|info|entity)(?:/review|/sample)?$", path)
        target = "/payments"
        if m:
            ref = m.group(1)
            seg = m.group(2)
            target = f"/payments/{ref}" if seg in ("info", "entity") else f"/payments/{ref}/{seg}"
            if path.endswith("/review") or path.endswith("/sample"):
                target = path.rsplit("/", 1)[0] if path.endswith("/review") else f"/payments/{ref}/evidence"
        return _redirect(R.url(target, msg=message[:300], level="error"))

    # -- routing ---------------------------------------------------------------------------------------------------------------------
    def _route(self, method: str, path: str, q: Dict[str, str], body: bytes, ctype: str) -> Response:
        svc = self.svc
        if path == "/healthz":
            return _json(200, {"ok": True, "fixture_data": True, "live_sandbox_configured": self.live.configured()})
        if path.startswith("/static/"):
            return self._static(path[len("/static/"):])
        flash = {"msg": q.get("msg", "")[:300], "level": q.get("level", "info")}
        if method == "GET":
            if path == "/":
                rows = [P.summary_row(a) for a in svc.list_analyses()]
                return _html(200, R.page_overview(rows, P.counters(rows), flash))
            if path == "/payments":
                return self._payments(q, flash)
            if path == "/live/return":
                return _redirect(R.url("/live", msg="Returned from PayPal. Retrieve the order to confirm its current status.", level="ok"))
            if path == "/live":
                return _html(200, R.page_live(self.live.configured(), self.live.history, flash, checkout_configured=self.checkout.configured(), orders=list(self.checkout.orders.values())))
            if path == "/api/live":
                return _json(200, {"origin": "LIVE_SANDBOX", "configured": self.live.configured(), "observations": self.live.history})
            m = re.fullmatch(r"/payments/([^/]+)", path)
            if m:
                return self._detail(m.group(1), q, flash)
            m = re.fullmatch(r"/payments/([^/]+)/assessment", path)
            if m:
                return _redirect(R.pay_url(m.group(1), "assessment"))
            m = re.fullmatch(r"/payments/([^/]+)/evidence", path)
            if m:
                an = svc.analyze(m.group(1))
                have = set(an.state.artifacts)
                samples = [{"id": a["id"], "category": a["category"]} for a in self._corpus() if a["id"] not in have]
                return _html(200, R.page_workspace(P.detail(svc, an), samples, flash, q.get("added")))
            m = re.fullmatch(r"/payments/([^/]+)/evidence/([^/]+)", path)
            if m:
                an = svc.analyze(m.group(1))
                if m.group(2) not in an.state.artifacts:
                    raise NotFound("artifact_not_found", f"No evidence {m.group(2)!r} on this payment.")
                return _html(200, R.page_artifact(P.detail(svc, an), m.group(2), flash))
            if path == "/evidence":
                items = []
                for a in svc.list_analyses():
                    d = P.detail(svc, a)
                    items += [{"ref": a.ref, "order_ref": d["order_ref"], "artifact": e} for e in d["evidence"]]
                return _html(200, R.page_evidence_index(items))
            if path == "/api/payments":
                rows = [P.summary_row(a) for a in svc.list_analyses()]
                return _json(200, {"payments": rows, "counters": P.counters(rows), "fixture_data": True})
            m = re.fullmatch(r"/api/payments/([^/]+)", path)
            if m:
                return _json(200, P.detail(svc, svc.analyze(m.group(1))))
            m = re.fullmatch(r"/api/payments/([^/]+)/assessment", path)
            if m:
                a = svc.analyze(m.group(1)).assessment
                return _json(200, a.to_dict() if a else {"assessment": None})
            m = re.fullmatch(r"/api/payments/([^/]+)/whatif", path)
            if m:
                an = svc.analyze(m.group(1))
                if "option" not in q:
                    return _json(200, {"options": [o.__dict__ for o in svc.what_if_options(m.group(1))]})
                return _json(200, P.what_if_view(svc, an, svc.what_if(m.group(1), q["option"])))
            raise NotFound("not_found", "That page does not exist.")
        if method == "POST":
            return self._post(path, body, ctype)
        return self._error(405, "Method not allowed", "That action is not supported.", path.startswith("/api/"), "method_not_allowed")

    def _corpus(self) -> List[Dict[str, Any]]:
        from eval.corpus import ARTIFACTS
        return list(ARTIFACTS)

    def _static(self, name: str) -> Response:
        p = (STATIC / name).resolve()
        if STATIC.resolve() not in p.parents or not p.is_file():
            raise NotFound("not_found", "That file does not exist.")
        ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        return 200, {"Content-Type": f"{ctype}; charset=utf-8" if ctype.startswith("text/") or ctype.endswith("javascript") else ctype, **HEADERS,
                     "Cache-Control": "no-cache"}, p.read_bytes()

    def _payments(self, q: Dict[str, str], flash: Optional[Dict[str, str]] = None) -> Response:
        svc = self.svc
        analyses = svc.list_analyses()
        rows = [P.summary_row(a) for a in analyses]
        counters = P.counters(rows)
        flt = q.get("filter", "all")
        flt = flt if flt in ("all", "attention", "review", "ready", "unassessable") else "all"
        term = q.get("q", "").strip().lower()[:80]
        shown = [r for r in rows if (flt == "all" or r["bucket"] == flt) and (not term or term in " ".join(
            [r["ref"], r["order_ref"], r["amount"], r["dispute"], r["assessment"]["label"], r["payment_status"]["label"]]).lower())]
        selected = None
        if q.get("selected"):
            an = next((a for a in analyses if a.ref == q["selected"]), None)
            if an is not None:
                selected = P.detail(svc, an)
        return _html(200, R.page_payments(shown, counters, flt, q.get("q", "")[:80], selected, len(rows), flash))

    def _detail(self, ref: str, q: Dict[str, str], flash: Dict[str, str]) -> Response:
        svc = self.svc
        an = svc.analyze(ref)
        tab = q.get("tab", "evidence")
        tab = tab if tab in ("evidence", "assessment", "whatif", "provenance") else "evidence"
        extra: Dict[str, Any] = {"group": q.get("group")}
        if tab == "whatif":
            extra["options"] = svc.what_if_options(ref)
            if q.get("option"):
                try:
                    extra["what_if"] = P.what_if_view(svc, an, svc.what_if(ref, q["option"]))
                except ServiceError as e:
                    extra["what_if_error"] = str(e)
        return _html(200, R.page_detail(P.detail(svc, an), tab, extra, flash))

    # -- POST --------------------------------------------------------------------------------------------------------------------------
    def _fields(self, body: bytes, ctype: str, allowed: Optional[set]) -> Dict[str, Any]:
        if "json" in ctype:
            try:
                data = json.loads(body.decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                raise BadRequest("invalid_json", "The request body is not valid JSON.")
            if not isinstance(data, dict):
                raise BadRequest("invalid_json", "The request body must be a JSON object.")
        else:
            data = {k: v[-1] for k, v in parse_qs(body.decode("utf-8", "replace"), keep_blank_values=True).items()}
        if allowed is not None:
            extra = sorted(set(data) - allowed)
            if extra:
                raise BadRequest("unexpected_field", f"Unsupported field(s): {', '.join(extra)}. Results, statuses and authenticity can't be set by a request.")
        return data

    def _post(self, path: str, body: bytes, ctype: str) -> Response:
        svc = self.svc
        api = path.startswith("/api/")
        if path in ("/reset", "/api/reset"):
            svc.reset()
            return _json(200, {"ok": True}) if api else _redirect("/")
        if path in ("/api/live/orders", "/live/orders"):
            f = self._fields(body, ctype, {"amount", "currency", "description"})
            base = "http://127.0.0.1:8080"
            try:
                rec = self.checkout.create(f.get("amount", ""), f.get("currency", "USD"), f.get("description", ""), base + "/live/return", base + "/live?cancelled=1")
                case_id = rec["case_id"]
                self.svc.register_paypal_case(case_id, rec)
                self.checkout.bind_case(rec["order_id"], case_id)
            except CheckoutError as e:
                if api: return _json(400 if e.code.startswith("invalid") or e.code == "not_configured" else 502, {"error":e.code,"message":str(e),"http_status":e.status,"paypal_debug_id":e.debug_id})
                return _redirect(R.url("/live", msg=str(e)[:250], level="error"))
            return _json(201, rec) if api else _redirect(R.url("/live", msg="Sandbox order created. Open the PayPal approval link.", level="ok"))
        if path in ("/api/live/orders/retrieve", "/live/orders/retrieve"):
            f = self._fields(body, ctype, {"order_id"})
            try:
                order_id = f.get("order_id", "")
                case_id = self.checkout.get_case_id(order_id)
                if not case_id: raise CheckoutError("order_case_not_found", "This order was not created and associated by this Delivery Gate application.")
                rec = self.checkout.retrieve(order_id)
                self.svc.update_paypal_case(case_id, self.checkout.orders[order_id])
            except CheckoutError as e:
                if api: return _json(502, {"error":e.code,"message":str(e),"http_status":e.status,"paypal_debug_id":e.debug_id})
                return _redirect(R.url("/live", msg=str(e)[:250], level="error"))
            return _json(200, rec) if api else _redirect(R.url("/live", msg="Order retrieved from PayPal Sandbox.", level="ok"))
        if path in ("/api/live/orders/capture", "/live/orders/capture"):
            f = self._fields(body, ctype, {"order_id"})
            try:
                order_id = f.get("order_id", "")
                case_id = self.checkout.get_case_id(order_id)
                if not case_id: raise CheckoutError("order_case_not_found", "This order was not created and associated by this Delivery Gate application.")
                rec = self.checkout.capture(order_id)
                self.svc.update_paypal_case(case_id, self.checkout.orders[order_id])
            except CheckoutError as e:
                if api: return _json(409 if e.code in ("already_captured","order_not_approved","order_case_not_found") else 502, {"error":e.code,"message":str(e),"http_status":e.status,"paypal_debug_id":e.debug_id})
                return _redirect(R.url("/live", msg=str(e)[:250], level="error"))
            return _json(200, rec) if api else _redirect(R.url("/live", msg="PayPal confirmed the capture.", level="ok"))
        if path in ("/live/observe", "/api/live/observe"):
            f = self._fields(body, ctype, {"kind", "resource_id", "select"})
            try:
                rec = self.live.observe(f.get("kind", ""), f.get("resource_id", ""), f.get("select"))
            except LiveError as e:
                err = {"code": e.code, "message": str(e), "status": e.status, "debug_id": e.debug_id}
                if api:
                    return _json(400 if e.code in ("bad_kind", "not_configured") else 502, {"error": e.code, "message": str(e), "http_status": e.status, "paypal_debug_id": e.debug_id})
                return _html(200, R.page_live(self.live.configured(), self.live.history, None, err))
            return _json(200, rec) if api else _redirect(R.url("/live", msg="Retrieved from the PayPal sandbox.", level="ok"))
        m = re.fullmatch(r"/(?:api/)?payments/([^/]+)/(artifacts|evidence)", path)
        if m:
            ref = m.group(1)
            f = self._fields(body, ctype, API_FIELDS["artifacts"] if api else {"text", "kind", "source_label"})
            rec = svc.add_artifact(ref, f.get("text", ""), f.get("kind") or "OTHER", (f.get("source_label") or "Pasted text")[:80])
            if api:
                return _json(201, {"artifact_id": rec.artifact.artifact_id, "extraction_status": rec.status, "message": rec.message, "fact_count": len(rec.facts)})
            note = {"EXTRACTED": f"Evidence {rec.artifact.artifact_id} added: {len(rec.facts)} fact(s) found.", "NO_FACTS": f"Evidence {rec.artifact.artifact_id} added, but no usable facts were found.",
                    "UNAVAILABLE": f"Evidence {rec.artifact.artifact_id} was saved but could not be read: {rec.message}", "FAILED": f"Evidence {rec.artifact.artifact_id} could not be analysed: {rec.message}"}[rec.status]
            return _redirect(R.url(f"/payments/{ref}/evidence", added=rec.artifact.artifact_id, msg=note, level="ok" if rec.status == "EXTRACTED" else "info"))
        m = re.fullmatch(r"/payments/([^/]+)/evidence/sample", path)
        if m:
            f = self._fields(body, ctype, {"sample_id"})
            sample = next((a for a in self._corpus() if a["id"] == f.get("sample_id")), None)
            if sample is None:
                raise NotFound("sample_not_found", "That sample does not exist.")
            rec = svc.add_artifact(m.group(1), sample["text"], sample["kind"], "Sample evidence (demo library)")
            return _redirect(R.url(f"/payments/{m.group(1)}/evidence", added=rec.artifact.artifact_id, msg=f"Sample {rec.artifact.artifact_id} added: {len(rec.facts)} fact(s) found.", level="ok"))
        m = re.fullmatch(r"/(?:api/)?payments/([^/]+)/artifacts/([^/]+)/review|/payments/([^/]+)/evidence/([^/]+)/review", path)
        if m:
            ref, aid = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
            f = self._fields(body, ctype, API_FIELDS["review"])
            out = svc.review_artifact(ref, aid, f.get("mode", ""), f.get("reviewer", ""), (f.get("note") or "")[:200], f.get("fact_id") or None)
            if api:
                return _json(200, out)
            return _redirect(R.url(f"/payments/{ref}/evidence/{aid}", msg=f"Review recorded ({out['mode'].replace('_', ' ')}).", level="ok"))
        m = re.fullmatch(r"/api/payments/([^/]+)/merchant-info", path)
        if m:
            svc.set_merchant_info(m.group(1), self._fields(body, ctype, API_FIELDS["merchant-info"]))
            return _json(200, {"ok": True})
        m = re.fullmatch(r"/payments/([^/]+)/info", path)
        if m:
            f = self._fields(body, ctype, {"country", "line1", "city", "region", "postal_code", "addr_country", "redirect_detected", "response_to_paypal", "shipped_after_advised_not_to_release"})
            tri = lambda v: {"true": True, "false": False}.get(v)
            data = {"country": f.get("country", ""), "address": {k: f.get(k, "") for k in ("line1", "city", "region", "postal_code")},
                    "answers": {"redirect_detected": tri(f.get("redirect_detected")), "response_to_paypal": f.get("response_to_paypal") or None,
                              "shipped_after_advised_not_to_release": tri(f.get("shipped_after_advised_not_to_release"))}}
            if f.get("addr_country"):
                data["address"]["country"] = f["addr_country"]
            svc.set_merchant_info(m.group(1), data)
            return _redirect(R.url(f"/payments/{m.group(1)}", msg="What you provided was updated.", level="ok"))
        m = re.fullmatch(r"/(?:api/)?payments/([^/]+)/entity", path)
        if m:
            svc.set_entity(m.group(1), self._fields(body, ctype, API_FIELDS["entity"]).get("entity_ref"))
            return _json(200, {"ok": True}) if api else _redirect(R.pay_url(m.group(1)))
        raise NotFound("not_found", "That action does not exist.")


class Handler(BaseHTTPRequestHandler):
    app: App = None  
    server_version = "DeliveryGate"
    sys_version = ""

    def _respond(self, resp: Response, head: bool = False) -> None:
        status, headers, body = resp
        self.send_response(status)
        for k, v in headers.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def do_GET(self):                                                    
        self._respond(self.app.handle("GET", self.path))

    def do_HEAD(self):                                                   
        self._respond(self.app.handle("GET", self.path), head=True)

    def do_POST(self):                                                   
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            n = 0
        body = self.rfile.read(min(n, MAX_BODY + 1))
        self._respond(self.app.handle("POST", self.path, body, self.headers.get("Content-Type", "")))

    def log_message(self, fmt, *args):                                  
        pass


def make_server(service: Optional[DeliveryGateService] = None, host: str = "127.0.0.1", port: int = 0, live: Optional[LiveSandboxService] = None) -> ThreadingHTTPServer:
    app = App(service, live)
    handler = type("BoundHandler", (Handler,), {"app": app})
    srv = ThreadingHTTPServer((host, port), handler)
    srv.app = app                                                        
    return srv


def main(argv: Optional[List[str]] = None) -> None:
    import argparse
    ap = argparse.ArgumentParser(description="Delivery Gate UI (fixture payments; optional read-only live sandbox page)")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args(argv)
    srv = make_server(host=a.host, port=a.port)
    print(f"Delivery Gate demo UI on http://{a.host}:{srv.server_address[1]}  (fixture data; Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
