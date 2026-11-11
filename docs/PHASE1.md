# Delivery Gate, Phase 1: policy registry + deterministic assessment engine (corrected)

Scope: US Seller Protection, INR, UNAUTHORIZED_TRANSACTION, SNAD (as NOT_COVERED), physical goods, fixtures only.
Not built (by instruction): UI, AI extraction, PayPal API integration, demo.

Run the tests:  `python3 -m unittest discover -s tests -t .`
Review output:   `python3 tools/walkthrough.py registry|inr|unauth|snad`

## Layers (separate types)
POLICY_REQUIREMENT = rules in `policy/rules/*.json`   |  TRANSACTION_FACT = `TransactionFact`  |  evidence input = `EvidenceFact`
EVIDENCE_ASSESSMENT = `EvidenceAssessment` (one per policy requirement, field level)  |  PROTECTION_ASSESSMENT = `Assessment.protection_assessment`
UNKNOWN = `UnknownItem`, `open_items`, `not_modeled`, `observed_inputs` (NOT_SUPPLIED / PROVENANCE_UNKNOWN)

## Two questions that are never merged
* `evidence_fields_assessment`: are the FIELDS a policy requirement names present and consistent in the supplied artifacts?
  (REQUIREMENT_FIELDS_DEMONSTRATED / REQUIREMENT_FIELDS_NOT_DEMONSTRATED). Each check carries `establishes` (a field-level
  statement such as "carrier_record contains a tracking number") and `corroboration` (CORROBORATED / MERCHANT_ASSERTED_ONLY).
* `paypal_acceptance`: would PayPal accept the artifact as sufficient proof? Always NOT_ESTABLISHED. No policy text retrieved
  says any artifact is sufficient. `PAYPAL_ACCEPTS_THIS_ARTIFACT_AS_SUFFICIENT_PROOF` appears only under `does_not_establish`.

## PayPal status is opaque
`paypal_seller_protection_status` is stored as an observed value with `status_semantics = UNKNOWN`. No token (including
PARTIALLY_ELIGIBLE and NOT_ELIGIBLE) satisfies or fails the policy condition. The assessment exposes
`PAYPAL_STATUS_OBSERVED` and `POLICY_STATUS_MAPPING = UNKNOWN`. A rule may only list status values if
`mapping.established` is true and cites `establishing_passage_ids` (primary documentation); the registry rejects anything else.

## Roll-up priority (UNKNOWN never becomes PASS)
triggered exclusion / unsatisfied established condition -> NOT_COVERED
any modeled requirement not demonstrated -> REQUIREMENTS_NOT_DEMONSTRATED
any unresolved exclusion or policy condition -> UNKNOWN
otherwise -> REQUIREMENTS_DEMONSTRATED_PAYPAL_DECIDES (modeled requirement fields only; PayPal still decides)

## Provenance of the rules
All rules are UNREVIEWED; every source_hash is null (raw bytes were not obtainable in the build environment). Every assessment carries
`policy_status` and `display_notice`. **A UI must display `display_notice` and must never present an assessment as an officially
verified PayPal interpretation.** The registry refuses REVIEWED without hashes and sign-off, and refuses VERIFIED outright.

## Counterfactuals
`counterfactual()` returns CURRENT_FACTS, COUNTERFACTUAL_FACTS, CHANGED_REQUIREMENTS (named policy requirements, with kind,
description and passage ids) and RESULT_CHANGE (protection_assessment and evidence_fields_assessment, before/after).
