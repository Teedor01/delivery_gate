# Delivery Gate, Phase 2: AI evidence EXTRACTION layer (only)

    artifact -> extraction (LLM) -> validation -> normalized candidate facts -> [human review] -> deterministic engine (Phase 1)

Not built (by instruction): UI, PayPal API integration, authentication, database. Output artifacts are JSON audit files.

## The boundary
* The LLM is an interpreter. It emits candidate facts from a CLOSED vocabulary (schemas/extraction.schema.json). It can never emit
  a policy conclusion: a fact named PROTECTED is rejected (not in vocabulary), any extra key such as `decision` rejects the whole
  output, and policy-conclusion language in any model-authored field rejects the fact. The source_span quotes the artifact and is exempt.
* `delivery_extraction/llm.py` and `prompt.py` never import `delivery_gate`; `delivery_gate` never imports `delivery_extraction`.
  The prompt contains no policy text, rule descriptions or passage ids.
* Every fact needs an exact source span (verified as a substring), and its normalised value is grounded in that span by deterministic
  checks. Hedged language stays hedged (UNKNOWN + ambiguity). Absence of mention is never evidence of absence.
* Confidence is stored but never consumed: the bridge drops it and tests prove the assessment digest is unchanged by it.
* Extracted facts enter the engine as EXTRACTED_UNREVIEWED, which Phase 1 treats as NEEDS_HUMAN_REVIEW. Only a reviewer decision can change
  that, and it cannot promote a merchant/customer/relayed statement to a carrier document. The model can never attest an artifact.
* UNKNOWN-normalised facts are never bridged: missing stays missing. Non-policy observations (signature, intended address) are kept
  but not consumed, with the reason recorded.
* Contradictions are surfaced deterministically within a declared case group and never resolved. Orders inside one artifact are kept
  apart by entity_ref; bridging several orders requires choosing one.

## Evaluation (eval/)
15 hand-labelled artifacts (4 adversarial). `python -m eval.evaluate` replays recorded outputs; `--live` uses AnthropicExtractor.
**The recorded outputs and the gold labels were both written by the assistant that built this repo, so the metrics are NOT an independent
measure of model accuracy.** They exercise the validator, bridge and engine. eval/results_first_run.json preserves a failed first run
(modality 63/67); eval/corpus.py GOLD_CHANGELOG records the gold correction made afterwards. For real accuracy, run `--live`.
