# Delivery Gate

**Delivery Gate helps an online seller see, before PayPal decides, what their evidence actually demonstrates in a disputed payment, what is missing or uncertain, and what would change if they supplied more.**

> **Read this first.** The web application runs on **fixture data** and its offline demo reads **recorded** extraction outputs, not a live AI model. A separate, read-only **PayPal sandbox command** exists (`python3 -m paypal_adapter.sandbox_check`), tested with mocked HTTP; **a real sandbox request has not yet been run and recorded**, and sandbox data is not yet shown in the web UI. See `docs/PAYPAL_SANDBOX.md` for the exact status. Delivery Gate does **not** decide disputes and never says a seller is "protected": **PayPal makes the final decision.** It is a hackathon prototype, not a production system, and it is not endorsed by or affiliated with PayPal.

Built for the [PayPal AI Hackathon 2026](https://paypalaihackathon.devpost.com/).

---

## 1. The problem

A buyer opens an *Item Not Received* dispute on a $480 phone. The seller has a tracking number and a note saying "it was probably delivered, PayPal should cover this, I'll win for sure". Sellers in this position usually cannot tell:

1. what PayPal is actually reporting about the payment,
2. which pieces of evidence they really have (versus things they merely assert),
3. which documented requirements are still unmet, and
4. which single piece of evidence would change the picture.

## 2. What Delivery Gate does

For one disputed payment it:

- keeps **what PayPal reports** visually separate from **what the merchant provided**;
- reads evidence documents (for example a carrier delivery email) into a small, closed set of **facts**, each pinned to the **exact words** it came from;
- refuses to trust new evidence until a **human reviewer** looks at it;
- compares the resulting facts with the **documented requirements currently modeled** and reports, requirement by requirement, what is demonstrated, not demonstrated, contradicted or needs review;
- answers **"what changes?"** by re-running the same assessment on hypothetical evidence, clearly labelled as hypothetical and never altering the real case.

### Worked example (the demo, payment `DG-20481`)

| Step | What you see |
|---|---|
| Start | $480 payment, buyer says item not received. Only evidence on file: the seller's overconfident note. Result: **Requirements not demonstrated** (6 requirements not demonstrated, 2 resting on the seller's own statement only). |
| What changes? | Add a sample FedEx delivery email *hypothetically*: result would change to **Requirements demonstrated**. The real case is untouched. |
| Add it for real | 7 facts are extracted, each highlighted at its exact position in the email. The assessment becomes **Needs human review**: new evidence is not automatically trusted. |
| Reviewer attests | The source becomes **Reviewed** (not "Verified"; the UI says it has not been independently verified). Result: **Requirements demonstrated. PayPal makes the final decision.** |
| Check | The assessment fingerprint after review equals the one the what-if predicted. |

## 3. What it does not do

- It does not decide disputes, guarantee Seller Protection, predict wins, or output scores or percentages.
- It is not a payment processor, escrow service or dashboard, and it never moves money.
- It does not verify documents. A reviewer attestation records that a *person* looked; it can never produce `VERIFIED`, which is reserved for a future carrier-API source.
- It does not invent policy: no undocumented thresholds or deadlines, and no fuzzy address matching.

## 4. How it works

```
evidence text ─► AI extraction ─► validation ─► normalized facts ─► deterministic assessment ─► UI
 (artifact)       (proposes)      (checks)      (+ provenance)       (the only authority)     (presents)
```

**Principle: AI extracts evidence. Deterministic code evaluates documented requirements.**

### Role of AI
The extraction layer (`delivery_extraction/`) turns a document into candidate facts from a **closed vocabulary of 11 fact types**. Every fact must carry an exact source span, who said it (attribution), how it was stated, and any ambiguity. The model's output is **validated before anything reaches the engine**: malformed output, unknown fact types, policy-conclusion language and prompt-injection attempts are rejected (see `docs/PHASE2.md`). The extraction prompt forbids policy, protection or eligibility conclusions, and the model never decides whether anything satisfies a requirement. Its self-reported confidence is shown to the user but is **never used** in the assessment.

### Role of the deterministic engine
`delivery_gate/engine.py` is plain Python with no randomness, clock or network. Given the same facts it always returns the same assessment, with a content digest ("fingerprint"). Unknown facts stay unknown and are never converted into passes. Outcomes: `NOT_COVERED`, `REQUIREMENTS_NOT_DEMONSTRATED`, `REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES`, `UNSUPPORTED_JURISDICTION`, `UNKNOWN`. The UI only displays this result; a test rebuilds every payment without the UI and requires an identical digest.

### Provenance and human review
Every fact records where it came from. A merchant's statement can never become carrier-confirmed evidence. A reviewer may attest that a document is a genuine carrier document (`attest_carrier`), which yields **REVIEWED**. The reviewer's name is typed (there is no authentication in this prototype), so a merchant can attest their own document; the UI states that this is not independent verification.

### Supported policy scope
US Seller Protection, physical goods: **Item Not Received**, **Unauthorized Transaction**, and **Significantly Not as Described** (modeled as `NOT_COVERED`). Rules are modeled from PayPal pages cited in `policy/sources.json` (Seller Protection and Purchase Protection pages dated January 26, 2026; the PayPal User Agreement; PayPal developer API pages). **All rules are marked `UNREVIEWED`** and every assessment says so. This is a model of published terms, not legal advice.

## 5. PayPal integration status

| Component | Status |
|---|---|
| PayPal observation adapter (`paypal_adapter/`) for Orders v2 captures and Disputes API responses | Implemented, **tested against fixtures only** |
| Read-only PayPal **sandbox** client and command (`paypal_adapter/sandbox_client.py`, `sandbox_check.py`): one OAuth token request plus `GET` of a capture or order, origin-labelled `LIVE_SANDBOX`, raw response and provenance preserved | **Implemented and tested with a mocked transport (27 tests). A real sandbox call has NOT yet been run and recorded** (the author's build environment had no credentials or network). Not shown in the web UI. The older `PayPalSandboxSource` stub still deliberately refuses to run |
| Webhook handling | Designed as "verified notification triggers a fresh API read"; **not connected to any live endpoint** |
| The eight payments in the UI | **Fixture data**, labelled "Fixture data" on every page |

PayPal API status values (for example `seller_protection.status`) are kept as opaque observations; they are not treated as equivalent to legal-policy outcomes. Orders API shipping addresses are never treated as Transaction Details addresses. Dispute route, not-as-described semantics and capture-to-dispute linkage remain unknown where the documentation does not establish them, and the UI shows them as unknown.

## 6. Requirements and installation

- **Python 3.12** (developed and tested on 3.12.3). The application and the 446 non-browser tests use the **standard library only**: no `pip install` is needed to run the app.
- **Optional, for the 21 browser tests:** `pip install playwright` then `playwright install chromium`. Without Playwright those tests skip automatically.

```bash
git clone <your-repository-url> delivery-gate
cd delivery-gate
```

## 7. Configuration

None is required. Offline, the app reads the **15 built-in sample documents** from recorded extraction outputs and runs entirely on fixtures.

To enable live extraction of arbitrary pasted text, set a provider key **and** a model in the server's environment (see `.env.example`; the app does not load `.env` files itself). **Groq is the recommended provider** (`docs/GROQ.md`):

```bash
export GROQ_API_KEY="your-groq-key"
export EXTRACTION_MODEL="openai/gpt-oss-120b"   # no default is built in; Groq retires models often
python3 -m delivery_extraction.groq_check --extract   # pre-flight: confirms the model is available, runs one real extraction
```

The key is read server-side only and is never sent to the browser. Anthropic remains supported as an alternative (`ANTHROPIC_API_KEY`). **The live path (Groq or Anthropic) has been tested only with a mocked transport, never against a real model; run the pre-flight command above to test it yourself.**

## 8. Run the application

```bash
python3 -m delivery_ui --port 8080
```

Open <http://127.0.0.1:8080>. State is in memory and resets when the server restarts; the **Reset demo data** control (or `POST /reset`) also restores the starting state.

## 9. Run the tests

```bash
python3 -m unittest discover -s tests -t .
```

Expected: **467 tests** (248 from Phases 1–3, 152 UI tests, 27 sandbox-client tests, 40 Groq tests), about 50 seconds. `tests/phase1_engine_hashes.json` pins the engine, registry, policy and schema files; a failure there means one of them changed and needs review.

## 10. Run the demo

Follow [`DEMO_RUNBOOK.md`](DEMO_RUNBOOK.md) for the exact click-by-click sequence and expected result at each step. [`DEMO_SCRIPT.md`](DEMO_SCRIPT.md) is the narrated script for a video under three minutes. Screenshots from the running app are in `docs/screens/`.

## 11. The eight fixture payments

| Payment | Amount | Shows |
|---|---|---|
| **DG-20481** | $480 | Missing delivery evidence, then the what-if (the main demo) |
| DG-20479 | $129 | Clean carrier evidence: requirements demonstrated, PayPal decides |
| DG-20472 | $760 (disputed $320) | Conflicting delivery addresses: human review; transaction and disputed amounts kept separate |
| DG-20475 | $215 | Merchant assertion only: not treated as carrier confirmation |
| DG-20468 | $84.50 | Unauthorized transaction: PayPal status unknown, no claim either way |
| DG-20463 | $312 | External dispute route: unknown |
| DG-20460 | $58 | Not-as-described reason: semantics unknown in the API context |
| DG-20455 | $59.99 | No dispute to assess |

## 12. Known limitations

- The web app is fixture-driven. The sandbox client exists but its **first real run is still to be performed and recorded**; sandbox data is not displayed in the UI; no disputes or webhooks are read live. In-memory state; single demo merchant; English only.
- The offline demo reads **recorded** extractions for the 15 built-in samples only. Other text cannot be read offline; the UI says so. Live extraction must be configured for it.
- **Live model accuracy has not been evaluated.** The earlier evaluation (15 hand-labelled artifacts, 67 gold facts) used outputs authored by Claude, not a live model run, and its gold labels were corrected once after a failed first run. Treat those metrics as a test of the pipeline, not of model accuracy.
- Text uploads only (`.txt`, `.eml`, `.csv`, `.md`, 200 KB). No PDFs or images.
- No authentication; reviewer identity is a typed name.
- What-if covers evidence already on the payment or a library sample, not free-form hypotheticals.
- Tested in Chromium only; no full screen-reader audit.
- Policy rules are `UNREVIEWED` models of published terms. Several PayPal semantics are deliberately left unknown rather than guessed.

## 13. Security and evidence handling

- No credentials are stored in the repository; `.env` is git-ignored and `.env.example` holds placeholders.
- The API key is server-side only; tests assert it never appears in pages, API responses or JavaScript.
- The server sends a Content-Security-Policy, escapes all rendered text, and accepts only whitelisted request fields (a request cannot supply a result, status or authenticity).
- Uploaded text is treated as data, never as instructions; the extraction layer has injection and malformed-output safeguards.
- The demo server is for local use (`127.0.0.1`) and is not hardened for public exposure.

## 14. Repository layout

| Path | Contents |
|---|---|
| `delivery_gate/` | Policy models, rule registry, deterministic engine (Phase 1) |
| `policy/`, `schemas/` | Rule definitions, cited source passages, JSON schemas |
| `delivery_extraction/`, `eval/` | Evidence extraction, validation, review bridge; evaluation corpus (Phase 2); Groq/Anthropic live extractors and the `groq_check` pre-flight command |
| `paypal_adapter/`, `fixtures/paypal/` | PayPal observation adapter and fixtures (Phase 3); read-only sandbox client and `sandbox_check` command (Phase 5) |
| `delivery_ui/` | Browser application: server, presenter, renderer, fixtures (Phase 4) |
| `tests/` | 467 tests |
| `docs/` | Phase reports (`PHASE1`–`PHASE4`) and screenshots |
| `tools/` | Walkthrough and fixture-building scripts |

## 15. License

Licensed under the **Apache License, Version 2.0**. See [`LICENSE`](LICENSE).
