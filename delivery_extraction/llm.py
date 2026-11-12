from __future__ import annotations

import hashlib
import json
import os
import random
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable, Optional, Tuple

from delivery_extraction.extractor import RawExtraction
from delivery_extraction.prompt import PROMPT_SHA256, SYSTEM_PROMPT, build_user_message
from delivery_extraction.schema import Artifact

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
Transport = Callable[[str, dict, bytes], Tuple[int, bytes]]


def _urllib_transport(url: str, headers: dict, body: bytes) -> Tuple[int, bytes]:   
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


class LLMError(RuntimeError):
    """A failed model request. `status` is the HTTP status when there was one, `attempts` how many requests were made."""
    status: Optional[int] = None
    attempts: int = 1
    retryable: bool = False

    def __init__(self, message: str = "", status: Optional[int] = None, attempts: int = 1, retryable: bool = False):
        super().__init__(message)
        self.status, self.attempts, self.retryable = status, attempts, retryable


class LLMRetryExhausted(LLMError):
    """Retries ran out (HTTP 429 or a transient 5xx/network failure). Nothing was extracted for the artifact."""


@dataclass(frozen=True)
class RetryPolicy:
    """429 (rate limit) and transient failures (HTTP 5xx, network errors) are retried separately and boundedly.
    Everything else (401, 403, 400, 404, malformed or truncated output) is never retried."""
    max_attempts_429: int = 6              # total requests allowed when rate limited
    max_attempts_transient: int = 3        # total requests allowed for 5xx / network errors
    base_delay: float = 2.0                # seconds; doubles per failed attempt when the server gave no wait time
    max_delay: float = 60.0
    max_retry_after: float = 120.0         # a server-requested wait longer than this is not slept through; the failure is reported
    jitter: float = 0.25                   # up to +25% added to computed backoff

    def backoff(self, failed_attempts: int, rng: random.Random) -> float:
        return min(self.max_delay, self.base_delay * (2 ** (failed_attempts - 1))) * (1 + rng.uniform(0, self.jitter))



def parse_retry_after(headers: Optional[dict], payload: bytes = b"") -> Optional[float]:
    """Seconds to wait, from the Retry-After header (delta-seconds). Falls back to Groq's 'try again in 1m2.5s' hint in the error
    message. HTTP-date values are not interpreted (None). Never negative."""
    h = {str(k).lower(): v for k, v in (headers or {}).items()}
    v = h.get("retry-after")
    if v is not None:
        try:
            x = float(str(v).strip())
            return max(0.0, x) if x == x and x != float("inf") else None
        except ValueError:
            return None
    try:
        msg = str(json.loads(payload).get("error", {}).get("message", ""))
    except (ValueError, AttributeError, TypeError):
        return None
    m = re.search(r"try again in (\d+(?:\.\d+)?ms|(?:\d+(?:\.\d+)?m)?\s*(?:\d+(?:\.\d+)?s)?)", msg)
    if not m or not m.group(1).strip():
        return None
    t = m.group(1)
    if t.endswith("ms"):
        return float(t[:-2]) / 1000
    mm, ss = re.fullmatch(r"(?:(\d+(?:\.\d+)?)m)?\s*(?:(\d+(?:\.\d+)?)s)?", t.strip()).groups()
    return float(mm or 0) * 60 + float(ss or 0)


def _urllib_transport_h(url: str, headers: dict, body: bytes):
    """Like _urllib_transport but also returns the (lower-cased) response headers, so Retry-After can be honoured."""
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, r.read(), {k.lower(): v for k, v in r.headers.items()}
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read(), {k.lower(): v for k, v in e.headers.items()}
        finally:
            e.close()


class AnthropicExtractor:
    KIND = "ANTHROPIC_API"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None, transport: Optional[Transport] = None,
                 max_tokens: int = 2000):
        self.model = model or os.environ.get("EXTRACTION_MODEL")
        if not self.model:
            raise LLMError("no model configured: pass model= or set EXTRACTION_MODEL (no default is guessed)")
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        self.transport, self.max_tokens = transport or _urllib_transport, max_tokens

    def build_request(self, artifact: Artifact) -> dict:
        return {"model": self.model, "max_tokens": self.max_tokens, "temperature": 0,
                "system": SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": build_user_message(artifact)}]}

    def extract(self, artifact: Artifact) -> RawExtraction:
        if not self.api_key:
            raise LLMError("no API key: set ANTHROPIC_API_KEY")
        body = json.dumps(self.build_request(artifact)).encode("utf-8")
        headers = {"x-api-key": self.api_key, "anthropic-version": API_VERSION, "content-type": "application/json"}
        status, payload = self.transport(API_URL, headers, body)
        if status != 200:
            raise LLMError(f"API returned HTTP {status}")
        doc = json.loads(payload)
        text = "".join(b.get("text", "") for b in doc.get("content", []) if b.get("type") == "text")
        return RawExtraction(text, self.KIND, self.model, PROMPT_SHA256, hashlib.sha256(body).hexdigest())


# =====================================================================================================================
# Groq (OpenAI-compatible Chat Completions). Added Nov 12, 2026; request format checked against Groq's API reference
# (https://console.groq.com/docs/api-reference) on that date. NOT yet run against the live service: see docs/GROQ.md.
# =====================================================================================================================
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_USER_AGENT = "delivery-gate/1.0 (evidence-extraction)"     # explicit UA: some CDNs reject the default Python-urllib one
# Models that accept reasoning_effort ('low'|'medium'|'high') and include_reasoning. Other Groq models take different values,
# so these parameters are sent ONLY for these two ids.
GROQ_GPT_OSS_MODELS = frozenset({"openai/gpt-oss-120b", "openai/gpt-oss-20b"})
# Retired per https://console.groq.com/docs/deprecations (read 2026-11-12) with Groq's recommended replacement. Used ONLY to make an
# error message more helpful; never to block a request (enterprise contracts can keep some of these).
GROQ_RETIRED_MODELS = {
    "llama-3.1-8b-instant": "openai/gpt-oss-20b",
    "llama-3.3-70b-versatile": "openai/gpt-oss-120b",
    "meta-llama/llama-4-scout-17b-16e-instruct": "openai/gpt-oss-120b",
    "meta-llama/llama-4-maverick-17b-128e-instruct": "openai/gpt-oss-120b",
    "qwen/qwen3-32b": "openai/gpt-oss-120b",
    "qwen/qwen3.6-27b": "qwen/qwen3.8-27b",
    "moonshotai/kimi-k2-instruct": "openai/gpt-oss-120b",
    "moonshotai/kimi-k2-instruct-0905": "openai/gpt-oss-120b",
    "groq/compound": "openai/gpt-oss-120b",
    "groq/compound-mini": "openai/gpt-oss-20b",
}


class GroqExtractor:
    """Same contract as AnthropicExtractor: returns the model's raw text; the strict validator downstream is the authority.
    JSON Object mode is requested, but nothing here trusts it: malformed, truncated or schema-violating output is rejected later."""
    KIND = "GROQ_API"

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None, transport: Optional[Transport] = None,
                 max_tokens: int = 8000, reasoning_effort: str = "low", retry: Optional[RetryPolicy] = None,
                 sleep: Optional[Callable[[float], None]] = None, rng: Optional[random.Random] = None,
                 on_retry: Optional[Callable[[str], None]] = None):
        self.model = model or os.environ.get("EXTRACTION_MODEL")
        if not self.model:
            raise LLMError("no model configured: pass model= or set EXTRACTION_MODEL (no default is guessed; see docs/GROQ.md)")
        self.api_key = api_key or os.environ.get("GROQ_API_KEY")
        if reasoning_effort not in ("low", "medium", "high"):
            raise LLMError("reasoning effort must be low, medium or high")
        self.transport, self.max_tokens, self.reasoning_effort = transport or _urllib_transport_h, max_tokens, reasoning_effort
        self.retry, self._sleep, self._rng, self.on_retry = retry or RetryPolicy(), sleep or time.sleep, rng or random.Random(), on_retry
        self.last_usage_tokens: Optional[int] = None     # total_tokens reported by the last successful response
        self.last_attempts = 0

    def __repr__(self) -> str:
        return f"GroqExtractor(model={self.model!r}, api_key=<redacted>)"

    def build_request(self, artifact: Artifact) -> dict:
        req = {"model": self.model, "temperature": 0, "max_completion_tokens": self.max_tokens,
               "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": build_user_message(artifact)}],
               "response_format": {"type": "json_object"}}
        if self.model in GROQ_GPT_OSS_MODELS:
            req["reasoning_effort"] = self.reasoning_effort      # reasoning tokens count against max_completion_tokens, so keep it low
            req["include_reasoning"] = False                      # the answer is in message.content; reasoning is neither needed nor stored
        return req

    def _hint(self) -> str:
        repl = GROQ_RETIRED_MODELS.get(self.model)
        return (f" Model '{self.model}' is listed as retired for standard accounts; Groq recommends '{repl}'. Set EXTRACTION_MODEL accordingly." if repl else "")

    def _once(self, headers: dict, body: bytes):
        """One request -> (status, payload, response_headers). A network failure is reported as status 0. Transports may return
        (status, payload) or (status, payload, headers)."""
        try:
            r = self.transport(GROQ_API_URL, headers, body)
        except LLMError:
            raise
        except (OSError, TimeoutError) as e:
            return 0, json.dumps({"error": {"message": f"network error contacting Groq ({type(e).__name__})"}}).encode(), {}
        return (r[0], r[1], r[2] if len(r) > 2 else {})

    def _post_with_retries(self, headers: dict, body: bytes):
        """Retries 429 and transient failures only, within RetryPolicy. Returns the final (status, payload, attempts)."""
        n429 = ntrans = attempts = 0
        while True:
            attempts += 1
            self.last_attempts = attempts
            status, payload, rh = self._once(headers, body)
            if status == 200:
                return status, payload, attempts
            if status == 429:
                n429 += 1
                if n429 >= self.retry.max_attempts_429:
                    return status, payload, attempts
                ra = parse_retry_after(rh, payload)
                if ra is not None and ra > self.retry.max_retry_after:
                    return status, payload, attempts                      # told to wait too long; report it, do not sleep through it
                wait = (ra + self._rng.uniform(0, 1.0)) if ra is not None else self.retry.backoff(n429, self._rng)
                why = f"HTTP 429, server asked for {ra:g}s" if ra is not None else "HTTP 429, no Retry-After"
            elif status == 0 or status >= 500:
                ntrans += 1
                if ntrans >= self.retry.max_attempts_transient:
                    if status == 0:
                        raise LLMRetryExhausted(f"network error contacting Groq. Gave up after {attempts} attempt(s).", None, attempts, True) from None
                    return status, payload, attempts
                wait, why = self.retry.backoff(ntrans, self._rng), ("network error" if status == 0 else f"HTTP {status}")
            else:
                return status, payload, attempts                          # 400/401/403/404/...: never retried
            if self.on_retry:
                self.on_retry(f"{why}; retrying in {wait:.1f}s (attempt {attempts + 1})")
            self._sleep(wait)

    def extract(self, artifact: Artifact) -> RawExtraction:
        if not self.api_key:
            raise LLMError("no API key: set GROQ_API_KEY")
        body = json.dumps(self.build_request(artifact)).encode("utf-8")
        headers = {"Authorization": "Bearer " + self.api_key, "Content-Type": "application/json", "Accept": "application/json",
                   "User-Agent": GROQ_USER_AGENT}
        status, payload, attempts = self._post_with_retries(headers, body)
        if status != 200:
            detail = ""
            try:
                err = json.loads(payload).get("error", {})
                detail = " [" + ", ".join(str(err[k])[:200] for k in ("code", "type", "message") if err.get(k)) + "]"
            except (ValueError, AttributeError, TypeError):
                pass
            what = {401: " (check GROQ_API_KEY)", 403: " (access denied)", 404: " (model or endpoint not found)",
                    429: " (rate limited: wait and retry)"}.get(status, "")
            msg = f"Groq API returned HTTP {status}{what}{detail}." + (self._hint() if status in (400, 404) else "")
            if status == 429 or status >= 500:
                raise LLMRetryExhausted(msg + f" Gave up after {attempts} attempt(s).", status, attempts, True)
            raise LLMError(msg, status, attempts)
        try:
            doc = json.loads(payload)
            choice = doc["choices"][0]
            text, finish = choice["message"].get("content"), choice.get("finish_reason")
            u = doc.get("usage", {}).get("total_tokens") if isinstance(doc.get("usage"), dict) else None
            self.last_usage_tokens = u if isinstance(u, int) else None
        except (ValueError, KeyError, IndexError, AttributeError, TypeError):
            raise LLMError("Groq response was not in the expected chat-completions format") from None
        if finish == "length":
            raise LLMError("Groq output was cut off at max_completion_tokens (reasoning models spend tokens thinking); raise max_tokens")
        if not isinstance(text, str) or not text.strip():
            raise LLMError(f"Groq returned no answer text (finish_reason={finish})")
        return RawExtraction(text, self.KIND, self.model, PROMPT_SHA256, hashlib.sha256(body).hexdigest())


def make_extractor(env=None):
    """Choose the live extractor from the environment. Returns None when nothing is configured.
    EXTRACTION_PROVIDER=groq|anthropic is honoured exactly; if unset, Groq is used when GROQ_API_KEY is present, otherwise Anthropic
    when ANTHROPIC_API_KEY is present. EXTRACTION_MODEL is always required (never guessed). Keys are read here, server-side only."""
    env = os.environ if env is None else env
    provider = (env.get("EXTRACTION_PROVIDER") or "").strip().lower()
    if provider not in ("", "groq", "anthropic"):
        raise LLMError("EXTRACTION_PROVIDER must be 'groq' or 'anthropic'")
    if not provider:
        provider = "groq" if env.get("GROQ_API_KEY") else ("anthropic" if env.get("ANTHROPIC_API_KEY") else "")
        if not provider:
            return None
    elif not env.get({"groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}[provider]):
        raise LLMError(f"EXTRACTION_PROVIDER={provider} but its API key variable is not set")
    model = (env.get("EXTRACTION_MODEL") or "").strip()
    if not model:
        return None
    if provider == "groq":
        effort = (env.get("EXTRACTION_REASONING_EFFORT") or "low").strip().lower()
        return GroqExtractor(model=model, api_key=env["GROQ_API_KEY"], reasoning_effort=effort)
    return AnthropicExtractor(model=model, api_key=env["ANTHROPIC_API_KEY"])
