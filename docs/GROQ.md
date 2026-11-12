# Groq as the live extraction provider

## Status (read this first)

| Item | Status |
|---|---|
| `GroqExtractor` (`delivery_extraction/llm.py`) and provider selection (`make_extractor`) | **Implemented** |
| Pre-flight command `python3 -m delivery_extraction.groq_check` | **Implemented** |
| 40 automated tests with a mocked transport (`tests/test_llm_groq.py`); 9 deliberate sabotage checks (parameters, truncation handling, key leakage, retired-model hint, provider precedence, no guessed default model) were each caught | **Pass** |
| A **real request to Groq** | **NOT YET PERFORMED.** The environment where this was written had no Groq key and no network access |
| Live extraction accuracy | **Never evaluated.** The recorded-output evaluation measures the validation pipeline, not a live model |

Everything below about Groq was checked against Groq's own documentation on **Nov 12, 2026** (links at the end). Model availability changes quickly, which is exactly why the pre-flight command exists. Run it before every demo or recording.

## 1. Quick start (5 minutes)

1. Create a key at <https://console.groq.com> (API Keys).
2. Set the environment (never commit a key; see `.env.example`):

```bash
export GROQ_API_KEY="gsk_..."
export EXTRACTION_MODEL="openai/gpt-oss-120b"
```

3. **Pre-flight check.** This asks Groq which models *your account* can use and confirms yours is one of them:

```bash
python3 -m delivery_extraction.groq_check
```

4. **One real extraction**, run through the same strict validator as everything else:

```bash
python3 -m delivery_extraction.groq_check --extract
```

5. Optional, the full 15-artifact evaluation against the live model (15 requests; writes `eval/results_live.json`):

```bash
python3 -m eval.evaluate --live
```

6. Start the app as usual (`python3 -m delivery_ui --port 8080`). Built-in samples are still read from recorded outputs, by design, so the demo stays deterministic. Text you paste or upload that is *not* a built-in sample is now read by Groq.

Exit codes of `groq_check`: `0` ok, `2` configuration problem (no request made), `3` request failed, `4` model not available to this account, `5` extraction ran but the validator accepted no facts.

## 2. Which model to use (as of Nov 12, 2026)

| Model ID | Tier | Price per 1M tokens (in / out) | Notes |
|---|---|---|---|
| **`openai/gpt-oss-120b`** | Production | $0.15 / $0.60 | **Recommended.** 131K context, 65K max output, ~500 tokens/s |
| `openai/gpt-oss-20b` | Production | $0.075 / $0.30 | Cheaper and faster (~1000 tokens/s); try it if 120B is rate limited |
| `qwen/qwen3.8-27b` | **Preview** | $0.80 / $4.00 | Preview models can be withdrawn at short notice; 16K max output. Not recommended, **not tested** here |

**Do not use these; Groq retired them for standard accounts** (the `groq_check` command and the extractor's error messages name the replacement automatically):

| Retired model | Shutdown | Groq's recommended replacement |
|---|---|---|
| `llama-3.3-70b-versatile` | 2026-08-16 | `openai/gpt-oss-120b` |
| `llama-3.1-8b-instant` | 2026-08-16 | `openai/gpt-oss-20b` |
| `meta-llama/llama-4-scout-17b-16e-instruct`, `qwen/qwen3-32b` | 2026-07-17 | `openai/gpt-oss-120b` |
| `qwen/qwen3.6-27b` | 2026-09-14 | `qwen/qwen3.8-27b` |
| `groq/compound`, `groq/compound-mini` | 2026-09-21 | none named |

Many tutorials still use the Llama IDs. Groq's models page still lists the two Llama 3.x models as *Enterprise / contact sales*, and Groq says the retirement applies to free and developer-tier usage, so an enterprise contract may keep them. The extractor never blocks a model ID; it only adds the hint to an error.

**No default model is built in, deliberately.** Groq retires models every few months (its deprecation page lists seven retirement dates in 2026 alone), so a hard-coded default would eventually break the app. `EXTRACTION_MODEL` is always required.

## 3. How the request is built

Verified against Groq's API reference on 2026-11-12:

- `POST https://api.groq.com/openai/v1/chat/completions`, `Authorization: Bearer <key>`, an explicit `User-Agent`.
- `temperature: 0`, `max_completion_tokens: 8000` (`max_tokens` is deprecated and is not sent), `response_format: {"type": "json_object"}`. The prompt already requires "a single JSON object", which JSON mode needs.
- For the two `gpt-oss` models only: `reasoning_effort: "low"` (override with `EXTRACTION_REASONING_EFFORT=low|medium|high`) and `include_reasoning: false`. Reasoning tokens count against the output limit, so truncation is detected and reported as a clear error instead of passing a cut-off answer along.
- Groq supports `n=1` only; nothing else is sent.

**Why JSON mode and not Groq's schema-enforced "structured outputs"?** Groq documents strict schema enforcement for the two gpt-oss models only, and a Groq community report describes it being silently ignored on `gpt-oss-120b`. The authority here is our own strict validator (exact source spans, closed vocabulary, injection and malformed-output checks), so nothing depends on the server honouring a schema. Model output is never trusted; a bad answer is rejected, not repaired.

## 4. Provider selection

| Environment | Provider used |
|---|---|
| `EXTRACTION_PROVIDER` unset, `GROQ_API_KEY` set | Groq |
| `EXTRACTION_PROVIDER` unset, only `ANTHROPIC_API_KEY` set | Anthropic (the original path still works) |
| `EXTRACTION_PROVIDER=groq` or `anthropic` | exactly that one; an error if its key is missing (no silent fallback) |
| no key, or no `EXTRACTION_MODEL` | none: offline, recorded samples only |

## 5. What could still go wrong (honest list)

- **Not run live yet.** Request and response handling follow the documentation and pass mocked tests. A first real run may reveal a difference; `groq_check --extract` is how you find out, and any printed error is safe to share (it never contains the key).
- **Free-tier rate limits** are lower than the developer-plan limits shown in the docs (250K tokens/min, 1K requests/min). I did not verify free-tier numbers. A 429 is reported as "rate limited: wait and retry"; the app records that evidence item as "analysis failed" with the reason shown, and keeps running.
- **Extraction quality is unknown.** `reasoning_effort` defaults to `low` for speed. If the validator accepts too few facts, try `EXTRACTION_REASONING_EFFORT=medium` or the other gpt-oss model, and measure with `python3 -m eval.evaluate --live`.
- **Explicit `User-Agent`.** Added as a precaution because some CDNs reject Python's default one. I have not confirmed Groq does.
- Data sent to Groq is the artifact text plus the fixed extraction prompt, nothing else. Do not paste real customer data into a hackathon demo.

## 6. Sources (all read on 2026-11-12)

- Supported models: <https://console.groq.com/docs/models>
- Deprecations and replacements: <https://console.groq.com/docs/deprecations>
- API reference (parameters): <https://console.groq.com/docs/api-reference>
- Structured outputs and JSON mode: <https://console.groq.com/docs/structured-outputs>
- Reasoning options (gpt-oss): <https://console.groq.com/docs/reasoning>
- Live model list for your account: `GET https://api.groq.com/openai/v1/models`
