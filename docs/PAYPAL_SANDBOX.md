# PayPal sandbox read: guide and verification record

## Status (read this first)

| Item | Status |
|---|---|
| Read-only sandbox client (`paypal_adapter/sandbox_client.py`) and command (`python3 -m paypal_adapter.sandbox_check`) | **Implemented** |
| 27 automated tests with a mocked transport (`tests/test_paypal_sandbox_client.py`) | **Pass.** Seven deliberate sabotage checks (host guard, scheme guard, read-only guard, redaction, origin label, token leakage, redirects) were each caught by the tests |
| A **real request to the PayPal sandbox** | **NOT YET PERFORMED.** The environment where this was written had no sandbox credentials and no network access, so it could not be run there |
| Live AI extraction (`python -m eval.evaluate --live`) | **NOT YET PERFORMED**, for the same reason (no API key, no model configured, no network) |
| Sandbox data shown inside the web UI | **Not implemented.** The sandbox read is a command-line tool; the web app still shows fixture data only |

Until section 4 below is filled in from a real run, do **not** describe this as a verified or working live integration. It is code that has passed mocked tests against PayPal's *documented* request and response shapes. The documented shapes were checked against PayPal's API reference (token endpoint, `GET /v2/payments/captures/{capture_id}`, `GET /v2/checkout/orders/{id}`, sandbox host `api-m.sandbox.paypal.com`), but a documentation match is not the same as a successful call.

## 1. What it does

- Fetches one **real sandbox** capture (or order) with a single read-only `GET`, after the standard OAuth client-credentials token request.
- Hands the unmodified response to the existing Phase 3 observation adapter with origin `SANDBOX`, so every observation carries the real retrieval time, a hash of the response, and the PayPal field path it came from.
- Prints the origin as **`LIVE_SANDBOX`**, the HTTP status, PayPal's `paypal-debug-id`, and each observed field **verbatim**. Fixture data is labelled `FIXTURE` everywhere else; the two cannot be confused because the origin token is part of every observation and every resource reference (`sandbox:paypal-capture:…` versus `fixture:paypal-capture:…`).
- Optionally saves an audit record (request metadata, the raw body, the parsed response, its hash) with `--save DIR`. It never contains credentials, tokens or request headers. The default folder name `live_captures/` is git-ignored.

## 2. What it deliberately does not do

- It cannot contact anything except `https://api-m.sandbox.paypal.com`; there is no production URL in the code, redirects are refused, and a URL on any other host is rejected before a connection is attempted.
- It cannot create, capture, refund or change anything: the only requests are the OAuth token `POST` and `GET`s of captures and orders.
- It does not interpret anything. Opaque PayPal status values (for example `seller_protection.status`) are shown as received and flagged as opaque. They are **not** mapped to a Seller Protection outcome, and the deterministic policy engine is untouched.
- It does not treat an Orders API shipping address as a Transaction Details address. A live order's shipping address is recorded as an unverified Orders-API observation and is not promoted to an engine fact (covered by a test).
- It does not read disputes and does not handle webhooks.

## 3. How to run it (about 15 minutes with a PayPal developer account)

I have **not** been able to execute these steps. They follow PayPal's documented flow; if anything differs from PayPal's current documentation, trust PayPal's documentation and tell me.

1. **Credentials.** At <https://developer.paypal.com> go to *Apps & Credentials*, select **Sandbox**, create (or open) a REST app, and copy its **Client ID** and **Secret**. PayPal creates default sandbox business and personal accounts for you.
2. **A sandbox capture to read.** The tool only reads, so a sandbox payment must already exist. Create one outside Delivery Gate with PayPal's Orders API (<https://developer.paypal.com/docs/api/orders/v2/>): create an order with intent `CAPTURE`, approve it in a browser while signed in as the sandbox **personal** (buyer) account, then capture it. The capture response contains `purchase_units[0].payments.captures[0].id`; that is the **capture ID**. (The order ID works too.)
3. **Run the check** (credentials go in the environment only, never on the command line or in a file you commit):

```bash
export PAYPAL_SANDBOX_CLIENT_ID="..."
export PAYPAL_SANDBOX_CLIENT_SECRET="..."
python3 -m paypal_adapter.sandbox_check --capture <CAPTURE_ID> --save live_captures
# or, for an order:   python3 -m paypal_adapter.sandbox_check --order <ORDER_ID> --save live_captures
```

Exit codes: `0` success, `2` configuration problem (no request was made), `3` the request failed (status and debug id are printed), `4` a response arrived but could not be observed.

A successful run begins like this (shape only; values will differ):

```
ORIGIN: LIVE_SANDBOX   (a real request to https://api-m.sandbox.paypal.com; not a fixture)
GET /v2/payments/captures/<id>  ->  HTTP 200
paypal-debug-id: <PayPal's id for this call>
observed_at   : <the real UTC retrieval time>
```

`HTTP 200` plus a `paypal-debug-id` you can find in the developer dashboard's API call logs is the evidence that the call was real.

## 4. Live verification record (fill this in after a real run)

> Leave this section as-is until a real run has happened. Do not fill it from a mocked test.

| Field | Value |
|---|---|
| Date and time (UTC) | _not yet run_ |
| Command used (without credentials) | _not yet run_ |
| HTTP status | _not yet run_ |
| `paypal-debug-id` | _not yet run_ |
| Response SHA-256 printed by the tool | _not yet run_ |
| Saved audit record file | _not yet run_ |
| Anything that differed from the documented shapes | _not yet run_ |

## 5. Live AI extraction check (also not yet run)

Live extraction now uses **Groq** by default; see `docs/GROQ.md` for the model guidance and the full procedure. In short:

```bash
export GROQ_API_KEY="..."
export EXTRACTION_MODEL="openai/gpt-oss-120b"
python3 -m delivery_extraction.groq_check --extract    # confirms the model is available, then runs ONE real extraction through the strict validator
python3 -m eval.evaluate --live                        # optional: all 15 artifacts; writes eval/results_live.json
```

Record the printed result in `docs/GROQ.md` or here **after** running it. Remember the standing caveat: the earlier recorded-output evaluation measured the pipeline, not a live model.
