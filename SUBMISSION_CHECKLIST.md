# Delivery Gate: submission checklist

**Deadline: Nov 12, 2026, 12:00 pm PST (= 9:00 PM West Africa Time)**, per the official Devpost page, read on Nov 11, 2026. Rules are at <https://paypalaihackathon.devpost.com/rules>; I read the overview and requirements page but not the full rules text, so read the Rules page yourself before submitting.

Legend: ✅ done and verified by me · ☐ you must do this · ⚠️ risk you should decide on

---

## ⚠️ Read first: eligibility and judging risks

These are findings, not criticisms. Phase 5's scope forbade new features and live PayPal calls, so I have not changed any of this.

1. **PayPal sandbox integration: built, but NOT yet proven with a real call. This is the one thing that can still change your eligibility.** Devpost says the project should integrate the PayPal developer platform *using the free sandbox environment*, with PayPal integration *central*. A read-only sandbox client and command now exist (`python3 -m paypal_adapter.sandbox_check`, guide in `docs/PAYPAL_SANDBOX.md`), tested with 27 mocked tests. **I could not make a real request**: my environment had no sandbox credentials and no network. Until you run it with your own sandbox credentials and it returns `HTTP 200`, it is unverified code, and the README, Devpost text and video must not claim otherwise. Still true after this work: the web UI shows fixture data only, and the sandbox tool is a command-line step, not a UI feature. **Your action (about 15 minutes): follow `docs/PAYPAL_SANDBOX.md` section 3, then fill in section 4 with the real result.** If the call fails, send me the printed error (it never contains secrets) and I will fix it. If you cannot get it working in time, submit with the honest wording in the Devpost draft and accept the risk.
2. **AI use is recorded offline unless you configure Groq.** In the zero-setup demo, extraction output is *recorded*, not produced live. The live path now uses **Groq** (`docs/GROQ.md`) but has only been tested with a mocked transport, never a real model. **Your action (about 5 minutes): set `GROQ_API_KEY` and `EXTRACTION_MODEL=openai/gpt-oss-120b`, run `python3 -m delivery_extraction.groq_check --extract`, and only then describe live AI extraction as working.** Run `python3 -m delivery_extraction.groq_check` again right before recording: Groq retires models often and this catches it. The demo's built-in samples intentionally stay on recorded outputs, so the video is deterministic. Say so honestly.
3. **"Functional demo" requirement.** A judge must be able to run it from the repo instructions. This works from a fresh clone (verified), **provided the repository is published with all files** (see "Repository" below). Do not publish the *original* repository: its committed state is incomplete and broken.
4. **Third-party marks in the video.** The rules prohibit third-party trademarks or copyrighted material without permission. The demo shows the PayPal name and a *sample FedEx notification*. Naming a product to describe what it does is normal, but if you want to be conservative, consider noting "sample carrier email" in narration instead of "FedEx", and use no logos or music. This is your judgment call.
5. **Disclaimer wording.** The README says the project is not endorsed by or affiliated with PayPal. Keep that in the Devpost text too.

---

## Repository

| | Item | Status |
|---|---|---|
| ✅ | Publication-ready repo prepared at `delivery-gate-publication/` (history preserved, author emails replaced, one new Phase 5 commit on top) | done |
| ✅ | Apache-2.0 `LICENSE` (canonical text, unmodified) | done |
| ✅ | `README.md`, `DEMO_RUNBOOK.md`, `DEMO_SCRIPT.md`, `PHASE5_REPORT.md`, this checklist | done |
| ✅ | `.gitignore`, `.gitattributes` (forces LF so the hash guard is stable on Windows), `.env.example` (placeholders only) | done |
| ✅ | Secrets scan (working tree + all history): none found | done |
| ✅ | Your original personal email address removed from the publication history (0 occurrences, checked before the Phase 5 commit and after) | done |
| ☐ | **Replace the placeholder commit email** (see "Git handoff") | you |
| ☐ | Create a **new, empty** public repository on GitHub/GitLab/Bitbucket and push the publication repo to it | you |
| ☐ | Confirm the license shows in the repo's **About** section (Devpost requires it to be visible at the top) | you |
| ☐ | Optional: add a copyright line or `NOTICE` with your legal name. I did not guess it | you |
| ☐ | Delete or keep private any older repository that holds the original history with your personal email address. Rewriting history in a *new* repo does not remove it from an old one | you |

## Installation and tests (all verified on a fresh clone)

| | Item |
|---|---|
| ✅ | `python3 -m unittest discover -s tests -t .` → 467 tests (400 + 27 sandbox-client + 40 Groq tests), 0 failures, 0 errors, 0 skipped (~52 s) |
| ✅ | `python3 -m delivery_ui --port 8080` starts; main pages load |
| ✅ | 27-check browser verification in Chromium (full DG-20481 workflow, reset, console, links, overflow, key-leak, claims): all pass |
| ☐ | **Run the PayPal sandbox check once with your own sandbox credentials and record the result in `docs/PAYPAL_SANDBOX.md` section 4** | you |
| ☐ | Run `python3 -m delivery_extraction.groq_check --extract` with your Groq key (see `docs/GROQ.md`); optionally `python -m eval.evaluate --live`; record the results | you |
| ☐ | Re-run both commands once more on **your** machine after cloning from the new public URL, ideally on a second OS if you can |

## Demo video (YouTube)

| | Requirement (from Devpost) | Status |
|---|---|---|
| ✅ | Script written, matches the verified UI (`DEMO_SCRIPT.md`) | done |
| ☐ | Record the real app, following `DEMO_RUNBOOK.md` | you |
| ☐ | **Under 3 minutes** (check YouTube's displayed length) | you |
| ☐ | Shows the project functioning on the device it was built for | you |
| ☐ | Uploaded to YouTube and **publicly visible** | you |
| ☐ | No third-party trademarks, copyrighted music or material | you |
| ☐ | Video URL: `____________________` (paste into the Devpost form) | you |

## Devpost submission form

| | Item |
|---|---|
| ☐ | Project name: Delivery Gate |
| ☐ | Text description (draft below) |
| ☐ | Tools used: PayPal developer platform (documented API shapes validated on fixtures, plus a read-only sandbox client that has not yet been run live; state which is true at submission time), an LLM served by Groq (openai/gpt-oss-120b recommended) for evidence extraction; the offline demo replays recorded extractions and the live path is unevaluated. Explain how each is used, honestly |
| ☐ | Repository URL: `____________________` |
| ☐ | Screenshots: use files in `docs/screens/` or capture fresh ones |
| ☐ | Final review of every field, then **Submit** before the deadline. Submit early; do not leave it to the last hour |

### Draft Devpost description (edit freely; keep the caveats)

> **Delivery Gate** helps online sellers understand their evidence position when a PayPal payment is disputed. A seller with a $480 "item not received" dispute sees what PayPal reports, what evidence they actually have, which documented Seller Protection requirements are not yet demonstrated, and what would change if they added more, such as a reviewed carrier delivery confirmation.
>
> **How it works.** AI extracts evidence from documents into a small closed set of facts, each tied to the exact source text. Validation checks the output. A deterministic engine, not the AI, evaluates the facts against the requirements currently modeled. A human reviewer must attest to new evidence before it counts, and an attestation produces "Reviewed", never "Verified". A "what changes?" view re-runs the same engine on hypothetical evidence, clearly labelled hypothetical. Delivery Gate never says a seller is protected and never predicts a win: PayPal makes the final decision.
>
> **Honest status.** This is a prototype. The web app runs on fixture data. The PayPal adapter is built against PayPal's documented API response shapes and tested on fixtures. [CHOOSE ONE AND DELETE THIS BRACKET. IF you have run the sandbox check successfully: "A read-only sandbox client retrieved a real PayPal sandbox capture on <date>." OTHERWISE: "A read-only sandbox client exists and is tested with mocked HTTP; it has not yet been run against the live sandbox."] The offline demo reads recorded AI extractions; the live extraction path has not been evaluated for accuracy. Built with Python's standard library, 467 automated tests, Apache-2.0.
>
> Not affiliated with or endorsed by PayPal.

## Git handoff (exact commands)

The publication repo is at `delivery-gate-publication/`. Its history is the original 16 commits with author and committer email replaced by `REPLACE_WITH_GITHUB_NOREPLY@users.noreply.github.com`, plus one Phase 5 commit.

**The one value you must replace:** your GitHub no-reply address, found at GitHub → Settings → Emails → "Keep my email addresses private" (format `ID+username@users.noreply.github.com`). I did not guess it.

```bash
cd delivery-gate-publication
# Review what you are about to publish
git log --oneline
git show --stat HEAD

# Replace the placeholder email in ALL commits (history is not published yet, so this is safe)
export NEW_EMAIL="ID+username@users.noreply.github.com"
FILTER_BRANCH_SQUELCH_WARNING=1 git filter-branch -f --env-filter \
  'export GIT_AUTHOR_EMAIL="$NEW_EMAIL"; export GIT_COMMITTER_EMAIL="$NEW_EMAIL"' -- --all
rm -rf .git/refs/original && git reflog expire --expire=now --all && git gc -q --prune=now
git config user.email "$NEW_EMAIL"

# Final check: your OLD personal address appears nowhere, tests pass
OLD_EMAIL="your-old-personal-address"   # type your real old address here (not stored in this repo)
git log --all -p | grep -ci -F "$OLD_EMAIL"   # expect 0
python3 -m unittest discover -s tests -t .

# Publish to a NEW empty repository (this is the step I did not do)
git remote add origin https://github.com/<you>/<new-repo>.git
git push -u origin main
```

If you would rather skip the email replacement, you can run only the `git config` line and leave the placeholder; it is harmless but looks unfinished.
