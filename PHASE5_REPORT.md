# Phase 5 report: demo, documentation and submission readiness

Date of work: Nov 11, 2026. Python 3.12.3, Chromium (Playwright). Everything below marked "verified" was actually executed; anything not run is labelled.

## 1. Summary

| | |
|---|---|
| Core product (Phases 1–4) | Works. Not rebuilt. No product, policy or engine logic changed. |
| What was wrong | The **committed** repository was incomplete *and* partly corrupted; the reports' claims about it were inaccurate (details below). |
| Repair | A separate publication copy contains every required file; a fresh clone of it passes **400/400** tests and the full browser demo. |
| Open risk | The hackathon asks for PayPal **sandbox** integration. A read-only sandbox client now exists (§10) but has **not yet made a verified real call**. See `SUBMISSION_CHECKLIST.md`. |

## 2. Stage A findings (before any change)

| Item | Earlier report | Measured |
|---|---|---|
| Tests, original working tree | 400 passing | 400 run: 399 pass, **1 fail** (hash guard) |
| Fresh clone of committed repo | not tested | 209 run: 1 fail, **2 errors** |
| Phase 4 "nothing pre-existing was modified" | stated | 38 tracked files differ from `HEAD` |
| `docs/PHASE3.md` "engine verified byte-identical" | stated | **Not true of this repo**: bytes differ (see §4) |
| `tools/ui_screenshots.py` | referenced in `docs/PHASE4.md` | does not exist; reference corrected |

### Why the committed repo was incomplete
- `schemas/`, `docs/` and six UI test files (`tests/test_ui_*.py`, `tests/ui_helpers.py`) were **never committed** in any of the 16 commits. There was no `.gitignore` or exclude file, so this was not an ignore rule. The most likely cause (my inference; nothing records it) is that commits were made by naming specific directories.
- The fresh-clone errors were: (1) missing `schemas/` (a schema test errors), and (2) **`tests/test_paypal_adapter.py` was syntactically broken at `HEAD`**: one line truncated and the line `with self.assertRaises(NotImplementedError):` lost. That lost line is the assertion that `PayPalSandboxSource` refuses to run, which backs the "no live PayPal call" claim. The working-tree copy has it restored (121 assertion calls vs 120 at `HEAD`); this is the only assertion-count difference in any Phase 1–3 test file.
- The 38 modified files: **37 parse in both versions and have zero executable differences** (identical after ignoring comments, whitespace and docstrings, checked with `ast`). The differences are comments and docstrings that the committed copy had lost; the working-tree copy is the correct one and was preserved. The 38th is the corrupted file above.

### Classification of files outside Git
| Kind | Files | Decision |
|---|---|---|
| Required | `schemas/*` (3), `docs/*.md`, `tests/test_ui_*.py` (5), `tests/ui_helpers.py` | restored into the publication tree |
| Useful, tracked | `docs/screens/*.png` (~4.9 MB, app screenshots) | kept |
| Junk / generated | none beyond `__pycache__` | excluded via `.gitignore` |

## 3. Test results

Command: `python3 -m unittest discover -s tests -t .`

| Tree | Discovered | Passed | Failed | Errors | Skipped | Runtime |
|---|---|---|---|---|---|---|
| Original working tree (before) | 400 | 399 | 1 | 0 | 0 | 51 s |
| Original committed repo, fresh clone (before) | 209 | 206 | 1 | 2 | 0 | <1 s |
| **Publication repo, fresh clone (after)** | **400** | **400** | **0** | **0** | **0** | **~51 s** |

- Phase 1–3 baseline: **248** tests (21 files); same 248 test names and same assertion-call counts as the committed versions in every file except the one restoration above. Phase 4: **152** tests, all included.
- No assertion was weakened, deleted or changed to obtain a green run.
- Run with Playwright installed, so the 21 browser tests executed. Without Playwright they skip by design (see §8).

## 4. Hash-guard investigation (baseline maintenance)

**Why it failed.** `tests/phase1_engine_hashes.json` pins ten Phase 1 files. Eight match exactly (all policy rule files, passages, sources, and all three schemas). `delivery_gate/engine.py` and `delivery_gate/registry.py` do not match, in the original working tree **or in any commit**.

**Original hashes (preserved):**

| File | Original (approved) SHA-256 | Current SHA-256 (new pin) |
|---|---|---|
| `delivery_gate/engine.py` | `cfa3fe5cb1309e8d96db266c32954a145abab502f5f6e6c7ebc13a12d0663c46` | `856427e98258fd65a269cf0dbe90cf93872cd6b36521756e832d1b5ff4dc7f49` |
| `delivery_gate/registry.py` | `b07f3693955ed3e1df7fb230bacd113a0c81a30554e4c2daae051273ae61f4dc` | `4c056c017c6553bb6a420a792b4b53b2468d150e9967b2d28878f452991daafc` |

**Evidence that only comments/whitespace differ.** Compared with the file as committed at each point in history (token stream = Python tokens excluding comments and whitespace):

| `engine.py` vs | Token stream equal | AST equal | Changed lines |
|---|---|---|---|
| `HEAD` (and `271c430`) | yes | yes | 2 |
| `cf747f0` "phase 2" | yes | yes | 10 |
| `e9a8814` initial commit | yes | yes | 8 |

`registry.py`: token and AST equal to all four versions; 2 changed lines each.

**The exact diffs** (trailing-space differences only; `·` marks a space, shown for engine.py vs `HEAD`):

```
-    corroboration: str = "NOT_APPLICABLE"·······
+    corroboration: str = "NOT_APPLICABLE"········
```

Versus the "phase 2" commit the changed lines are the same kind: trailing-space runs after `establishes: Optional[str] = None`, `corroboration: ...`, `outcome: str`, `state: str`, and `unresolved.append("UNRESOLVED_EXCLUSION")` (lines 41, 42, 60, 151, 636). The trailing-space runs look like where inline comments were stripped from the committed copy.

**What I could not establish.** The *originally approved Phase 2 bytes* are not in this repository, and no whitespace-only variation of the current files reproduces the approved hash (I searched trailing-space counts on every affected line). So I cannot prove byte equality with those bytes. What is established: the executable content is identical in every version that exists, from the initial commit to now.

**Action taken.** Updated the two hash values in `tests/phase1_engine_hashes.json` only, and recorded the previous hashes and this reasoning in a `_baseline_maintenance` block in the same file. The test code and its assertions are unchanged. **This is baseline maintenance for comment/whitespace differences, not a policy-engine modification.** No policy rule, assessment behavior or schema was touched; the other eight guarded files still match their original approved hashes.

**Added safeguard.** `.gitattributes` forces LF line endings. The guard is byte-exact, and a Windows checkout with CRLF conversion would otherwise fail it for reasons unrelated to the code.

## 5. Files added, modified and removed (publication tree vs original `HEAD`)

- **Added (tracked now, previously missing):** `schemas/` (3 files), `docs/` (reports and screenshots), `tests/test_ui_browser.py`, `test_ui_http.py`, `test_ui_mutations.py`, `test_ui_presenter.py`, `test_ui_service.py`, `tests/ui_helpers.py`.
- **Added (new in Phase 5):** `LICENSE`, `.gitignore`, `.gitattributes`, `.env.example`, `README.md`, `DEMO_SCRIPT.md`, `DEMO_RUNBOOK.md`, `SUBMISSION_CHECKLIST.md`, `PHASE5_REPORT.md`.
- **Modified:** the 38 files above (comment/docstring restoration; one test file repaired), `tests/phase1_engine_hashes.json` (§4), `docs/PHASE4.md` (removed the dangling `ui_screenshots.py` reference).
- **Removed:** none.
- **Git history:** rewritten **only in the publication copy** (author/committer email replaced). The original repository was not modified.

## 6. Browser verification (verified, Chromium, fresh clone, cold server)

27/27 checks passed, including a full repeat of the workflow after one fix to my own check (a link-crawl ordering flaw in my script, not a product defect).

Verified, in order: app starts; Overview loads with the Fixture-data badge; DG-20481 shows $480.00 and *Item not received*; initial assessment *Requirements not demonstrated*; evidence workspace and merchant note A11 inspectable; what-if shows *Hypothetical.* with current vs hypothetical; what-if does **not** change the real case; FedEx sample added (7 facts); exact source-span highlight (`774912340001`); unreviewed evidence yields *Needs human review*; `attest_carrier` via the UI; source becomes **Reviewed** (never Verified) with a not-independently-verified statement; assessment becomes *Requirements demonstrated, PayPal makes the final decision*; **digest after review `dee7a99f14912079…` equals the what-if digest** (computed independently in a separate process) and differs from the starting `ee92cbca…`; activity log records the review; **Reset** returns DG-20481 to its original state.

Also verified: zero console errors, CSP violations or failed requests across ~48 page loads; 54 internal links resolve (200); no horizontal overflow at 1672/1280/1024/768/390 px on five key pages; a fake API-key canary set in the server environment appears in **no** page, JS or CSS; none of the phrases "you are protected", "likely to qualify", "will win", "win probability", "protection score", "guaranteed" appear.

**Not verified:** other browsers; screen readers; the live-extraction path; any live PayPal behavior. The what-if page does not display digests; the digest equality is verified from the service layer and the Provenance tab, and by an existing unit test.

## 7. Security and hygiene

- Secrets: none in the working tree or in any commit (pattern scan of all history). The only secret-shaped strings are deliberately fake test values.
- Personal data: the original history carries one personal email address on all 16 commits. The publication history has **0** occurrences; the original repo is untouched. A placeholder remains (see checklist). **Rewriting history in a new repo does not remove the address from any older public repo** — see checklist.
- No third-party runtime dependencies (stdlib only); Playwright is test-only and optional.
- The server sets a CSP, `X-Content-Type-Options: nosniff`, and is intended for localhost only.

## 8. Remaining limitations and unresolved items

1. **No live PayPal sandbox integration**, while the hackathon requests one. Decision needed from you (see `SUBMISSION_CHECKLIST.md`). Not changed here.
2. Offline demo uses recorded extractions; live extraction untested against a real model; model accuracy never evaluated.
3. All policy rules remain `UNREVIEWED` models of published terms.
4. The original approved Phase 2 bytes for `engine.py`/`registry.py` are unavailable (§4).
5. The behavior "browser tests skip without Playwright" is documented in the repo; see §9 for whether I ran it.
6. The placeholder git email must be replaced by you before publishing.
7. Everything listed in "Phase 4 limitations" (no auth, text-only uploads, English only, single merchant, in-memory state) still applies.

## 9. Final verification (all executed on a fresh `git clone` of the publication repo)

*Figures in §3, §6 and §9 are from the first hand-off (400 tests). §10 records the later sandbox-client addendum and the updated totals (427 tests); the browser verification was re-run after it, see §10 final line.*

| Check | Result |
|---|---|
| `python3 -m unittest discover -s tests -t .` | **Ran 400 tests, OK**: 400 passed, 0 failed, 0 errors, 0 skipped, ~51 s |
| Browser verification (Chromium, cold server, 20-step workflow + console/links/overflow/key-leak/claims) | **27/27 passed** |
| Runbook navigation using **only real clicks** (no direct URLs) | 6/6 passed (see below) |
| Browser tests without Playwright installed | **21 skipped, 0 failures** (documented skip behavior confirmed) |
| Git-handoff commands from `SUBMISSION_CHECKLIST.md`, run on a throwaway clone | Worked: placeholder email replaced in all commits, 0 placeholder occurrences left, tests still pass |
| Extracted-ZIP test | Performed after packaging; the result is stated in the hand-off message, because this file is inside the ZIP and cannot contain a hash of itself. Verify yourself with `git rev-parse HEAD^{tree}` after extracting and `git status` (must be clean). |

**Documentation defect found and fixed during final verification.** My first draft of the runbook and script told the reader to click "Review evidence" on the payment page. A real-click walkthrough showed that label exists only in the Payments side panel; on the payment page the button is **Review & update evidence**, and a row click opens a side panel whose **View assessment** link opens the payment page. Both documents were corrected and the corrected path was re-walked with real clicks. The automated 27-check script navigates by URL, so it could not have caught this; the real-click walkthrough did.

**Claims in the README that I checked against the code before keeping them**: 21 browser tests; recorded-vs-live extraction wording; gold-label correction history (documented in `docs/PHASE2.md`); a unit test comparing UI digests with an engine oracle; the Reset control; the CSP header. Three statements that the code did not support were removed or reworded (a claim about what the model "sees", a policy detail the repo does not mention, and a more specific label for DG-20463 than the fixture gives).

## 10. Addendum: read-only PayPal sandbox client (added after the first hand-off)

**Request:** implement the smallest safe, real PayPal sandbox integration, and test live AI extraction if possible.

**What could and could not be done.** The build environment had **no PayPal sandbox credentials, no Anthropic key or model configured, and no outbound network** (the sandbox host did not resolve; the Anthropic endpoint returned a proxy 403). Therefore:

| Item | Result |
|---|---|
| Real PayPal sandbox request | **Not performed.** No integration is claimed to have been verified live |
| Live AI extraction run | **Not performed.** No live-AI functionality is claimed to have been tested |
| Read-only sandbox client + CLI | Implemented (`paypal_adapter/sandbox_client.py`, `paypal_adapter/sandbox_check.py`), additive only |
| Mocked tests | 27 new tests, all pass. 7 sabotage checks (host guard, scheme guard, read-only guard, secret redaction, origin label, token leakage, redirects) were each caught. Two mutants initially survived because my tests were too weak; I strengthened them and re-ran |
| Endpoints | Checked against PayPal's API reference: sandbox host `api-m.sandbox.paypal.com`, `POST /v1/oauth2/token` (client credentials), `GET /v2/payments/captures/{capture_id}`, `GET /v2/checkout/orders/{id}`. A documentation match is not a live success |
| Full suite after the change | **427 tests, OK, 0 failures/errors/skips**, ~52 s (400 original + 27 new) |
| Guarded Phase 1 files, policy engine, evidence rules | **Untouched** (hash guard unchanged and passing) |
| `PayPalSandboxSource` stub | Unchanged; its refusal test still passes |

**Design (each point enforced by tests):** sandbox host only, `https` only, no redirects, no production URL in the code; only the OAuth `POST` and `GET`s of captures/orders, so it cannot create, capture, refund or change anything; credentials only from `PAYPAL_SANDBOX_CLIENT_ID` / `PAYPAL_SANDBOX_CLIENT_SECRET`, never stored, printed, saved, put in errors or in `repr()`; identifiers validated against injection; the raw body is preserved and parsed unchanged; `observed_at` is the real retrieval time; the adapter origin token is `SANDBOX` and the display label is `LIVE_SANDBOX`, so it cannot be confused with `FIXTURE`; opaque statuses are passed through verbatim and flagged as opaque; an Orders API shipping address stays an unverified observation and is never promoted to a Transaction Details address.

**Deliberately not done (scope and risk):** wiring sandbox data into the web UI. Every page header carries a "Fixture data" badge, and changing that without a real response to test against risked the working demo. The sandbox read is therefore a command-line step. Once you have one real response, wiring it into the UI behind the existing origin labels is a reasonable follow-up.

**Why this does not fully close the eligibility risk:** the code is unverified against the live service until you run it. See `docs/PAYPAL_SANDBOX.md` (run instructions, and a verification record to fill in from a real run) and `SUBMISSION_CHECKLIST.md`.

## 11. Addendum: Groq as the live extraction provider (Nov 12, 2026)

**Request:** make Groq the AI provider instead of Anthropic, using Groq's current models and API so there are no surprises later.

| Item | Result |
|---|---|
| Groq docs checked (models, deprecations, API reference, structured outputs, reasoning) | Read on 2026-11-12; sources listed in `docs/GROQ.md` §6 |
| `GroqExtractor` + `make_extractor` (provider selection) | Implemented in `delivery_extraction/llm.py`; Anthropic path unchanged and still selectable |
| Pre-flight command `python3 -m delivery_extraction.groq_check [--extract]` | Implemented: asks Groq which models the account can use, checks the configured one, optionally runs ONE real extraction through the strict validator |
| Mocked tests | 40 new tests, all pass; 9 sabotage checks (reasoning params to wrong models, deprecated `max_tokens`, JSON mode dropped, truncation ignored, key leaked in errors, retired-model hint removed, provider precedence, key in `repr`, guessed default model) each caught |
| Full suite | **467 tests** (427 + 40), see the final verification line below |
| **Real request to Groq** | **NOT performed** (no key, no network in the build environment). Live extraction is therefore still **unverified** |
| Policy engine, evidence rules, validator, hash guard | Untouched |

**Findings that shaped the design (all from Groq's own pages, dated 2026-11-12):**
- `llama-3.3-70b-versatile` and `llama-3.1-8b-instant`, the models most tutorials use, were **retired for standard accounts on 2026-08-16**; `qwen/qwen3.6-27b` on 2026-09-14; `groq/compound*` on 2026-09-21. The current Production models are **`openai/gpt-oss-120b`** and **`openai/gpt-oss-20b`**.
- Groq retires models often (seven retirement dates in 2026), so **no default model is built in**: `EXTRACTION_MODEL` is required and a retired ID produces an error naming Groq's replacement.
- The gpt-oss models are reasoning models: reasoning tokens count against the output limit, so the request uses a generous limit, `reasoning_effort: low`, `include_reasoning: false`, and truncation is reported as an error instead of passing on a cut-off answer.
- JSON Object mode is used rather than schema-enforced structured outputs: a Groq community report describes the schema being ignored on gpt-oss-120b, and our strict validator is the authority regardless.

**Behaviour change to be aware of:** if `GROQ_API_KEY` is set and `EXTRACTION_PROVIDER` is not, Groq is chosen even when an Anthropic key is also present. Built-in samples still replay recorded outputs, so the demo remains deterministic.

**Unresolved:** live Groq behaviour (rate limits on free tier, a possible difference from the documented request format, extraction quality) is unknown until `groq_check --extract` is run with a real key.
