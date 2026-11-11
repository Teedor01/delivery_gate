import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from delivery_extraction.bridge import build_case, assess_extraction, trace_fact  # noqa: E402
from delivery_extraction.extractor import MappingExtractor, RecordedExtractor  # noqa: E402
from delivery_extraction.pipeline import run_extraction  # noqa: E402
from delivery_extraction.review import Attestation, ReviewAction, ReviewDecision  # noqa: E402
from delivery_extraction.schema import Artifact  # noqa: E402
from delivery_extraction.validate import validate_output  # noqa: E402
from eval.corpus import ARTIFACTS, CASE_GROUPS  # noqa: E402
from tests.helpers import REG, S, assess, ES, PA, EFA  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ART = {a["id"]: Artifact(a["id"], a["text"], a["kind"]) for a in ARTIFACTS}
_RUN = None


def recorded_run():
    global _RUN
    if _RUN is None:
        _RUN = run_extraction(list(ART.values()), RecordedExtractor(ROOT / "eval" / "recorded_outputs"), CASE_GROUPS)
    return _RUN


def facts_of(*ids):
    run = recorded_run()
    return [f for r in run.results if r.artifact.artifact_id in ids for f in r.report.accepted]


def cand(fact_id):
    return next(f for f in recorded_run().candidates if f.fact_id == fact_id)


def base_case():
    """PayPal-supplied transaction facts + merchant-supplied evidence that does NOT come from the extraction layer."""
    c = S.inr_case("EXT-CASE")
    c = c.with_changes(remove_evidence=["delivery_record", "tracking_number", "delivery_date", "delivered_status", "recipient_address",
                                        "shipped_to_transaction_address", "redirect_detected"])
    return c.with_changes(set_evidence=[S.merchant("redirect_detected", False)])


def mk_fact(art, **o):
    f = {"fact_id": "f1", "fact": "delivery_status", "value": "delivered", "normalized_value": "DELIVERED",
         "source_span": "delivered", "confidence": "HIGH", "ambiguity": False, "ambiguity_note": None,
         "attribution": "UNKNOWN", "modality": "DIRECT", "entity_ref": None, "artifact_id": art.artifact_id}
    f.update(o)
    return f


def mk_out(art, facts, notes=(), **extra):
    d = {"artifact_id": art.artifact_id, "facts": list(facts), "extraction_notes": list(notes)}
    d.update(extra)
    return json.dumps(d)


def art(text, aid="T1", kind="OTHER"):
    return Artifact(aid, text, kind)
