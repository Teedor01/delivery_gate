import json
import unittest

from delivery_ui.live import LiveSandboxService
from delivery_ui.server import App
from paypal_adapter.sandbox_client import PayPalSandboxClient
from tools import sandbox_order_flow as flow

ENV = {"PAYPAL_SANDBOX_CLIENT_ID": "cid-secret-xyz", "PAYPAL_SANDBOX_CLIENT_SECRET": "sec-secret-xyz"}


def capture_body():
    return {"id": "CAP12345XYZ", "status": "COMPLETED", "amount": {"currency_code": "USD", "value": "10.00"}, "create_time": "2026-11-12T10:00:00Z"}


def transport(calls, status=200, body=None):
    def t(method, url, headers, data):
        calls.append((method, url))
        if url.endswith("/v1/oauth2/token"):
            return 200, {"paypal-debug-id": "d0"}, json.dumps({"access_token": "TOKEN-ABC"}).encode()
        return status, {"paypal-debug-id": "dbg-live-1"}, json.dumps(capture_body() if body is None else body).encode()
    return t


def app(env=ENV, calls=None, status=200):
    calls = [] if calls is None else calls
    live = LiveSandboxService(env, lambda e: PayPalSandboxClient.from_env(e, transport(calls, status)))
    return App(live=live), calls


class LiveUiTests(unittest.TestCase):
    def test_live_page_without_credentials_is_visibly_unavailable_and_makes_no_request(self):
        a, calls = app({})
        st, _, body = a.handle("GET", "/live")
        self.assertEqual(st, 200)
        self.assertIn(b"live-not-configured", body)
        st, _, body = a.handle("POST", "/api/live/observe", b'{"kind":"capture","resource_id":"CAP12345XYZ"}', "application/json")
        self.assertEqual(st, 400)
        self.assertEqual(calls, [])

    def test_live_observation_shows_provenance_and_is_labelled_live_sandbox(self):
        a, calls = app()
        st, _, body = a.handle("POST", "/api/live/observe", b'{"kind":"capture","resource_id":"CAP12345XYZ"}', "application/json")
        self.assertEqual(st, 200)
        d = json.loads(body)
        self.assertEqual((d["origin"], d["http_status"], d["paypal_debug_id"]), ("LIVE_SANDBOX", 200, "dbg-live-1"))
        self.assertEqual(len(d["response_sha256"]), 64)
        st, _, page = a.handle("GET", "/live")
        for needle in (b"LIVE_SANDBOX", b"dbg-live-1", b"CAP12345XYZ", b"Live sandbox (not fixture)", b"not an assessment"):
            self.assertIn(needle, page)
        self.assertNotIn(b"Fixture data</span>", page)
        self.assertEqual([c[0] for c in calls], ["POST", "GET"])

    def test_live_data_never_enters_fixture_payments_or_the_engine(self):
        a, _ = app()
        before = a.handle("GET", "/api/payments")[2]
        a.handle("POST", "/api/live/observe", b'{"kind":"capture","resource_id":"CAP12345XYZ"}', "application/json")
        self.assertEqual(a.handle("GET", "/api/payments")[2], before)
        self.assertNotIn(b"CAP12345XYZ", a.handle("GET", "/payments")[2])

    def test_failures_are_visible_not_swallowed_and_no_secret_leaks(self):
        a, _ = app(status=404)
        st, _, body = a.handle("POST", "/api/live/observe", b'{"kind":"capture","resource_id":"CAP12345XYZ"}', "application/json")
        self.assertEqual(st, 502)
        self.assertIn(b"dbg-live-1", body)
        st, _, page = a.handle("POST", "/live/observe", b"kind=capture&resource_id=CAP12345XYZ", "application/x-www-form-urlencoded")
        self.assertIn(b"live-error", page)
        for secret in (b"cid-secret-xyz", b"sec-secret-xyz", b"TOKEN-ABC"):
            for r in (body, page, a.handle("GET", "/healthz")[2], a.handle("GET", "/live")[2]):
                self.assertNotIn(secret, r)

    def test_bad_ids_and_extra_fields_are_refused(self):
        a, calls = app()
        self.assertEqual(a.handle("POST", "/api/live/observe", b'{"kind":"capture","resource_id":"../x"}', "application/json")[0], 400)
        self.assertEqual(a.handle("POST", "/api/live/observe", b'{"kind":"capture","resource_id":"CAP12345XYZ","origin":"FIXTURE"}', "application/json")[0], 400)
        self.assertEqual(calls, [])


class OrderFlowTests(unittest.TestCase):
    def run_flow(self, argv, env=ENV, status=201, body=None):
        import io
        calls, out = [], io.StringIO()
        def t(method, url, headers, data):
            calls.append((method, url, data))
            if url.endswith("/v1/oauth2/token"):
                return 200, {}, b'{"access_token":"TOKEN-ABC"}'
            return status, {"paypal-debug-id": "dbg9"}, json.dumps(body or {"id": "ORDER12345", "status": "PAYER_ACTION_REQUIRED", "links": [{"rel": "payer-action", "href": "https://www.sandbox.paypal.com/checkoutnow?token=ORDER12345"}]}).encode()
        rc = flow.main(argv, env, t, out)
        return rc, out.getvalue(), calls

    def test_create_prints_approval_link_and_never_credentials(self):
        rc, out, calls = self.run_flow(["create"])
        self.assertEqual(rc, 0)
        self.assertIn("checkoutnow", out)
        self.assertNotIn("TOKEN-ABC", out)
        self.assertTrue(all("api-m.sandbox.paypal.com" in c[1] for c in calls))

    def test_capture_needs_explicit_confirmation(self):
        rc, out, calls = self.run_flow(["capture", "ORDER12345"])
        self.assertEqual((rc, calls), (2, []))

    def test_unapproved_capture_failure_is_reported_not_hidden(self):
        rc, out, _ = self.run_flow(["capture", "ORDER12345", "--yes-capture"], status=422, body={"name": "UNPROCESSABLE_ENTITY", "details": [{"issue": "ORDER_NOT_APPROVED"}]})
        self.assertEqual(rc, 3)
        self.assertIn("ORDER_NOT_APPROVED", out)

    def test_adapter_package_stays_read_only_and_does_not_import_the_flow_tool(self):
        import pathlib
        for f in pathlib.Path("paypal_adapter").glob("*.py"):
            t = f.read_text()
            self.assertNotIn("sandbox_order_flow", t)
            self.assertNotIn("import tools", t)


if __name__ == "__main__":
    unittest.main()
