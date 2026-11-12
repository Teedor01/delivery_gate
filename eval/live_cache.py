"""Local checkpoint cache for LIVE extraction results (raw model text only; the validator always re-runs on load).

Key = sha256 of artifact content hash + extractor kind + model + reasoning effort + prompt hash + prompt version + schema fingerprint.
Change any of those and the old entry is simply not found, so results from a different model or prompt/schema are never reused.
Files are written atomically. A corrupt or mismatching entry is ignored (treated as a miss), never trusted.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, Optional

from delivery_extraction import schema as S
from delivery_extraction.extractor import RawExtraction
from delivery_extraction.prompt import PROMPT_SHA256, PROMPT_VERSION


def schema_fingerprint() -> str:
    parts = {n: getattr(S, n) for n in ("FACT_VOCAB", "FACT_KEYS", "ADDRESS_FIELDS", "ATTRIBUTIONS", "CONFIDENCES", "MODALITIES")}
    return hashlib.sha256(json.dumps(parts, sort_keys=True, default=str).encode("utf-8")).hexdigest()


def cache_meta(artifact_sha: str, kind: str, model: str, effort: str, prompt_sha: str = PROMPT_SHA256, prompt_version: str = PROMPT_VERSION,
               schema_fp: Optional[str] = None) -> Dict[str, str]:
    return {"artifact_sha256": artifact_sha, "extractor_kind": kind, "model": model, "reasoning_effort": effort, "prompt_sha256": prompt_sha,
            "prompt_version": prompt_version, "schema_fingerprint": schema_fp or schema_fingerprint()}


def cache_key(meta: Dict[str, str]) -> str:
    return hashlib.sha256(json.dumps(meta, sort_keys=True).encode("utf-8")).hexdigest()


class LiveCache:
    def __init__(self, directory: Path):
        self.dir = Path(directory)

    def get(self, meta: Dict[str, str]) -> Optional[RawExtraction]:
        key = cache_key(meta)
        try:
            d = json.loads((self.dir / f"{key}.json").read_text(encoding="utf-8"))
            if d.get("key") != key or d.get("meta") != meta:
                return None
            r = d["raw"]
            if not isinstance(r.get("text"), str) or not r["text"].strip():
                return None
            return RawExtraction(r["text"], r["extractor_kind"], r.get("model"), r.get("prompt_sha256"), r.get("request_sha256"))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            return None

    def put(self, meta: Dict[str, str], raw: RawExtraction) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        key = cache_key(meta)
        fd, tmp = tempfile.mkstemp(dir=self.dir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"key": key, "meta": meta, "raw": asdict(raw)}, f, ensure_ascii=False)
            os.replace(tmp, self.dir / f"{key}.json")
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
