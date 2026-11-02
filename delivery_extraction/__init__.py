"""Delivery Gate Phase 2: AI evidence EXTRACTION layer only.

    artifact -> extraction (LLM) -> validation -> normalized candidate facts -> [human review] -> deterministic engine

The LLM is an interpreter, never a policy engine. It can only emit candidate facts from a closed vocabulary; every fact must
carry an exact source span; policy conclusions are structurally impossible to emit. `delivery_gate` (the engine) does not
import this package, and this package's LLM client does not import the engine.
"""
EXTRACTION_VERSION = "0.1.0-phase2"
