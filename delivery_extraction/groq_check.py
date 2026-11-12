"""Pre-flight check for the Groq extractor. Run this BEFORE a demo or a recording.

    export GROQ_API_KEY=...            # your Groq key
    export EXTRACTION_MODEL=openai/gpt-oss-120b
    python3 -m delivery_extraction.groq_check              # asks Groq which models your account can use; checks yours is one of them
    python3 -m delivery_extraction.groq_check --extract    # also runs ONE real extraction on built-in sample A01 through the strict validator

Exit codes: 0 ok, 2 configuration problem (no request made), 3 Groq request failed, 4 model not available to this account,
5 extraction ran but the validator accepted no facts. Keys are never printed. This makes real network calls only when you run it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import IO, Mapping, Optional, Sequence

from .llm import GROQ_GPT_OSS_MODELS, GROQ_RETIRED_MODELS, GROQ_USER_AGENT, GroqExtractor, LLMError

MODELS_URL = "https://api.groq.com/openai/v1/models"


def _get(key: str):
    """The only GET in this module; injectable for tests. Returns (status, body)."""
    import urllib.error
    import urllib.request
    req = urllib.request.Request(MODELS_URL, method="GET", headers={"Authorization": "Bearer " + key, "Accept": "application/json", "User-Agent": GROQ_USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise LLMError(f"network error contacting Groq ({type(e).__name__})") from None


def _list_models(key: str, get=None) -> list:
    status, body = (get or _get)(key)
    if status != 200:
        raise LLMError(f"model list request failed (HTTP {status})" + (" (check GROQ_API_KEY)" if status == 401 else ""))
    try:
        return sorted(m["id"] for m in json.loads(body)["data"])
    except (ValueError, KeyError, TypeError):
        raise LLMError("model list was not in the expected format") from None


def main(argv: Optional[Sequence[str]] = None, env: Optional[Mapping[str, str]] = None, list_transport=None, extract_transport=None,
         out: Optional[IO[str]] = None, sleep=None) -> int:
    out = out or sys.stdout
    env = os.environ if env is None else env
    ap = argparse.ArgumentParser(prog="python3 -m delivery_extraction.groq_check")
    ap.add_argument("--extract", action="store_true", help="also run one real extraction on sample A01 and validate it")
    a = ap.parse_args(argv)
    p = lambda s="": print(s, file=out)

    key, model = (env.get("GROQ_API_KEY") or "").strip(), (env.get("EXTRACTION_MODEL") or "").strip()
    if not key or not model:
        miss = [n for n, v in (("GROQ_API_KEY", key), ("EXTRACTION_MODEL", model)) if not v]
        p("CONFIGURATION ERROR (no request was made): missing " + ", ".join(miss) + ". See docs/GROQ.md.")
        return 2
    try:
        ids = _list_models(key, list_transport)
    except LLMError as e:
        p(f"REQUEST FAILED: {e}")
        return 3
    p(f"Groq reports {len(ids)} models available to this account.")
    gpt_oss = [i for i in ids if i in GROQ_GPT_OSS_MODELS]
    p("Recommended for extraction (Production, supports reasoning_effort): " + (", ".join(gpt_oss) or "none visible to this account"))
    if model not in ids:
        repl = GROQ_RETIRED_MODELS.get(model)
        p(f"MODEL NOT AVAILABLE: '{model}' is not in this account's model list." + (f" Groq lists it as retired; recommended replacement: {repl}." if repl else ""))
        if gpt_oss:
            p("Set EXTRACTION_MODEL to one of the recommended models above, then run this check again.")
        return 4
    p(f"OK: EXTRACTION_MODEL '{model}' is available to this account.")
    if model not in GROQ_GPT_OSS_MODELS:
        p("note: this is not one of the two models the extractor was written and mock-tested for (openai/gpt-oss-120b, openai/gpt-oss-20b).")

    if a.extract:
        from delivery_extraction.schema import Artifact
        from delivery_extraction.validate import validate_output
        from eval.corpus import ARTIFACTS
        spec = next(x for x in ARTIFACTS if x["id"] == "A01")
        art = Artifact(spec["id"], spec["text"], spec["kind"])
        try:
            ex = GroqExtractor(model=model, api_key=key, transport=extract_transport, sleep=sleep, on_retry=lambda m: p('  ' + m), reasoning_effort=(env.get("EXTRACTION_REASONING_EFFORT") or "low").strip().lower())
            raw = ex.extract(art)
        except LLMError as e:
            p(f"EXTRACTION REQUEST FAILED: {e}")
            return 3
        rep = validate_output(art, raw.text)
        p(f"\nREAL EXTRACTION via {raw.extractor_kind}, model {raw.model}")
        p(f"  validator accepted {len(rep.accepted)} fact(s); rejected {len(rep.rejected)}")
        if not rep.output_ok:
            p("  output problems: " + "; ".join(rep.output_errors[:3]))
        for f in rep.accepted[:12]:
            p(f"  - {f.fact}: {str(f.normalized_value)[:60]}")
        p("  (the recorded reference output for A01 has 7 accepted facts; a different count is not an error, it is a real model's result)")
        if not rep.accepted:
            p("  NO FACTS ACCEPTED: the model's output did not pass the strict validator. Try EXTRACTION_REASONING_EFFORT=medium or the other gpt-oss model.")
            return 5
    return 0


if __name__ == "__main__":
    sys.exit(main())
