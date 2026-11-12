# Delivery Gate

**Know what your delivery evidence demonstrates, what is missing, and what could change before PayPal makes its decision.**

Delivery Gate is an evidence-assessment prototype for online sellers handling disputed PayPal payments. It separates payment information from merchant-provided evidence, extracts relevant facts, evaluates them against modeled requirements, and shows where human review is needed.

Built for the [PayPal AI Hackathon 2026](https://paypalaihackathon.devpost.com/).

> **Project status and limitations**
>
> The web application currently runs on fixture data. Its offline demo uses recorded AI extraction outputs rather than a live language model.
>
> A separate, read-only PayPal Sandbox client is implemented and tested with mocked HTTP responses. A real sandbox request has not yet been run and recorded, and sandbox data is not currently displayed in the main web application.
>
> Delivery Gate does not decide disputes, guarantee Seller Protection, or replace PayPal's processes. PayPal makes the final decision. This is a hackathon prototype, not a production system, and it is not affiliated with or endorsed by PayPal.
>
> See `docs/PAYPAL_SANDBOX.md` for the detailed integration status.

---

## 1. The problem

Consider a seller facing a $480 Item Not Received dispute.

The seller has a tracking number and a note claiming the package was probably delivered. But what does the available evidence actually establish?

The seller needs to understand four things:

1. What does PayPal report about the payment?
2. Which facts are supported by submitted evidence, and which are only merchant assertions?
3. Which documented requirements remain unmet?
4. What additional evidence could change the assessment?

Delivery Gate addresses this problem by turning scattered evidence into a structured, traceable assessment.

## 2. What Delivery Gate does

For an individual disputed payment, Delivery Gate:

- Separates PayPal-reported transaction information from merchant-provided evidence.
- Extracts facts from documents, such as carrier delivery emails.
- Links every extracted fact to the exact source text supporting it.
- Tracks attribution, ambiguity, and evidence provenance.
- Requires human review before newly extracted evidence is trusted.
- Compares reviewed facts against modeled requirements.
- Reports what is demonstrated, not demonstrated, contradicted, or still needs review.
- Supports hypothetical evidence scenarios so sellers can see how an assessment would change without modifying the actual case.

### Worked example: Payment DG-20481

The main demo follows a $480 payment with an Item Not Received dispute.

| Stage | What happens |
|---|---|
| Initial assessment | Only the seller's own statement is available. Six requirements are not demonstrated, while two rely only on the seller's assertion. |
| What-if assessment | A sample FedEx delivery email is added hypothetically. The assessment changes to requirements demonstrated. The real case remains untouched. |
| Evidence submission | The email is added to the actual case. Seven facts are extracted and linked to their exact source positions. |
| Human review | The assessment changes to Needs Human Review. The newly submitted evidence is not automatically trusted. |
| Reviewer attestation | A reviewer attests to the document. Its status becomes REVIEWED, not VERIFIED. |
| Final assessment | The modeled requirements are demonstrated. PayPal still makes the final decision. |

The assessment fingerprint after review matches the fingerprint predicted by the hypothetical assessment.

## 3. What Delivery Gate does not do

Delivery Gate has deliberate boundaries:

- It does not decide disputes or predict whether a seller will win.
- It does not guarantee Seller Protection.
- It does not generate risk scores or percentages.
- It is not a payment processor, escrow service, or money-transfer application.
- It does not move or capture funds.
- It does not independently authenticate uploaded documents.
- It does not treat a merchant's statement as carrier-confirmed evidence.
- It does not invent undocumented PayPal policies, thresholds, or deadlines.
- It does not use fuzzy address matching to manufacture a match.

A reviewer attestation means a person has reviewed a document. It does not establish independent authenticity.

## 4. How it works

The system separates evidence extraction from policy evaluation.

```text
Evidence document
       |
       v
  AI extraction
  (proposes facts)
       |
       v
  Validation
  (checks model output)
       |
       v
  Normalized facts
  (with provenance)
       |
       v
  Deterministic assessment
  (evaluates requirements)
       |
       v
  Human review and UI
```

**Core principle: AI extracts evidence. Deterministic code evaluates documented requirements.**

### AI extraction

The extraction layer lives in `delivery_extraction/`.

It converts submitted documents into candidate facts from a closed vocabulary of 11 fact types.

Each fact must include:

- The exact source text supporting it.
- Who made the statement.
- How the information was expressed.
- Any detected ambiguity.

Model output is validated before it reaches the assessment engine.

Malformed output, unknown fact types, policy conclusions, and prompt-injection attempts are rejected.

The extraction prompt explicitly prohibits the model from making policy, protection, or eligibility decisions.

Model-reported confidence is displayed for reference but is never used to determine the assessment.

See `docs/PHASE2.md`.

### Deterministic assessment engine

The assessment engine lives in `delivery_gate/engine.py`.

It is implemented in plain Python without randomness, clock access, or network calls.

Given the same facts, it produces the same assessment and content digest, called a fingerprint.

Unknown information remains unknown. Missing evidence is never silently converted into a passing result.

The engine supports these outcomes:

- `NOT_COVERED`
- `REQUIREMENTS_NOT_DEMONSTRATED`
- `REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES`
- `UNSUPPORTED_JURISDICTION`
- `UNKNOWN`

The UI presents the engine's result rather than independently deciding the outcome.

A separate test rebuilds every payment without the UI and checks that the resulting digest is identical.

### Evidence provenance and human review

Every extracted fact records its source.

A merchant statement cannot become carrier-confirmed evidence simply because it mentions a tracking number or delivery status.

A reviewer can attest that a document is a genuine carrier document using `attest_carrier`. This produces the status `REVIEWED`.

It does not produce `VERIFIED`. That status is reserved for a future independently confirmed carrier API source.

The reviewer enters their name manually. The prototype has no authentication system, meaning a merchant can attest to their own document.

The interface explicitly communicates that this is not independent verification.

### Modeled policy scope

The current modeled scope covers US Seller Protection for physical goods:

- Item Not Received
- Unauthorized Transaction
- Significantly Not as Described, modeled as `NOT_COVERED`

Rules are modeled from published PayPal materials referenced in `policy/sources.json`, including Seller Protection and Purchase Protection pages dated January 26, 2026, the PayPal User Agreement, and PayPal developer documentation.

**All modeled rules are marked `UNREVIEWED`.** Assessments communicate this limitation.

This is a technical model of published terms, not legal advice or an authoritative interpretation of PayPal policy.

## 5. PayPal integration status

The project includes a PayPal observation adapter and a separate read-only Sandbox client.

| Component | Implementation status |
|---|---|
| PayPal Orders v2 observation adapter | Implemented; tested against fixtures |
| PayPal capture observation | Implemented; tested against fixtures |
| PayPal Disputes API response adapter | Implemented; tested against fixtures |
| Read-only Sandbox client | Implemented; tested with mocked HTTP |
| Real Sandbox API request | Not yet run and recorded |
| Sandbox data in the main web UI | Not implemented |
| Webhook integration | Designed, but not connected to a live endpoint |

The Sandbox command is:

```bash
python3 -m paypal_adapter.sandbox_check
```

The client supports an OAuth token request followed by a read-only GET request for a PayPal order or capture.

Responses are labeled `LIVE_SANDBOX`, with raw response data and provenance preserved.

The Sandbox client has 27 tests using a mocked transport. These tests do not establish that a real PayPal Sandbox request has succeeded.

The older `PayPalSandboxSource` stub deliberately refuses to run.

### Important data distinctions

PayPal API fields such as `seller_protection.status` are preserved as observations. They are not treated as equivalent to legal-policy conclusions.

The system also avoids making unsupported assumptions about:

- Orders API shipping addresses versus Transaction Details addresses.
- Dispute routes and not-as-described semantics.
- Capture-to-dispute relationships where the documentation does not establish them.

Where the available information is insufficient, the assessment remains unknown.

The eight payments shown in the main application are fixture records, labeled as fixture data throughout the interface.

See `docs/PAYPAL_SANDBOX.md`.

## 6. Requirements

- Python 3.12. The project was developed and tested on Python 3.12.3.
- The application uses Python's standard library and requires no package installation to run.
- Playwright is optional and required only for browser tests.

To install the optional browser-testing dependency:

```bash
pip install playwright
playwright install chromium
```

Without Playwright, the corresponding browser tests skip automatically.

## 7. Installation and configuration

Clone the repository:

```bash
git clone https://github.com/Teedor01/delivery_gate.git
cd delivery_gate
```

No configuration is required for the offline demo.

The application uses fixture data and recorded extraction outputs for its 15 built-in sample documents.

### Optional: Enable live AI extraction

To extract facts from arbitrary pasted text using a live model, configure a provider API key and model in the server environment.

The application does not load `.env` files automatically.

Groq is the recommended provider.

```bash
export GROQ_API_KEY="your-groq-key"
export EXTRACTION_MODEL="openai/gpt-oss-120b"
```

Run the pre-flight check:

```bash
python3 -m delivery_extraction.groq_check --extract
```

This checks model availability and attempts one real extraction.

The API key remains server-side and is never sent to the browser.

Anthropic is also supported as an alternative through `ANTHROPIC_API_KEY`.

**Live Groq and Anthropic extraction have been tested with mocked transports only.** A real model request has not yet been run and recorded in this repository. Run the pre-flight command to test your own configuration.

## 8. Running the application

Start the application:

```bash
python3 -m delivery_ui --port 8080
```

Open:

http://127.0.0.1:8080

The application is intended for local demonstration.

State is held in memory and resets when the server restarts. The Reset Demo Data control, or `POST /reset`, restores the starting fixture state.

## 9. Running the tests

Run:

```bash
python3 -m unittest discover -s tests -t .
```

The documented expected result is 467 tests.

The test suite covers the engine, UI, Sandbox client, and extraction integrations. Playwright is optional for browser testing.

`tests/phase1_engine_hashes.json` pins the engine, registry, policy, and schema files. A failure indicates that one of these files has changed and requires review.

**Test-count note:** The reported breakdown in the project notes should be reconciled with the actual test discovery output before treating 467 as the final verified count.

## 10. Running the demo

The repository includes two guides:

- `DEMO_RUNBOOK.md`: step-by-step instructions with expected results.
- `DEMO_SCRIPT.md`: narration for a video under three minutes.

Screenshots from the running application are available in `docs/screens/`.

## 11. Included fixture payments

The application includes eight fixture payments covering different assessment scenarios.

| Payment | Amount | Scenario |
|---|---:|---|
| DG-20481 | $480 | Missing delivery evidence and the main what-if demonstration |
| DG-20479 | $129 | Carrier evidence with requirements demonstrated |
| DG-20472 | $760, disputed amount $320 | Conflicting delivery addresses |
| DG-20475 | $215 | Merchant assertion without carrier confirmation |
| DG-20468 | $84.50 | Unauthorized transaction with unknown PayPal status |
| DG-20463 | $312 | External dispute route remains unknown |
| DG-20460 | $58 | Not-as-described semantics remain unknown |
| DG-20455 | $59.99 | No dispute to assess |

These records are demonstration fixtures, not live customer transactions.

## 12. Known limitations

The current prototype has the following limitations:

**Application and integrations**
- The main web application is fixture-driven.
- The Sandbox client has not yet completed a recorded real API request.
- Sandbox data is not displayed in the main web UI.
- Live disputes and webhooks are not connected.
- Application state is in memory.
- The demo supports a single merchant.
- English is the only supported language.

**Evidence extraction**
- Offline extraction uses recorded outputs for the 15 built-in sample documents.
- Arbitrary text requires a configured live extraction provider.
- Live model accuracy has not been evaluated.
- Supported uploads are `.txt`, `.eml`, `.csv`, and `.md`, with a 200 KB limit.
- PDF and image extraction are not supported.

**Review and security**
- There is no authentication system.
- Reviewer identity is a manually entered name.
- What-if assessments use existing payment evidence or a library sample, not unrestricted free-form hypothetical documents.
- The application has been tested in Chromium only.
- A full screen-reader accessibility audit has not been completed.

**Policy**
- All modeled policy rules remain `UNREVIEWED`.
- Some PayPal API semantics are deliberately left unknown rather than inferred.

### Evaluation limitations

The earlier evaluation used 15 hand-labeled artifacts containing 67 gold facts.

However, the evaluated extraction outputs were authored by Claude rather than generated by a live model. The gold labels were also corrected once after an initial failed run.

Consequently, those results evaluate aspects of the extraction and validation pipeline. They are not evidence of live model accuracy.

## 13. Security and evidence handling

The prototype includes several safeguards:

- No credentials are stored in the repository.
- `.env` is Git-ignored, and `.env.example` contains placeholders.
- Provider API keys remain server-side.
- Tests check that API keys do not appear in pages, API responses, or JavaScript.
- The server sends a Content Security Policy.
- Rendered text is escaped.
- Request fields are whitelisted. Clients cannot submit their own assessment result, status, or authenticity designation.
- Uploaded documents are treated as data, not instructions.
- Extraction includes safeguards against prompt injection and malformed model output.

The demo server binds to `127.0.0.1` by default. It is not hardened for public internet exposure.

## 14. Repository structure

| Directory | Purpose |
|---|---|
| `delivery_gate/` | Policy models, rule registry, and deterministic assessment engine |
| `policy/` | Modeled requirements and policy source references |
| `schemas/` | Data schemas |
| `delivery_extraction/` | Evidence extraction, validation, review bridge, and live provider integrations |
| `eval/` | Evaluation corpus and extraction evaluation tools |
| `paypal_adapter/` | PayPal observation adapter and read-only Sandbox client |
| `fixtures/paypal/` | PayPal fixture records |
| `delivery_ui/` | Web application, server, presenter, renderer, and fixtures |
| `tests/` | Automated tests |
| `docs/` | Phase reports, integration notes, screenshots, and documentation |
| `tools/` | Walkthrough and fixture-building scripts |

## 15. License

Delivery Gate is licensed under the **Apache License 2.0**.

See the [`LICENSE`](LICENSE) file.

---

## Optional: PayPal Sandbox page

With the following environment variables configured:

```bash
PAYPAL_SANDBOX_CLIENT_ID
PAYPAL_SANDBOX_CLIENT_SECRET
```

The `/live` page can retrieve a Sandbox order or capture using the read-only client.

The response is labeled `LIVE_SANDBOX` and displayed separately from fixture payments.

See `docs/PAYPAL_SANDBOX.md` for implementation details and current limitations.