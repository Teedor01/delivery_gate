# Delivery Gate: submission checklist

**Deadline: Nov 12, 2026, 12:00 pm PST (= 9:00 PM West Africa Time)**, per the official Devpost page, read on Nov 11, 2026. Rules are at <https://paypalaihackathon.devpost.com/rules>; I read the overview and requirements page but not the full rules text, so read the Rules page yourself before submitting.

Legend: ✅ done and verified by me · ☐ you must do this · ⚠️ risk you should decide on

---

## ⚠️ Read first: eligibility and judging risks

These are findings, not criticisms. Phase 5's scope forbade new features and live PayPal calls, so I have not changed any of this.

1. **PayPal sandbox integration.** Devpost's "What to Build" says the project should integrate the PayPal developer platform *using the free sandbox environment*, and that PayPal integration should be *central* to the project. **Delivery Gate makes no live or sandbox PayPal call**: the PayPal adapter is implemented and tested against fixtures only, and `PayPalSandboxSource` deliberately refuses to run. A judge could reasonably conclude the "meaningfully integrate PayPal" requirement is not met. Everything in this repo says this honestly; I have not softened it, and you should not either. **Decide before submitting** whether to (a) submit as is and describe the integration accurately (adapter built against PayPal's documented Orders v2 / Disputes API shapes, validated on fixtures), or (b) spend the remaining time on a minimal real sandbox read. Option (b) is a new feature and an architecture-boundary change, so it needs your explicit go-ahead; I did not attempt it.
2. **AI use is recorded offline.** In the zero-setup demo, extraction output is *recorded*, not produced live. The live path (`ANTHROPIC_API_KEY` + `EXTRACTION_MODEL`) exists but has only been tested with an injected stand-in, never against a real model. Say so in the Devpost text. If you can, run one live extraction yourself before the video and only then describe it as working.
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
| ✅ | `python3 -m unittest discover -s tests -t .` → 400 tests, 0 failures, 0 errors, 0 skipped (~51 s) |
| ✅ | `python3 -m delivery_ui --port 8080` starts; main pages load |
| ✅ | 27-check browser verification in Chromium (full DG-20481 workflow, reset, console, links, overflow, key-leak, claims): all pass |
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
| ☐ | Tools used: PayPal developer platform (documented API shapes; fixtures only), an AI model via the Anthropic Messages API for evidence extraction (live path unevaluated). Explain how each is used, honestly |
| ☐ | Repository URL: `____________________` |
| ☐ | Screenshots: use files in `docs/screens/` or capture fresh ones |
| ☐ | Final review of every field, then **Submit** before the deadline. Submit early; do not leave it to the last hour |

### Draft Devpost description (edit freely; keep the caveats)

> **Delivery Gate** helps online sellers understand their evidence position when a PayPal payment is disputed. A seller with a $480 "item not received" dispute sees what PayPal reports, what evidence they actually have, which documented Seller Protection requirements are not yet demonstrated, and what would change if they added more, such as a reviewed carrier delivery confirmation.
>
> **How it works.** AI extracts evidence from documents into a small closed set of facts, each tied to the exact source text. Validation checks the output. A deterministic engine, not the AI, evaluates the facts against the requirements currently modeled. A human reviewer must attest to new evidence before it counts, and an attestation produces "Reviewed", never "Verified". A "what changes?" view re-runs the same engine on hypothetical evidence, clearly labelled hypothetical. Delivery Gate never says a seller is protected and never predicts a win: PayPal makes the final decision.
>
> **Honest status.** This is a prototype running on fixture data. The PayPal adapter is built against PayPal's documented API response shapes and tested on fixtures; it has not made a live or sandbox call. The offline demo reads recorded AI extractions; the live extraction path has not been evaluated for accuracy. Built with Python's standard library, 400 automated tests, Apache-2.0.
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
