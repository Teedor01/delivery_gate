"""Delivery Gate Phase 4: fixture-driven web UI.

Layers (dependencies point downward only):
    server.py    HTTP routes (stdlib http.server), no business logic
    render.py    HTML views built from presenter view-models
    presenter.py plain-language translation of engine / adapter outputs; it maps, it never decides
    service.py   application service: calls the EXISTING Phase 1-3 components (PayPal adapter, extraction pipeline, review bridge,
                 deterministic engine, counterfactual) and holds in-memory demo state
Nothing here re-implements policy, extraction or assessment, and no UI state can reach the engine except through the bridge.
"""
