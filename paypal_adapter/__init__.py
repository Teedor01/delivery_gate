"""Delivery Gate Phase 3: PayPal observation adapter.

    PayPal API response (fixture today) -> observe_* -> Observations (raw + provenance) -> handoff.to_case -> Case -> deterministic engine

The adapter is an OBSERVATION layer. It records what PayPal returned and where, and never what it means for policy.
`adapter.py` and `inventory.py` do not import delivery_gate at all; only `handoff.py` does, to build a Case.
"""
