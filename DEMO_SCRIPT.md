# Delivery Gate: demo video script

**Target length: about 2 min 30 s. Hard limit: under 3:00.** Narration is about 240 words (about 1:35 of speech); the rest of the 2:30 is the on-screen actions and one-second pauses on each banner. Pace yourself to the timestamps in the table, not to a words-per-minute target. I have not recorded or timed a voice-over, so do one practice read and confirm the final video is under 3:00.

**Before recording:** follow `DEMO_RUNBOOK.md` sections 1–2 (start the server, click **Reset demo data**). Use a browser window about 1600 px wide, zoom 100%. Start on **Payments**. Record the real running app; there are no slides. Every action below was performed and verified in Chromium against a fresh clone.

**Do not say** that Delivery Gate verifies documents, predicts outcomes, protects the seller, or connects to live PayPal. The script below stays inside what the app does.

| Time | Screen action | Narration (exact) | What the judge should understand |
|---|---|---|---|
| 0:00–0:15 | Payments list. Click the **DG-20481** row, then **View assessment**. The payment page opens; the amber **Requirements not demonstrated** banner is visible. | "A buyer says a four-hundred-eighty-dollar phone never arrived and opens a PayPal dispute. The seller has a note and a hunch. Delivery Gate shows what their evidence actually demonstrates, what's missing, and what would change it." | The problem and the value, immediately. |
| 0:15–0:35 | Slowly scroll: **Payment information** (badge "Reported by PayPal", "Fixture data") beside **Your information** ("Provided by you"). Then the **Assessment summary** on the right: six "Not demonstrated", two "Your statement only". | "PayPal's data and the merchant's own statements are kept apart. Six requirements are not demonstrated; two rest only on the seller's say-so. This demo runs on fixture data, not a live PayPal connection." | Clear separation of sources. Honest about fixtures. |
| 0:35–0:50 | Click **Review & update evidence**, then the existing note **A11**. The text is visible: "…we're protected. I'll win this dispute for sure." The panel says **Nothing to review**. | "Here's the seller's note: confident, but it contains no carrier facts, so there's nothing to review. Claims of being protected carry no weight." | Assertions are not evidence. |
| 0:50–1:15 | Back to the payment. Open the **What changes?** tab. Click **Compare** on "Carrier delivery email (sample FedEx notification)". Point at the **Hypothetical.** label, then "Current assessment" versus "With additional evidence (hypothetical)". | "What if the seller had a FedEx delivery email? This comparison is hypothetical, and it says so: nothing changes on the payment. The result would move from not demonstrated to demonstrated, and it lists exactly which requirements change." | The core idea: a safe, clearly labelled what-if. |
| 1:15–1:40 | Click **Review & update evidence**, expand **Sample evidence library**, click the FedEx email (A01). Message: "7 fact(s) found." Open A01, click **Tracking number**: the exact words highlight in the email. | "Now we add it for real. The email is read into seven facts, and each one points to the exact words it came from. In this offline demo, extraction is a recorded output; with an API key it runs live." | AI proposes facts, always tied to source text. Honest about recorded extraction. |
| 1:40–1:55 | Back to the payment page. Show the banner: **Needs human review**. | "But new evidence isn't trusted automatically. The assessment now says a person needs to review it." | Trust is earned through review. |
| 1:55–2:15 | Open A01 again. Type a reviewer name (for example "Casey Reviewer") and click **I attest this is a genuine carrier document**. The authenticity card reads **Reviewed** with the statement that it has not been independently verified. | "A reviewer attests the document is a genuine carrier email. That makes it Reviewed, never Verified, and the screen says it hasn't been independently verified." | The system is honest about what review proves. |
| 2:15–2:30 | Back to the payment page: **Requirements demonstrated**, with "PayPal makes the final decision." | "The deterministic engine now reports requirements demonstrated, the same result the what-if showed. Delivery Gate explains the evidence. PayPal makes the final decision." | The what-if was faithful; the product never decides. |
| 2:30–2:35 | Hold on the banner, or on the Overview page. | (silence, or end card) | Clean finish, under three minutes. |

## Narration only (for a voice-over read-through)

A buyer says a four-hundred-eighty-dollar phone never arrived and opens a PayPal dispute. The seller has a note and a hunch. Delivery Gate shows what their evidence actually demonstrates, what's missing, and what would change it.

PayPal's data and the merchant's own statements are kept apart. Six requirements are not demonstrated; two rest only on the seller's say-so. This demo runs on fixture data, not a live PayPal connection.

Here's the seller's note: confident, but it contains no carrier facts, so there's nothing to review. Claims of being protected carry no weight.

What if the seller had a FedEx delivery email? This comparison is hypothetical, and it says so: nothing changes on the payment. The result would move from not demonstrated to demonstrated, and it lists exactly which requirements change.

Now we add it for real. The email is read into seven facts, and each one points to the exact words it came from. In this offline demo, extraction is a recorded output; with an API key it runs live.

But new evidence isn't trusted automatically. The assessment now says a person needs to review it.

A reviewer attests the document is a genuine carrier email. That makes it Reviewed, never Verified, and the screen says it hasn't been independently verified.

The deterministic engine now reports requirements demonstrated, the same result the what-if showed. Delivery Gate explains the evidence. PayPal makes the final decision.

## Recording tips

- If a step goes wrong mid-take, click **Reset demo data** and retake from the top; the starting state is identical every time.
- Keep the mouse slow and deliberate; pause one second on each banner so viewers can read it.
- The attest step needs a typed name. Type it before the take starts if you prefer, but do not skip showing the **Reviewed** result.
- **Optional 10-second terminal segment, only if the real sandbox check has actually succeeded** (`docs/PAYPAL_SANDBOX.md` section 4 filled in): show `python3 -m paypal_adapter.sandbox_check --capture <ID>` printing `ORIGIN: LIVE_SANDBOX` and `HTTP 200`, and say: "Separately, a read-only command retrieves a real PayPal sandbox capture." If it has not succeeded, do not include or mention this segment. Never record your credentials on screen.
- Upload to YouTube as **Public** or **Unlisted** per the hackathon rules (see `SUBMISSION_CHECKLIST.md`), and confirm the displayed duration is under 3:00.
