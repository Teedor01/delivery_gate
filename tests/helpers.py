import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delivery_gate.engine import assess, counterfactual, default_registry  # noqa: E402
import json  # noqa: E402
from delivery_gate.models import (Case, Changes, EvidenceFieldsAssessment as EFA, EvidenceStatus as ES, ProtectionAssessment as PA)  # noqa: E402
from delivery_gate import samples as S  # noqa: E402

REG = default_registry()


def text(a):
    return "\n".join(a.explanation)


def blocking_ids(a):
    return sorted(c.check_id for c in a.blocking())


def add_evidence(case, *items):
    return Case(case.case_id, case.transaction_facts, case.evidence + tuple(items))
