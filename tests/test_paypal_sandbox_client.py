"""Mocked tests for the read-only PayPal sandbox client. NO network is used and NO real credentials exist here:
a recording fake transport stands in for PayPal. These tests prove the client's behaviour and safeguards; they do NOT prove
that the live PayPal service accepts these requests. That is shown only by a real run, recorded in docs/PAYPAL_SANDBOX.md."""
import base64
import io
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from paypal_adapter import sandbox_check
from paypal_adapter.adapter import canonical, observe_order, sha256_hex
from paypal_adapter.handoff import PayPalFixtureSource
from paypal_adapter.sandbox_client import (SANDBOX_BASE, PayPalSandboxClient, SandboxConfigError, SandboxRequestError, audit_record,
                                           default_transport, load_credentials, observe_live)

ROOT = Path(__file__).resolve().parent.parent
CID, SECRET, TOKEN = "AcanaryClientId123", "ECANARY-SECRET-DO-NOT-LEAK-987", "A21AAcanaryAccessTokenXYZ"
ORDER = json.loads((ROOT / "fixtures/paypal/01_normal.json").read_text())["response"]
CAPTURE = ORDER["purchase_units"][0]["payments"]["captures"][0]
FIXED = datetime(2026, 11, 11, 12, 0, 0, tzinfo=timezone.utc)


class Fake:
    """Records every request; replies from a route table. Never touches the network."""
    def __init__(self, token_status=200, resource_status=200, resource_body=None, debug="debug-123"):
        self.calls, self.token_status, self.resource_status, self.debug = [], token_status, resource_status, debug
        self.resource_body = resource_body

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, dict(headers), body))
        if url.endswith("/v1/oauth2/token"):
            b = json.dumps({"access_token": TOKEN, "token_type": "Bearer"}) if self.token_status == 200 else json.dumps({"error": "invalid_client"})
            return self.token_status, {"paypal-debug-id": self.debug}, b.encode()
        body_obj = self.resource_body if self.resource_body is not None else (CAPTURE if "/captures/" in url else ORDER)
        data = body_obj if isinstance(body_obj, bytes) else json.dumps(body_obj).encode()
        return self.resource_status, {"paypal-debug-id": self.debug}, data


def client(fake=None):
    return PayPalSandboxClient(CID, SECRET, transport=fake or Fake(), clock=lambda: FIXED)


class Configuration(unittest.TestCase):
    def test_missing_variables_are_named_but_no_values_are_involved(self):
        with self.assertRaises(SandboxConfigError) as cm:
            load_credentials({})
        self.assertIn("PAYPAL_SANDBOX_CLIENT_ID", str(cm.exception))
        self.assertIn("PAYPAL_SANDBOX_CLIENT_SECRET", str(cm.exception))

    def test_blank_values_count_as_missing(self):
        with self.assertRaises(SandboxConfigError):
            load_credentials({"PAYPAL_SANDBOX_CLIENT_ID": "  ", "PAYPAL_SANDBOX_CLIENT_SECRET": "x"})

    def test_cli_without_credentials_makes_no_request_and_exits_2(self):
        fake, out = Fake(), io.StringIO()
        rc = sandbox_check.main(["--capture", "ABCDE12345"], env={}, transport=fake, out=out)
        self.assertEqual(rc, 2)
        self.assertEqual(fake.calls, [], "no network call may happen without credentials")
        self.assertIn("no request was made", out.getvalue())

    def test_identifiers_are_validated_so_a_path_cannot_be_injected(self):
        c = client()
        for bad in ("", "../x", "a/b", "AB CD", "abc", "x" * 65, "ABCDE?x=1", "ABCDE#frag", None):
            with self.assertRaises(SandboxConfigError, msg=repr(bad)):
                c.fetch_capture(bad)


class RequestShape(unittest.TestCase):
    def test_token_request_is_the_documented_client_credentials_call_to_the_sandbox_host(self):
        f = Fake(); client(f).fetch_capture("ABCDE12345")
        method, url, headers, body = f.calls[0]
        self.assertEqual((method, url), ("POST", "https://api-m.sandbox.paypal.com/v1/oauth2/token"))
        self.assertEqual(headers["Authorization"], "Basic " + base64.b64encode(f"{CID}:{SECRET}".encode()).decode())
        self.assertEqual(headers["Content-Type"], "application/x-www-form-urlencoded")
        self.assertEqual(body, b"grant_type=client_credentials")

    def test_capture_read_is_a_single_get_with_a_bearer_token_and_no_body(self):
        f = Fake(); client(f).fetch_capture("ABCDE12345")
        self.assertEqual(len(f.calls), 2)
        method, url, headers, body = f.calls[1]
        self.assertEqual((method, url), ("GET", "https://api-m.sandbox.paypal.com/v2/payments/captures/ABCDE12345"))
        self.assertEqual(headers["Authorization"], "Bearer " + TOKEN)
        self.assertIsNone(body)

    def test_order_read_path(self):
        f = Fake(); client(f).fetch_order("ORDER12345")
        self.assertEqual(f.calls[1][1], "https://api-m.sandbox.paypal.com/v2/checkout/orders/ORDER12345")

    def test_the_client_is_read_only_whatever_it_is_asked_to_do(self):
        f = Fake(); c = client(f)
        c.fetch_capture("ABCDE12345"); c.fetch_order("ORDER12345")
        self.assertEqual([m for m, *_ in f.calls], ["POST", "GET", "GET"], "only the OAuth POST and GETs")
        for method, path in (("POST", "/v2/payments/captures/ABCDE12345/refund"), ("DELETE", "/v2/checkout/orders/X1234"), ("GET", "/v1/customer/disputes/PP-D-1")):
            with self.assertRaises(SandboxRequestError):
                c._send(method, path, {})

    def test_the_token_is_requested_once_per_client(self):
        f = Fake(); c = client(f)
        c.fetch_capture("ABCDE12345"); c.fetch_capture("FGHIJ67890")
        self.assertEqual(sum(1 for m, u, *_ in f.calls if u.endswith("/oauth2/token")), 1)

    def test_every_request_targets_only_the_sandbox_host(self):
        f = Fake(); c = client(f); c.fetch_capture("ABCDE12345"); c.fetch_order("ORDER12345")
        for _, url, *_ in f.calls:
            self.assertTrue(url.startswith(SANDBOX_BASE + "/"))
        self.assertEqual(SANDBOX_BASE, "https://api-m.sandbox.paypal.com")


class NetworkGuard(unittest.TestCase):
    """default_transport is the only code that can touch a network; it must refuse anything but the sandbox host BEFORE any connection
    is even attempted (a refusal that only happens because the connection failed would not count)."""
    def test_refuses_production_and_foreign_hosts_and_plain_http_without_attempting_a_connection(self):
        import urllib.request
        attempted = []
        real = urllib.request.build_opener
        urllib.request.build_opener = lambda *a, **k: attempted.append(1) or real(*a, **k)
        try:
            for url in ("https://api-m.paypal.com/v2/payments/captures/ABCDE12345", "https://evil.example/v2/x", "http://api-m.sandbox.paypal.com/v2/x",
                        "https://api-m.sandbox.paypal.com.evil.example/v2/x", "https://user:pw@api-m.sandbox.paypal.com/v2/x",
                        "https://api-m.sandbox.paypal.com:8443/v2/x", "ftp://api-m.sandbox.paypal.com/x"):
                with self.assertRaises(SandboxRequestError, msg=url) as cm:
                    default_transport("GET", url, {}, None)
                self.assertIn("refused", str(cm.exception), url)
        finally:
            urllib.request.build_opener = real
        self.assertEqual(attempted, [], "no connection may even be attempted for a non-sandbox URL")

    def test_redirects_are_refused(self):
        from paypal_adapter.sandbox_client import _NoRedirect
        self.assertIsNone(_NoRedirect().redirect_request(None, None, 302, "Found", {}, "https://evil.example/"))


class ResponseHandling(unittest.TestCase):
    def test_raw_response_is_preserved_unchanged_and_provenance_is_real(self):
        raw = json.dumps(CAPTURE)
        fetch = client(Fake(resource_body=raw.encode())).fetch_capture("ABCDE12345")
        self.assertEqual(fetch.raw_body, raw)
        self.assertEqual(fetch.response, CAPTURE)
        self.assertEqual(fetch.http_status, 200)
        self.assertEqual(fetch.paypal_debug_id, "debug-123")
        self.assertEqual(fetch.observed_at, "2026-11-11T12:00:00Z", "observed_at is the retrieval time from the clock, never invented")

    def test_live_observations_are_origin_sandbox_never_fixture(self):
        cap = observe_live(client().fetch_capture("ABCDE12345"))
        self.assertEqual(cap.origin, "SANDBOX")
        self.assertTrue(all(o.origin == "SANDBOX" and o.observed_at == "2026-11-11T12:00:00Z" for o in cap.observations))
        self.assertTrue(cap.resource_ref.startswith("sandbox:"))
        fixture = PayPalFixtureSource(ROOT / "fixtures/paypal").load_wrapper("01_normal")
        fx = observe_order(fixture["response"], origin="FIXTURE")
        self.assertEqual(fx.captures[0].origin, "FIXTURE")
        self.assertTrue(fx.captures[0].resource_ref.startswith("fixture:"))

    def test_response_hash_covers_exactly_the_returned_payload(self):
        fetch = client().fetch_capture("ABCDE12345")
        self.assertEqual(observe_live(fetch).response_sha256, sha256_hex(canonical(CAPTURE)))
        self.assertEqual(audit_record(fetch)["response_sha256"], sha256_hex(canonical(CAPTURE)))

    def test_opaque_status_values_pass_through_verbatim_and_are_not_interpreted(self):
        from paypal_adapter.handoff import to_case
        odd = json.loads(json.dumps(CAPTURE)); odd["seller_protection"]["status"] = "SOME_NEW_TOKEN"
        cap = observe_live(client(Fake(resource_body=odd)).fetch_capture("ABCDE12345"))
        sp = cap.find("seller_protection.status")
        self.assertEqual(sp.raw_value, "SOME_NEW_TOKEN", "raw value preserved exactly as returned")
        self.assertEqual(sp.enum_state, "UNDOCUMENTED_TOKEN")
        cautions = " ".join(to_case(cap).cautions)
        self.assertIn("SOME_NEW_TOKEN", cautions)
        self.assertIn("opaque", cautions, "the handoff flags it as an opaque value, not a policy outcome")

    def test_order_with_one_capture_is_observed_and_several_must_be_chosen_explicitly(self):
        cap = observe_live(client().fetch_order("ORDER12345"))
        self.assertEqual(cap.origin, "SANDBOX")
        self.assertEqual(cap.order_id, ORDER["id"])
        multi = json.loads((ROOT / "fixtures/paypal/11_multi_capture.json").read_text())["response"]
        from paypal_adapter.adapter import MalformedPayPalResponse
        with self.assertRaises(MalformedPayPalResponse):
            observe_live(client(Fake(resource_body=multi)).fetch_order("ORDER12345"))

    def test_order_shipping_address_is_not_a_transaction_details_address(self):
        """A live Orders API shipping address stays an unverified Orders-API observation; the live path never promotes it."""
        from paypal_adapter.handoff import to_case
        cap = observe_live(client().fetch_order("ORDER12345"))
        addr = cap.find("unit.shipping.address")
        self.assertIsNotNone(addr, "the live order's shipping address is observed and preserved")
        self.assertEqual(addr.semantics, "NOT_VERIFIED")
        self.assertEqual(addr.origin, "SANDBOX")
        names = [f.name for f in to_case(cap).case.transaction_facts]
        self.assertNotIn("transaction_details_address", names)
        self.assertFalse([n for n in names if "address" in n], "no address-bearing fact is handed to the engine from the Orders API")


class Failures(unittest.TestCase):
    def test_token_failure_reports_status_and_debug_id_but_no_secret(self):
        with self.assertRaises(SandboxRequestError) as cm:
            client(Fake(token_status=401)).fetch_capture("ABCDE12345")
        self.assertEqual((cm.exception.status, cm.exception.debug_id), (401, "debug-123"))
        for leaked in (SECRET, CID, TOKEN, base64.b64encode(f"{CID}:{SECRET}".encode()).decode(), "invalid_client"):
            self.assertNotIn(leaked, str(cm.exception))

    def test_not_found_and_server_errors_are_errors_not_empty_results(self):
        for st in (401, 404, 500):
            with self.assertRaises(SandboxRequestError) as cm:
                client(Fake(resource_status=st)).fetch_capture("ABCDE12345")
            self.assertEqual(cm.exception.status, st)
            self.assertNotIn(TOKEN, str(cm.exception))

    def test_non_json_or_non_object_bodies_are_rejected(self):
        for body in (b"<html>nope</html>", b"[1,2]", b"\xff\xfe"):
            with self.assertRaises((SandboxRequestError, UnicodeDecodeError)):
                client(Fake(resource_body=body)).fetch_capture("ABCDE12345")


class SecretsNeverLeak(unittest.TestCase):
    def test_repr_and_str_are_redacted(self):
        c = client()
        encoded = base64.b64encode(f"{CID}:{SECRET}".encode()).decode()
        for s in (repr(c), str(c), f"{c}", "%s" % c, str(vars(c).keys())):
            for leaked in (SECRET, CID, encoded):
                self.assertNotIn(leaked, s)

    def test_audit_record_and_saved_file_contain_no_credentials_or_token(self):
        f = Fake(); fetch = client(f).fetch_capture("ABCDE12345")
        with tempfile.TemporaryDirectory() as d:
            out = io.StringIO()
            rc = sandbox_check.main(["--capture", "ABCDE12345", "--save", d],
                                    env={"PAYPAL_SANDBOX_CLIENT_ID": CID, "PAYPAL_SANDBOX_CLIENT_SECRET": SECRET}, transport=f, out=out)
            self.assertEqual(rc, 0)
            files = list(Path(d).glob("*.json"))
            self.assertEqual(len(files), 1)
            saved = files[0].read_text()
            blob = saved + out.getvalue() + json.dumps(audit_record(fetch))
        for leaked in (SECRET, CID, TOKEN, "Authorization", "Bearer", "Basic "):
            self.assertNotIn(leaked, blob)
        rec = json.loads(saved)
        self.assertEqual(rec["_origin"], "LIVE_SANDBOX")
        self.assertEqual(rec["response"], CAPTURE)


class CommandLine(unittest.TestCase):
    ENV = {"PAYPAL_SANDBOX_CLIENT_ID": CID, "PAYPAL_SANDBOX_CLIENT_SECRET": SECRET}

    def run_cli(self, argv, fake):
        out = io.StringIO()
        return sandbox_check.main(argv, env=self.ENV, transport=fake, out=out), out.getvalue()

    def test_success_output_labels_the_origin_and_prints_raw_values(self):
        rc, text = self.run_cli(["--capture", "ABCDE12345"], Fake())
        self.assertEqual(rc, 0)
        self.assertIn("ORIGIN: LIVE_SANDBOX", text)
        self.assertIn("HTTP 200", text)
        self.assertIn("paypal-debug-id: debug-123", text)
        self.assertRegex(text, r"observed_at   : \d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")
        self.assertIn(CAPTURE["id"], text)
        self.assertIn("PayPal makes the final decision", text)
        self.assertNotIn("protected", text.lower().replace("not a seller protection decision", ""))
        for leaked in (SECRET, CID, TOKEN):
            self.assertNotIn(leaked, text)

    def test_http_failure_exits_3_with_the_debug_id(self):
        rc, text = self.run_cli(["--capture", "ABCDE12345"], Fake(resource_status=404))
        self.assertEqual(rc, 3)
        self.assertIn("HTTP 404", text)
        self.assertIn("debug-123", text)

    def test_order_with_several_captures_needs_an_explicit_choice(self):
        multi = json.loads((ROOT / "fixtures/paypal/11_multi_capture.json").read_text())["response"]
        rc, text = self.run_cli(["--order", "ORDER12345"], Fake(resource_body=multi))
        self.assertEqual(rc, 4)
        rc2, text2 = self.run_cli(["--order", "ORDER12345", "--select", multi["purchase_units"][0]["payments"]["captures"][0]["id"]], Fake(resource_body=multi))
        self.assertEqual(rc2, 0)


class ExistingGuardsStillHold(unittest.TestCase):
    def test_the_original_stub_still_refuses_and_fixtures_remain_the_offline_default(self):
        from delivery_gate.adapters import PayPalSandboxSource
        with self.assertRaises(NotImplementedError):
            PayPalSandboxSource().load_case("x")
        case = PayPalFixtureSource(ROOT / "fixtures/paypal").load_case("01_normal")
        self.assertTrue(case.transaction_facts)
        self.assertTrue(all(f.provenance.source_ref.startswith("fixture:") for f in case.transaction_facts), "offline path is still labelled FIXTURE")


if __name__ == "__main__":
    unittest.main()
