# Delivery Gate, Phase 3 (corrected): PayPal observation adapter

Labels: **VERIFIED** = read in a primary PayPal document this session, **INFERRED**, **UNKNOWN**.
Status: fixtures only. No live sandbox call, UI, database, authentication or production integration exists. Stopped for review.
Run: `python3 -m unittest discover -s tests -t .` (248 tests).

Architecture, unchanged: `PayPal/API fixture -> adapter -> observed facts -> deterministic engine`. The adapter observes; it does not decide, map or default.

## Corrections made

### 1. Documented API semantics are separate from legal-policy equivalence
New `paypal_adapter/api_semantics.py` (data: `docs/phase3_semantics.json`). Each row records what PayPal's API reference says a value describes, the exact source URL with field anchor, the retrieval date, and a separate `legal_policy_equivalence` field that is `NOT_ESTABLISHED` for every row.

| `capture.seller_protection.status` | What PayPal's Orders v2 reference says it describes (paraphrased) | Source |
|---|---|---|
| ELIGIBLE | seller's PayPal balance stays intact if the customer claims non-receipt of an item OR the account holder claims they did not authorize the payment | `https://developer.paypal.com/api/orders/v2/definitions/capture#seller_protection.status` |
| PARTIALLY_ELIGIBLE | same, for the item-not-received claim only | same |
| NOT_ELIGIBLE | the transaction is not eligible for seller protection | same |

The claim types are stored in PayPal's own phrasing, not Delivery Gate's `ClaimCategory` names (a test enforces this), so no equivalence is implied. Observations carry an `api_semantics_ref` pointing at the row; the engine never sees it.
Equivalence with the Transaction Details eligibility mark stays unestablished: no PayPal document links the two; the API describes balance effects, not policy requirements; the policy says PayPal decides at dispute time. Recorded separately as a cross-surface note (VERIFIED): PayPal's Dispute Detail report defines "Partially Eligible Unauth Only" as unauthorized-only, which is a different scope from the API's PARTIALLY_ELIGIBLE. It is noted, not resolved, and no longer presented as the sole blocker.
The engine still receives the bare opaque token. Critical test (10 tokens x 3 claim categories): the policy assessment is identical.
Corrections to my earlier report: it described these meanings as "conflicting" and cited a sample payload pairing I could not re-verify; that sample claim is removed.

### 2. Exposure terminology
New `paypal_adapter/exposure.py` (example: `docs/phase3_exposure.json`). Three separate quantities:
- `original_transaction_value`: the capture amount (Orders v2). Not a disputed amount, not a bound.
- `disputed_amount`: the Disputes API `dispute_amount`. UNKNOWN unless a dispute linked to this capture has been read. VERIFIED: PayPal documents that it can differ from the original transaction's gross or net amount because customers can dispute part of a payment (`https://developer.paypal.com/api/customer-disputes/v1/definitions/dispute_search`).
- `potential_seller_exposure`: always UNKNOWN. No reviewed policy rule defines it; it is derived from neither of the other two.
No "floor" or "minimum" vocabulary appears in any adapter output (tested).
**Consequence you should review:** the Phase 1 SNAD rule reads `transaction_amount` as a conservative lower bound of exposure (`policy/rules/us.sp.snad.json`, `exposure_model.floor_fact`). I may not edit it, so the handoff no longer passes `transaction_amount`. The engine's SNAD assessment now shows `exposure_floor: null`, with `transaction_amount` listed as `AMOUNT_UNKNOWN` (SNAD stays NOT_COVERED). The engine's own labels ("exposure_floor", "known_lower_bound") remain in Phase 1 data until a reviewed policy change.

### 3. Source architecture (`paypal_adapter/sources.py`, `docs/phase3_sources.json`)
| Input | Source | Status |
|---|---|---|
| Merchant jurisdiction | merchant-asserted (`MERCHANT_INPUT / MERCHANT_ASSERTED`) or missing. Never presented as PayPal-verified. | helper implemented |
| Claim category / reason | Disputes API `reason`, raw value preserved, `CLAIM_REASON_TABLE_V1` | fixtures |
| Lifecycle stage | Disputes API `dispute_life_cycle_stage`, its own observation, no engine fact | fixtures |
| Dispute route | Disputes API `dispute_channel` only; INTERNAL -> PAYPAL_DISPUTE, others unknown | fixtures |
| Webhooks | `CUSTOMER.DISPUTE.CREATED/UPDATED/RESOLVED`: verified notification yields only a request for a fresh Disputes API read; payload yields no facts | interface only; verifier is injected, default fails closed, no network |
| Dispute Detail report | supplementary / reconciliation only, `mandatory: false` | not implemented |

Jurisdiction documentation (VERIFIED): PayPal documents a partner-only "show seller status" call whose sample includes `country`. Whether a direct-merchant integration can call it, and what `country` means, was not established, so it is not used.
Claim normalization table (documented in code): MERCHANDISE_OR_SERVICE_NOT_RECEIVED -> ITEM_NOT_RECEIVED and UNAUTHORISED -> UNAUTHORIZED_TRANSACTION are established (PayPal descriptions retrieved). MERCHANDISE_OR_SERVICE_NOT_AS_DESCRIBED is NOT normalized: it is listed in the docs but I retrieved no PayPal description of it, and I will not normalize from a name. All other reasons stay unknown.
Dispute facts reach the engine only when the dispute lists the capture id among its `seller_transaction_id`s. That is identifier equality only (PayPal does not state the two share a namespace); an unlinked dispute contributes nothing.

### 4. Issuer route is not inferred from claim reason
Route depends on `dispute_channel` alone. A test sweeps every documented reason x every stage x every channel: with no channel, route stays unknown whatever the reason or stage; with INTERNAL it is PAYPAL_DISPUTE; with EXTERNAL or ALERT it is unknown. Why EXTERNAL is not mapped to a card-issuer chargeback (VERIFIED): PayPal documents external disputes as including card chargebacks AND ACH returns (`https://developer.paypal.com/disputes/overview#external-disputes`), and the Phase 1 INR rule records that the retrieved policy does not establish handling for other routes such as bank reversals. ALERT is a pre-chargeback notification, not a filed dispute. The capture's `status_details.reason = CHARGEBACK` is observed but not read as a route.

### 5. Orders shipping address is not the Transaction Details address
Unchanged and now enforced by a handoff reason code: the address is observed (raw plus a key-renamed candidate), listed as withheld, never handed over.

### 6. Phase 1 engine unchanged
`tests/phase1_engine_hashes.json` records SHA-256 hashes of `engine.py`, `registry.py`, every file under `policy/` and `schemas/`, taken from your approved Phase 2 zip. A test fails if any differs or any file is added/removed. Verified byte-identical today. Files that differ from the Phase 2 zip: `delivery_gate/models.py`, `delivery_gate/adapters.py`, `delivery_extraction/bridge.py`, `delivery_extraction/review.py` (the authenticity refinement from the previous round: an additive optional `source_authenticity`).

## Changed files
Since the previous Phase 3 delivery:
- New code: `paypal_adapter/api_semantics.py`, `disputes.py`, `exposure.py`, `webhooks.py`, `sources.py`
- Modified: `paypal_adapter/adapter.py` (additive `api_semantics_ref`, per-context API name), `handoff.py` (amount withheld, dispute plan, linkage, jurisdiction helper), `inventory.py` (`policy_equivalence`, disputes rows, amount withheld)
- New fixtures: `fixtures/paypal/disputes/d01..d13` (synthetic, labelled `not_a_live_response`)
- New tests: `tests/test_paypal_corrections.py` (36), `tests/test_paypal_corrections_mutations.py` (3), `tests/phase1_engine_hashes.json`
- Updated tests (my own Phase 3 tests only): `tests/test_paypal_adapter.py`, `tests/test_paypal_mutations.py`
- Docs/tools: `docs/PHASE3.md`, `docs/paypal_field_inventory.json`, `docs/phase3_{semantics,sources,exposure,provenance_chain}.json`, `tools/phase3_demo.py`
**My error, now fixed:** an earlier edit left `tools/phase3_demo.py` empty in the previous delivery. It is rewritten and regenerates all the docs JSON.

## Test results
248 tests, all passing: 158 baseline (unmodified) + 90 Phase 3 (40 adapter, 4 adapter mutation, 7 authenticity, 36 corrections, 3 corrections mutation).
Mutation checks: 35, all caught, each by the property it breaks: 16 adapter (including "capture amount handed to the engine"), 6 authenticity, 13 corrections (promoting API meaning to policy equivalence, route inferred from reason, EXTERNAL mapped to chargeback, unestablished reason normalized, raw reason overwritten, linkage skipped, potential exposure derived, disputed amount assumed, amount called a floor, unverified webhook accepted, payload leaked into the read request, jurisdiction defaulted, dispute amount handed to the engine).

## Primary documentation used
- Orders v2 `capture` definition (read in full): https://developer.paypal.com/api/orders/v2/definitions/capture
- Disputes API reference and `dispute_search` definition (channel, stage, reason and amount definitions): https://developer.paypal.com/docs/api/customer-disputes/v1/ , https://developer.paypal.com/api/customer-disputes/v1/definitions/dispute_search
- Disputes overview (read in full: internal vs external disputes, ACH returns, lifecycle): https://developer.paypal.com/disputes/overview
- Disputes webhooks: https://developer.paypal.com/docs/disputes/webhooks ; webhook verification: https://developer.paypal.com/api/webhooks/v1/verify-webhook-signature-post
- Dispute Detail Custom report: https://developer.paypal.com/docs/reports/sftp-reports/dispute-detail-custom/
- Seller onboarding / show seller status (jurisdiction): https://developer.paypal.com/platforms/seller-onboarding/before-payment
Limits: several definitions were read through search excerpts, not full pages; the `show dispute details` response definition itself was not read in full; dispute fixtures are synthetic, so real sandbox shapes are UNVERIFIED.

## Unresolved questions
1. **SNAD exposure policy change.** Do you want a reviewed change so the rule's floor input becomes the Disputes API disputed amount (unknown when no dispute exists), the "floor / lower bound" wording is retired, and potential seller exposure gets a defined rule? Until then SNAD exposure shows unknown.
2. **EXTERNAL route.** Is there a documented way to tell a card chargeback from an ACH return? I found none (only the capture's `status_details.reason = CHARGEBACK`, present only for some pending/denied captures). Do you want EXTERNAL left unknown, or a reviewed mapping?
3. **Not-as-described normalization.** Needs a retrieved PayPal description of that reason (or your decision) before `established` is set.
4. **Capture-to-dispute linkage.** Identifier equality between a capture id and `seller_transaction_id` is unproven; a sandbox probe would settle it.
5. **Jurisdiction.** Is merchant assertion acceptable for the demo, and should I investigate whether the seller-status `country` is available to a direct merchant?
6. **Transaction Details eligibility label.** Which API, if any, exposes the label the policy names (Transaction Search was not checked)? Until found, the equivalence stays unestablished.
7. **Lifecycle stage.** It is recorded but the engine has no lifecycle fact; whether a stage should ever affect an assessment is a policy question.
8. **Webhook verification.** The documented verify-webhook-signature call needs a live app and credentials (Phase 4+).
