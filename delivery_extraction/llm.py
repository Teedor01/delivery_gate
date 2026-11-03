"""Live LLM adapter (Anthropic Messages API). Isolated on purpose: this module never imports the policy engine, so the
model call path cannot see rules, passages or assessments. Not exercised against the real API in the build environment (no
network, no key); the request/response handling is tested through an injected transport."""
from __future__ import annotations

import hashlib
import json
import os
import urllib.request
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
    pass


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
