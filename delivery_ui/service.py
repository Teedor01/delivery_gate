from __future__ import annotations

import copy
import json
import os
import pickle
import sqlite3
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from delivery_extraction import bridge, contradictions
from delivery_extraction.extractor import RecordedExtractor
from delivery_extraction.llm import LLMError, make_extractor
from delivery_extraction.pipeline import ArtifactResult, run_extraction
from delivery_extraction.review import Attestation, ReviewAction, ReviewDecision, ReviewError
from delivery_extraction.schema import ARTIFACT_KINDS, FACT_VOCAB, UNKNOWN, Artifact, CandidateFact
from delivery_gate.engine import Assessment, CounterfactualReport, assess, counterfactual, default_registry
from delivery_gate.models import Case, Changes, EvidenceFact, Provenance, ProvStatus, SourceType, TransactionFact
from eval.corpus import ARTIFACTS as CORPUS
from paypal_adapter import adapter as pp_adapter
from paypal_adapter import disputes as pp_disputes
from paypal_adapter import exposure as pp_exposure
from paypal_adapter.handoff import HandoffResult, merchant_jurisdiction_fact, to_case

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = Path(__file__).resolve().parent / "fixtures" / "transactions.json"
RECORDED_DIR = ROOT / "eval" / "recorded_outputs"
MAX_TEXT_CHARS = 20000
REVIEW_MODES = ("attest_carrier", "approve_merchant", "reject_all", "reject_fact", "undo")
RESPONSE_VALUES = ("NO_REQUEST_OUTSTANDING", "RESPONDED_WITHIN_REQUESTED_TIME", "RESPONSE_LATE_OR_MISSING")
ADDRESS_KEYS = ("line1", "line2", "city", "region", "postal_code", "country")


class ServiceError(ValueError):
    """A request the service refuses. `code` is stable for the HTTP layer and tests."""
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


class NotFound(ServiceError):
    pass


def _norm_text(t: str) -> str:
    return t.replace("\r\n", "\n").strip()


def corpus_index() -> Dict[str, Dict[str, Any]]:
    return {_norm_text(a["text"]): a for a in CORPUS}


# ---- extraction -------------------------------------------------------------------------------------------------------------
ExtractorFactory = Callable[[Artifact, Optional[str]], Tuple[Any, Optional[str], Optional[str]]]


def default_extractor_factory(artifact: Artifact, recognized_id: Optional[str]):
    """-> (extractor | None, extractor_kind | None, unavailable_message | None). Server-side only; keys never reach the browser."""
    if recognized_id:
        return RecordedExtractor(RECORDED_DIR), RecordedExtractor.KIND, None
    try:
        live = make_extractor(os.environ)
    except LLMError as e:
        return None, None, str(e)
    if live is not None:
        return live, live.KIND, None
    return None, None, ("No extraction model is configured in this environment, so this text could not be read automatically. "
                        "Only the built-in sample evidence can be read offline.")


# ---- state ------------------------------------------------------------------------------------------------------------------
@dataclass
class ArtifactRecord:
    artifact: Artifact
    source_label: str
    added_at: str
    status: str                                    
    message: Optional[str] = None
    extractor_kind: Optional[str] = None
    result: Optional[ArtifactResult] = None
    recognized_sample: bool = False
    fixture: bool = False

    @property
    def facts(self) -> List[CandidateFact]:
        return list(self.result.report.accepted) if self.result else []

    @property
    def rejected(self):
        return list(self.result.report.rejected) if self.result else []


@dataclass
class TransactionState:
    ref: str
    fixture: Dict[str, Any]
    artifacts: Dict[str, ArtifactRecord] = field(default_factory=dict)
    decisions: Dict[str, ReviewDecision] = field(default_factory=dict)
    attestations: Dict[str, Attestation] = field(default_factory=dict)
    review_log: List[Dict[str, Any]] = field(default_factory=list)
    events: List[Dict[str, Any]] = field(default_factory=list)
    merchant: Dict[str, Any] = field(default_factory=dict)
    entity_ref: Optional[str] = None
    next_upload: int = 1
    external_paypal: Optional[Dict[str, Any]] = None
    validation_snapshot: Optional[Dict[str, Any]] = None


@dataclass
class Analysis:
    ref: str
    state: TransactionState
    capture: Any
    dispute: Any
    handoff: HandoffResult
    exposure: Any
    base_case: Case
    bridge: Optional[bridge.BridgeResult]
    assessment: Optional[Assessment]
    contradictions: List[Any]
    candidates: List[CandidateFact]
    entities: List[str]
    needs_entity_choice: bool

    @property
    def case(self) -> Case:
        return self.bridge.case if self.bridge else self.base_case


@dataclass
class WhatIfOption:
    option_id: str
    label: str
    kind: str                       
    artifact_id: str
    detail: str


@dataclass
class WhatIfResult:
    option: WhatIfOption
    report: CounterfactualReport
    hypothetical_bridge: bridge.BridgeResult


# ---- service ----------------------------------------------------------------------------------------------------------------
class DeliveryGateService:
    def __init__(self, fixture_path: Path = FIXTURE_PATH, extractor_factory: ExtractorFactory = default_extractor_factory,
                 clock: Optional[Callable[[], datetime]] = None, registry=None, assess_fn: Callable = assess, db_path=None):
        self.registry = registry or default_registry()
        self._factory = extractor_factory
        self._clock = clock or (lambda: datetime.now(timezone.utc))
        self._assess = assess_fn                                    
        self._doc = json.loads(Path(fixture_path).read_text())
        configured_db = db_path or os.environ.get("DELIVERY_GATE_CASE_DB")
        if not configured_db:
            configured_db = Path(tempfile.mkstemp(prefix="delivery-gate-service-", suffix=".sqlite3")[1])
        self.db_path = Path(configured_db)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_persistence()
        self.merchant_name = self._doc["merchant"]["name"]
        self._corpus = corpus_index()
        self._corpus_by_id = {a["id"]: a for a in CORPUS}
        self.states: Dict[str, TransactionState] = {}
        self.reset()

    # -- lifecycle
    def now(self) -> str:
        return self._clock().astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def reset(self) -> None:
        """Reload demo data. Fixture evidence and reviews go through the same code paths as user actions."""
        self.states = {}
        for fx in self._doc["transactions"]:
            st = TransactionState(fx["ref"], copy.deepcopy(fx))
            mp = fx["merchant_provided"]
            st.merchant = {"country": mp["country"], "address": dict(mp["transaction_details_address"]), "answers": dict(mp["answers"]),
                           "physical_goods": mp["physical_goods"], "pre_order_or_made_to_order": mp["pre_order_or_made_to_order"]}
            self.states[fx["ref"]] = st
            for a in fx["artifacts"]:
                text = self._corpus_by_id[a["artifact_id"]]["text"]
                self._add(st, text, self._corpus_by_id[a["artifact_id"]]["kind"], a["source_label"], a["added_at"], fixture=True)
                r = a.get("review")
                if r:
                    self._review(st, a["artifact_id"], r["mode"], r["reviewer"], "Demo fixture review", r["at"], fixture=True)
        self._restore_live_states()

    def _init_persistence(self) -> None:
        with sqlite3.connect(str(self.db_path), timeout=15) as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS assessment_states (case_id TEXT PRIMARY KEY, state_blob BLOB NOT NULL, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")

    def _restore_live_states(self) -> None:
        with sqlite3.connect(str(self.db_path), timeout=15) as db:
            rows = db.execute("SELECT case_id, state_blob FROM assessment_states").fetchall()
        for case_id, blob in rows:
            try:
                state = pickle.loads(blob)
            except Exception as exc:
                raise RuntimeError(f"Persisted assessment {case_id} could not be restored") from exc
            if isinstance(state, TransactionState) and state.ref == case_id and state.external_paypal:
                self.states[case_id] = state

    def _persist_state(self, state: TransactionState, invalidate: bool = True) -> None:
        if not state.external_paypal:
            return
        if invalidate:
            state.validation_snapshot = None
        blob = pickle.dumps(state, protocol=pickle.HIGHEST_PROTOCOL)
        with sqlite3.connect(str(self.db_path), timeout=15) as db:
            db.execute("INSERT INTO assessment_states(case_id,state_blob,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) "
                       "ON CONFLICT(case_id) DO UPDATE SET state_blob=excluded.state_blob, updated_at=CURRENT_TIMESTAMP",
                       (state.ref, sqlite3.Binary(blob)))

    def _state(self, ref: str) -> TransactionState:
        if ref not in self.states:
            raise NotFound("transaction_not_found", f"No payment with reference {ref!r}.")
        return self.states[ref]

    def refs(self) -> List[str]:
        return list(self.states)

    def register_paypal_case(self, case_id: str, order_record: Dict[str, Any]) -> TransactionState:
        """Register a live PayPal order as a distinct assessment case; payment data stays separate from delivery evidence."""
        if case_id in self.states:
            st = self.states[case_id]
            if st.external_paypal and st.external_paypal.get("order_id") != order_record.get("order_id"):
                raise ServiceError("case_conflict", "Assessment case is already linked to another PayPal order.")
            st.external_paypal = copy.deepcopy(order_record)
            st.fixture["paypal_order"] = copy.deepcopy(order_record.get("order") or {})
            st.fixture["order_ref"] = order_record.get("order_id")
            self._persist_state(st)
            return st
        template = copy.deepcopy(self._doc["transactions"][0])
        template["ref"] = case_id
        template["order_ref"] = order_record.get("order_id")
        template["paypal_order"] = copy.deepcopy(order_record.get("order") or {})
        template["paypal_dispute"] = None
        # No fixture merchant assertions or address are carried into a real order.
        template["merchant_provided"] = {"country": None, "transaction_details_address": {}, "answers": {
            "redirect_detected": None, "response_to_paypal": None, "shipped_after_advised_not_to_release": None},
            "physical_goods": None, "pre_order_or_made_to_order": None}
        mp = template["merchant_provided"]
        st = TransactionState(case_id, template, merchant={"country": None, "address": {}, "answers": dict(mp["answers"]),
            "physical_goods": None, "pre_order_or_made_to_order": None}, external_paypal=copy.deepcopy(order_record))
        self.states[case_id] = st
        self._persist_state(st)
        return st

    def update_paypal_case(self, case_id: str, order_record: Dict[str, Any]) -> None:
        st = self._state(case_id)
        if not st.external_paypal or st.external_paypal.get("order_id") != order_record.get("order_id"):
            raise ServiceError("order_case_mismatch", "PayPal order does not belong to this assessment case.")
        st.external_paypal = copy.deepcopy(order_record)
        st.fixture["paypal_order"] = copy.deepcopy(order_record.get("order") or {})
        st.fixture["order_ref"] = order_record.get("order_id")
        self._persist_state(st)

    # -- evidence
    def add_artifact(self, ref: str, text: str, kind: str = "OTHER", source_label: str = "Pasted text") -> ArtifactRecord:
        st = self._state(ref)
        rec = self._add(st, text, kind, source_label, self.now(), fixture=False)
        self._persist_state(st)
        return rec

    def _add(self, st: TransactionState, text: Any, kind: str, source_label: str, at: str, fixture: bool) -> ArtifactRecord:
        if not isinstance(text, str) or not text.strip():
            raise ServiceError("empty_evidence", "There is no text to add. Paste the evidence or choose a text file.")
        if len(text) > MAX_TEXT_CHARS:
            raise ServiceError("evidence_too_long", f"Evidence is limited to {MAX_TEXT_CHARS:,} characters in this demo.")
        if kind not in ARTIFACT_KINDS:
            raise ServiceError("invalid_kind", f"Evidence type must be one of: {', '.join(ARTIFACT_KINDS)}.")
        normalised_input = _norm_text(text)
        for existing in st.artifacts.values():
            if _norm_text(existing.artifact.text) == normalised_input and existing.artifact.declared_kind == kind:
                return existing
        sample = self._corpus.get(normalised_input)
        if sample:                                                  
            aid, canonical_text = sample["id"], sample["text"]
            kind = sample["kind"] if fixture else kind
        else:
            while f"U{st.next_upload}" in st.artifacts:
                st.next_upload += 1
            aid, canonical_text = f"U{st.next_upload}", text.replace("\r\n", "\n")
        if aid in st.artifacts:
            return st.artifacts[aid]                               
        artifact = Artifact(aid, canonical_text, kind)
        extractor, ekind, why = self._factory(artifact, sample["id"] if sample else None)
        result, status, message = None, "UNAVAILABLE", why
        if extractor is not None:
            try:
                result = run_extraction([artifact], extractor).results[0]
                status, message, ekind = ("EXTRACTED" if result.report.accepted else "NO_FACTS"), None, result.raw.extractor_kind
                if not result.report.output_ok:
                    status, message = "FAILED", "The extraction output could not be validated: " + "; ".join(result.report.output_errors[:2])
            except Exception as e:                                  
                status, message = "FAILED", f"{type(e).__name__}: {e}"
        rec = ArtifactRecord(artifact, source_label, at, status, message, ekind, result, bool(sample), fixture)
        st.artifacts[aid] = rec
        n = len(rec.facts)
        outcome = {"EXTRACTED": f"{n} fact{'s' if n != 1 else ''} found", "NO_FACTS": "no usable facts found",
                   "UNAVAILABLE": "could not be read automatically", "FAILED": "analysis failed"}[status]
        self._event(st, at, "EVIDENCE_ADDED", f"Evidence {aid} added ({source_label}); {outcome}", fixture)
        return rec

    def consumable(self, rec: ArtifactRecord) -> List[CandidateFact]:
        return [f for f in rec.facts if FACT_VOCAB[f.fact]["engine"] and f.normalized_value != UNKNOWN]

    # -- review (the bridge is the authority on what a reviewer may do; this method only asks it)
    def review_artifact(self, ref: str, artifact_id: str, mode: str, reviewer: str, note: str = "", fact_id: Optional[str] = None) -> Dict[str, Any]:
        st = self._state(ref)
        result = self._review(st, artifact_id, mode, reviewer, note, self.now(), fixture=False, fact_id=fact_id)
        self._persist_state(st)
        return result

    def _review(self, st: TransactionState, aid: str, mode: str, reviewer: Any, note: str, at: str, fixture: bool, fact_id: Optional[str] = None) -> Dict[str, Any]:
        if mode not in REVIEW_MODES:
            raise ServiceError("invalid_review_mode", f"Review action must be one of: {', '.join(REVIEW_MODES)}.")
        rec = st.artifacts.get(aid)
        if rec is None:
            raise NotFound("artifact_not_found", f"No evidence {aid!r} on this payment.")
        reviewer = (reviewer or "").strip() if isinstance(reviewer, str) else ""
        if mode != "undo" and not (1 <= len(reviewer) <= 80):
            raise ServiceError("reviewer_required", "Enter the reviewer's name (up to 80 characters). It is recorded with the review.")
        facts = self.consumable(rec)
        mine = {f.fact_id for f in rec.facts}
        summary: Dict[str, Any] = {"mode": mode, "artifact_id": aid, "applied": [], "refused": []}
        if mode == "undo":
            for fid in list(st.decisions):
                if fid in mine:
                    del st.decisions[fid]
            st.attestations.pop(aid, None)
            text = f"Review of {aid} undone"
        elif mode == "reject_fact":
            target = next((f for f in rec.facts if f.fact_id == fact_id), None)
            if target is None:
                raise NotFound("fact_not_found", f"No fact {fact_id!r} in evidence {aid}.")
            st.decisions[target.fact_id] = ReviewDecision(target.fact_id, ReviewAction.REJECT, reviewer, note)
            summary["applied"].append(target.fact_id)
            text = f"{reviewer} rejected fact {target.fact_id}"
        elif mode == "reject_all":
            for f in facts:
                st.decisions[f.fact_id] = ReviewDecision(f.fact_id, ReviewAction.REJECT, reviewer, note)
                summary["applied"].append(f.fact_id)
            st.attestations.pop(aid, None)
            text = f"{reviewer} rejected the facts in {aid}"
        elif mode == "approve_merchant":
            for f in facts:
                st.decisions[f.fact_id] = ReviewDecision(f.fact_id, ReviewAction.APPROVE_AS_MERCHANT_ASSERTION, reviewer, note)
                summary["applied"].append(f.fact_id)
            st.attestations.pop(aid, None)
            text = f"{reviewer} recorded the facts in {aid} as the merchant's own statement (not corroborated)"
        else:                                                      
            att = Attestation(aid, reviewer)                       
            eligible, refused = [], []
            for f in facts:
                dec = ReviewDecision(f.fact_id, ReviewAction.APPROVE_AS_CARRIER_DOCUMENT, reviewer, note)
                try:
                    bridge.build_case(Case("probe"), [f], {aid: rec.artifact}, [dec], [att])
                    eligible.append(dec)
                except ReviewError as e:
                    refused.append({"fact_id": f.fact_id, "why": str(e)})
            if not eligible:
                why = refused[0]["why"] if refused else "there are no facts in this evidence that a carrier document could support"
                raise ServiceError("carrier_review_refused", f"This evidence cannot be recorded as a carrier document: {why}")
            st.attestations[aid] = att
            for d in eligible:
                st.decisions[d.fact_id] = d
                summary["applied"].append(d.fact_id)
            summary["refused"] = refused
            text = f"{reviewer} attested that {aid} is a genuine carrier document ({len(eligible)} fact(s) approved)"
        st.review_log.append({"at": at, "artifact_id": aid, "mode": mode, "reviewer": reviewer, "note": note, "fixture": fixture})
        self._event(st, at, "REVIEW_RECORDED", text, fixture)
        return summary

    # -- merchant-provided information
    def set_merchant_info(self, ref: str, data: Dict[str, Any]) -> None:
        st = self._state(ref)
        m = copy.deepcopy(st.merchant)
        if "country" in data:
            c = data["country"]
            if c in (None, ""):
                m["country"] = None
            elif isinstance(c, str) and len(c.strip()) == 2 and c.strip().isalpha():
                m["country"] = c.strip().upper()
            else:
                raise ServiceError("invalid_country", "Country must be a two-letter code such as US.")
        if "address" in data:
            a = data["address"]
            if not isinstance(a, dict) or set(a) - set(ADDRESS_KEYS):
                raise ServiceError("invalid_address", "Address fields must be: " + ", ".join(ADDRESS_KEYS) + ".")
            m["address"] = {k: v.strip() for k, v in a.items() if isinstance(v, str) and v.strip()}
        if "answers" in data:
            an = data["answers"]
            if not isinstance(an, dict):
                raise ServiceError("invalid_answers", "Answers must be an object.")
            allowed = {"redirect_detected": (True, False, None), "response_to_paypal": RESPONSE_VALUES + (None,),
                       "shipped_after_advised_not_to_release": (True, False, None)}
            for k, v in an.items():
                if k not in allowed or v not in allowed[k]:
                    raise ServiceError("invalid_answers", f"Invalid answer for {k!r}.")
                m["answers"][k] = v
        st.merchant = m
        self._event(st, self.now(), "ANSWERS_UPDATED", "Information provided by the merchant was updated", False)
        self._persist_state(st)

    def set_entity(self, ref: str, entity_ref: Optional[str]) -> None:
        st = self._state(ref)
        if entity_ref in (None, ""):
            st.entity_ref = None
            return
        if entity_ref not in self.analyze(ref).entities:
            raise ServiceError("unknown_entity", f"The evidence does not mention order {entity_ref!r}.")
        st.entity_ref = entity_ref
        self._event(st, self.now(), "ORDER_SELECTED", f"Evidence for order {entity_ref} selected", False)
        self._persist_state(st)

    # -- analysis
    def _event(self, st: TransactionState, at: str, kind: str, text: str, fixture: bool) -> None:
        st.events.append({"at": at, "kind": kind, "text": text, "fixture": fixture})

    def _merchant_base(self, st: TransactionState, handoff: HandoffResult) -> Case:
        m = st.merchant
        ref = f"merchant:{st.ref}"

        def fact(n, v):
            return TransactionFact(n, v, Provenance(SourceType.MERCHANT_INPUT, ref, ProvStatus.MERCHANT_ASSERTED))

        def ev(n, v):
            return EvidenceFact(n, v, Provenance(SourceType.MERCHANT_INPUT, ref, ProvStatus.MERCHANT_ASSERTED))

        facts = list(handoff.case.transaction_facts)
        if m.get("physical_goods") is not None:
            facts.append(fact("physical_goods", m["physical_goods"]))
        if m.get("pre_order_or_made_to_order") is not None:
            facts.append(fact("pre_order_or_made_to_order", m["pre_order_or_made_to_order"]))
        if m.get("address"):
            facts.append(fact("transaction_details_address", dict(m["address"])))
        evidence = [ev(k, v) for k, v in sorted(m["answers"].items()) if v is not None]
        return Case(st.ref, tuple(facts), tuple(evidence))

    def _paypal(self, st: TransactionState):
        fx = st.fixture
        order = pp_adapter.observe_order(fx["paypal_order"], origin="SANDBOX" if st.external_paypal else "FIXTURE")
        cap = order.select_capture()
        disp = pp_disputes.observe_dispute(fx["paypal_dispute"], origin="FIXTURE") if fx.get("paypal_dispute") else None
        country = merchant_jurisdiction_fact(st.merchant.get("country"), source_ref=f"merchant:{st.ref}")
        return cap, disp, to_case(cap, case_id=st.ref, dispute=disp, merchant_country=country)

    def _build(self, st: TransactionState, decisions: Dict[str, ReviewDecision], attestations: Dict[str, Attestation],
               extra: Optional[Dict[str, ArtifactRecord]] = None):
        cap, disp, handoff = self._paypal(st)
        base = self._merchant_base(st, handoff)
        recs = dict(st.artifacts)
        recs.update(extra or {})
        candidates = [f for r in recs.values() for f in r.facts]
        arts = {aid: r.artifact for aid, r in recs.items()}
        consumable = sorted({c.entity_ref for c in candidates if FACT_VOCAB[c.fact]["engine"] and c.normalized_value != UNKNOWN and c.entity_ref})
        br, needs = None, False
        try:
            br = bridge.build_case(base, candidates, arts, decisions.values(), attestations.values(), st.entity_ref)
        except bridge.MultipleEntitiesError:
            needs = True
        return cap, disp, handoff, base, br, candidates, consumable, needs

    def analyze(self, ref: str) -> Analysis:
        st = self._state(ref)
        cap, disp, handoff, base, br, candidates, entities, needs = self._build(st, st.decisions, st.attestations)
        a = None if needs else self._assess(self.registry, br.case)
        members = [f for r in st.artifacts.values() for f in r.facts]
        contra = contradictions.detect(members, st.ref)
        result = Analysis(ref, st, cap, disp, handoff, pp_exposure.build_exposure(cap, disp), base, br, a, contra, candidates, entities, needs)
        if st.external_paypal:
            st.validation_snapshot = {"assessment": a, "contradictions": contra, "needs_entity_choice": needs, "computed_at": self.now()}
            self._persist_state(st, invalidate=False)
        return result

    def list_analyses(self) -> List[Analysis]:
        return [self.analyze(r) for r in self.refs()]

    def trace(self, ref: str, fact_id: str) -> Dict[str, Any]:
        an = self.analyze(ref)
        if an.bridge is None or an.assessment is None:
            raise ServiceError("no_assessment", "Choose which order the evidence belongs to first.")
        fact = next((f for f in an.candidates if f.fact_id == fact_id), None)
        if fact is None:
            raise NotFound("fact_not_found", f"No fact {fact_id!r} on this payment.")
        return bridge.trace_fact(self.registry, an.bridge, an.assessment, fact, {k: r.artifact for k, r in an.state.artifacts.items()})

    # -- counterfactual (the existing engine.counterfactual; hypothetical evidence is produced by the same bridge)
    def what_if_options(self, ref: str) -> List[WhatIfOption]:
        st = self._state(ref)
        out: List[WhatIfOption] = []
        for aid, rec in st.artifacts.items():
            facts = self.consumable(rec)
            if not facts:
                continue
            carrier_done = aid in st.attestations
            if rec.artifact.declared_kind in bridge.CARRIER_KINDS and not carrier_done:
                out.append(WhatIfOption(f"review:{aid}:carrier", f"If evidence {aid} is reviewed as a genuine carrier document", "REVIEW_CARRIER", aid,
                                        "A reviewer attests that the document itself came from the carrier."))
            if not any(st.decisions.get(f.fact_id) and st.decisions[f.fact_id].action == ReviewAction.APPROVE_AS_MERCHANT_ASSERTION for f in facts) and not carrier_done:
                out.append(WhatIfOption(f"review:{aid}:merchant", f"If you confirm evidence {aid} as your own statement", "REVIEW_MERCHANT", aid,
                                        "The facts are recorded as the merchant's statement. They are not carrier evidence."))
        for s in st.fixture.get("suggested_evidence", []):
            if s["artifact_id"] not in st.artifacts:
                out.append(WhatIfOption(f"add:{s['artifact_id']}", f"If this were added and reviewed: {s['label']}", "ADD_SAMPLE", s["artifact_id"],
                                        "Sample evidence from the demo library, read by the same extraction and review steps."))
        return out

    def what_if(self, ref: str, option_id: str) -> WhatIfResult:
        st = self._state(ref)
        opt = next((o for o in self.what_if_options(ref) if o.option_id == option_id), None)
        if opt is None:
            raise NotFound("what_if_not_found", "That what-if is not available for this payment.")
        decisions, atts, extra = dict(st.decisions), dict(st.attestations), {}
        reviewer = "hypothetical"
        if opt.kind == "ADD_SAMPLE":
            sample = self._corpus_by_id[opt.artifact_id]
            art = Artifact(opt.artifact_id, sample["text"], sample["kind"])
            extractor, ekind, why = self._factory(art, opt.artifact_id)
            if extractor is None:
                raise ServiceError("extraction_unavailable", why or "Extraction is unavailable.")
            res = run_extraction([art], extractor).results[0]
            rec = ArtifactRecord(art, "Sample (hypothetical)", self.now(), "EXTRACTED", None, ekind, res, True, False)
            extra[opt.artifact_id] = rec
            use = rec
        else:
            use = st.artifacts[opt.artifact_id]
        facts = self.consumable(use)
        carrier = opt.kind in ("REVIEW_CARRIER", "ADD_SAMPLE")
        if carrier:
            att = Attestation(opt.artifact_id, reviewer)
            atts[opt.artifact_id] = att
        for f in facts:
            action = ReviewAction.APPROVE_AS_CARRIER_DOCUMENT if carrier else ReviewAction.APPROVE_AS_MERCHANT_ASSERTION
            dec = ReviewDecision(f.fact_id, action, reviewer)
            if carrier:                                             # keep only what the bridge itself allows a reviewer to do
                try:
                    bridge.build_case(Case("probe"), [f], {opt.artifact_id: use.artifact}, [dec], [atts[opt.artifact_id]])
                except ReviewError:
                    continue
            decisions[f.fact_id] = dec
        cap, disp, handoff, base, hyp, cands, ents, needs = self._build(st, decisions, atts, extra)
        if hyp is None:
            raise ServiceError("no_assessment", "Choose which order the evidence belongs to first.")
        current = self.analyze(ref)
        if current.bridge is None:
            raise ServiceError("no_assessment", "Choose which order the evidence belongs to first.")
        hyp_names = {e.name for e in hyp.case.evidence}
        changes = Changes(opt.label, set_evidence=tuple(hyp.case.evidence),
                          remove_evidence=tuple(sorted({e.name for e in current.case.evidence} - hyp_names)))
        report = counterfactual(self.registry, current.case, changes)
        return WhatIfResult(opt, report, hyp)
