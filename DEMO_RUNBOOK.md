# Delivery Gate: demo runbook

For someone who did not build the project. Every step below was executed against a fresh clone in Chromium. Total time: about 5 minutes for a first run.

## 1. Start

**Requirements:** Python 3.12, a terminal, a web browser. **No `pip install` is needed.**

```bash
cd delivery-gate
python3 -m delivery_ui --port 8080
```

Expected terminal output: `Delivery Gate demo UI on http://127.0.0.1:8080  (fixture data; Ctrl+C to stop)`

Open **http://127.0.0.1:8080** in the browser.

**Environment variables:** none required. Optional (live extraction only): `ANTHROPIC_API_KEY` **and** `EXTRACTION_MODEL`, both set before starting the server. Leave them **unset for the demo**; the demo needs no API key and works fully offline. See `.env.example`.

**Different port:** `python3 -m delivery_ui --port 8090`, then use that port in the URL.

## 2. Reset to the starting state

State is held in memory only. You get a clean start by either:

- **restarting the server** (Ctrl+C, then run the command again), or
- on the **Overview** page, in the **Demo scenarios** card, clicking **Reset demo data**.

After a reset, DG-20481 shows **Requirements not demonstrated** and has exactly one piece of evidence, the merchant note **A11**. Always reset before recording.

## 3. The demo sequence

The page header shows a **Fixture data** badge throughout: all payments are fixtures, not live PayPal data.

| # | Action | Expected result |
|---|---|---|
| 1 | Open **Overview**. | Page loads; "Demo scenarios" lists the fixture payments. |
| 2 | Click **Payments**, click the row **DG-20481** (a side panel opens), then click **View assessment**. | The payment page opens: **$480.00 USD**, Order #1048, dispute reason **Item not received**. |
| 3 | Read the banner. | **Requirements not demonstrated.** Summary on the right: six "Not demonstrated", two "Your statement only". |
| 4 | On the payment page click **Review & update evidence**, then open **A11**. | The merchant's note ("…we're protected. I'll win this dispute for sure."). Panel says **Nothing to review**. |
| 5 | Return to the payment page (Payments → DG-20481 → **View assessment**) and open the **What changes?** tab. Click **Compare**. | Labelled **Hypothetical.** Current: *Requirements not demonstrated*. With additional evidence (hypothetical): *Requirements demonstrated*. "The result would change. PayPal makes the final decision." Lists five facts it would add and which requirements change. |
| 6 | Click back to the payment overview. | Still **Requirements not demonstrated**: the what-if did not change the case. |
| 7 | On the payment page click **Review & update evidence**. Expand **Sample evidence library**, click the sample **A01** (FedEx email). | Message **"Sample A01 added: 7 fact(s) found."** |
| 8 | Open **A01**. Click the fact **Tracking number**. | The exact text `774912340001` is highlighted in the original email. Authenticity: **Not reviewed**. |
| 9 | Return to the payment overview. | Banner: **Needs human review** (unreviewed evidence is not trusted). |
| 10 | Open **A01**, type a reviewer name (e.g. `Casey Reviewer`), click **I attest this is a genuine carrier document**. | Source authenticity: **Reviewed**, with the reviewer's name and a statement that it is not independently verified. It never says "Verified". |
| 11 | Return to the payment overview. | **Requirements demonstrated** and "PayPal makes the final decision." |
| 12 | On the payment page, open the **Provenance** tab. | An **Assessment fingerprint** beginning `dee7a99f…` (the same fingerprint the what-if produced) and an activity log entry: "Casey Reviewer attested that A01 is a genuine carrier document (4 fact(s) approved)." |
| 13 | **Overview → Reset demo data.** | DG-20481 is back to **Requirements not demonstrated** with only A11. |

**The starting fingerprint is `ee92cbca…`.** If the values differ from these, the policy files, fixtures or code differ from the tested version: see Recovery.

## 4. Optional second payments (only if time allows)

- **DG-20479** ($129): requirements demonstrated, PayPal decides (clean carrier evidence).
- **DG-20472** ($760, $320 disputed): conflicting addresses; needs human review; the two amounts stay separate.
- **DG-20475** ($215): merchant assertion only; not treated as carrier confirmation.
- **DG-20468** ($84.50): unauthorized transaction; PayPal status unknown, no claim either way.

## 5. Recovery

| Problem | Fix |
|---|---|
| `Address already in use` | Another server holds port 8080. Stop it, or start with `--port 8090`. |
| Browser shows "unable to connect" | The server is not running. Start it (section 1) and reload. |
| Screen is in an unexpected state mid-take | Overview → **Reset demo data**, then restart the sequence. |
| After Reset the page still looks old | Hard-refresh (Ctrl/Cmd+Shift+R). |
| A pasted document says it "cannot be read offline" | Expected: only the 15 built-in samples can be read without live extraction. Use the **Sample evidence library**. |
| Values or fingerprints differ from this document | Confirm you are on the intended version, then run `python3 -m unittest discover -s tests -t .`. Expect 427 tests, OK. |
| Server crashes or hangs | Ctrl+C, start again. State is in memory, so you lose nothing that matters. |
| Windows: hash-guard test fails | Make sure the checkout kept LF line endings (`.gitattributes` enforces this on a fresh clone). |

## 6. Shut down

Press **Ctrl+C** in the terminal running the server. There is nothing to clean up: no database, no files written.

## 7. Verify the build (optional)

```bash
python3 -m unittest discover -s tests -t .
```

Expected: `Ran 427 tests ... OK` in about 50 seconds. The 21 browser tests need Playwright and Chromium (`pip install playwright && playwright install chromium`); without them they skip.
