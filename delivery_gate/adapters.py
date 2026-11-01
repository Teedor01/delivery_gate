from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Protocol

from .models import Case, EvidenceFact, Provenance, ProvStatus, SourceType, TransactionFact


class TransactionDataSource(Protocol):
    def load_case(self, ref: str) -> Case: ...


def _prov(d: Dict[str, Any]) -> Provenance:
    return Provenance(SourceType(d["source_type"]), d["source_ref"], ProvStatus(d["status"]),
                      d.get("confidence"), d.get("timestamp"), d.get("text_span"))


def case_from_dict(d: Dict[str, Any]) -> Case:
    return Case(d["case_id"],
                tuple(TransactionFact(f["name"], f["value"], _prov(f["provenance"])) for f in d["transaction_facts"]),
                tuple(EvidenceFact(e["name"], e["value"], _prov(e["provenance"])) for e in d["evidence"]))


class FixtureSource:
    """Reads a case from fixtures/<ref>.json. Fixture data is labelled as fixture data in provenance."""
    def __init__(self, fixture_dir: Path):
        self.dir = Path(fixture_dir)

    def load_case(self, ref: str) -> Case:
        return case_from_dict(json.loads((self.dir / f"{ref}.json").read_text()))


class PayPalSandboxSource:
    def load_case(self, ref: str) -> Case: 
        raise NotImplementedError("PayPal sandbox integration is Phase 2 and has not been built or tested.")
