from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .models import EVIDENCE_NAMES, TRANSACTION_FACT_NAMES, ClaimCategory, UnknownItem

ROOT = Path(__file__).resolve().parent.parent
POLICY_DIR = ROOT / "policy"

RULE_STATUSES = {"UNREVIEWED", "REVIEWED"}
ITEM_KINDS = {"EXPLICIT_REQUIREMENT", "EXPLICIT_CONDITION", "EXCLUSION", "INTERPRETATION"}
RULE_MODES = {"EVALUATE", "NOT_COVERED"}
GATE_TYPES = {"jurisdiction", "route", "goods_scope"}
REQUIRED_RULE_KEYS = {
    "rule_id", "version", "status", "policy", "jurisdiction", "claim_category", "mode", "source_ids",
    "policy_effect", "eligibility_determination", "gates", "policy_conditions", "exclusions", "checks",
    "open_requirements", "not_modeled", "unknowns",
}
NOT_ESTABLISHED_CLAIM = "PAYPAL_ACCEPTS_THIS_ARTIFACT_AS_SUFFICIENT_PROOF"


class RegistryError(ValueError):
    pass


@dataclass(frozen=True)
class SourceRef:
    source_id: str
    url: str
    title: str
    last_updated: Optional[str]
    retrieved_at: str
    source_hash: Optional[str]
    hash_status: str

    def to_dict(self) -> Dict[str, Any]:
        return {"id": self.source_id, "url": self.url, "title": self.title,
                "last_updated": self.last_updated, "retrieved_at": self.retrieved_at,
                "source_hash": self.source_hash, "hash_status": self.hash_status}


@dataclass(frozen=True)
class Rule:
    rule_id: str
    version: str
    status: str
    jurisdiction: str
    claim_category: str
    mode: str
    sources: Tuple[SourceRef, ...]
    raw: Dict[str, Any]        
    file_sha256: str

    def unknowns(self) -> Tuple[UnknownItem, ...]:
        return tuple(UnknownItem(u["id"], u["text"], tuple(u["passage_ids"])) for u in self.raw["unknowns"])

    def all_passage_ids(self) -> List[str]:
        found: List[str] = []

        def walk(o: Any):
            if isinstance(o, dict):
                for k, v in o.items():
                    if k in ("passage_ids", "floor_passage_ids", "reviewed_passage_ids", "establishing_passage_ids"):
                        found.extend(v)
                    else:
                        walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(self.raw)
        return sorted(set(found))

    def resolved(self, passages: Dict[str, Any]) -> Dict[str, Any]:
        """Rule with sources and passage hashes inlined, for audit display."""
        d = copy.deepcopy(self.raw)
        d["sources"] = [s.to_dict() for s in self.sources]
        d["passages"] = {p: passages[p]["passage_sha256"][:12] for p in self.all_passage_ids()}
        d["file_sha256"] = self.file_sha256
        return d


class PolicyRegistry:
    def __init__(self, policy_dir: Path = POLICY_DIR, evaluator_names: Optional[set] = None):
        self.policy_dir = Path(policy_dir)
        self.sources: Dict[str, SourceRef] = {}
        self.passages: Dict[str, Any] = {}
        self.rules: Dict[str, Rule] = {}
        self._by_category: Dict[str, Rule] = {}
        self._evaluator_names = evaluator_names
        self._load()

    # ---- loading ----------------------------------------------------------------------------
    def _load(self) -> None:
        for sid, s in json.loads((self.policy_dir / "sources.json").read_text()).items():
            self.sources[sid] = SourceRef(sid, s["url"], s["title"], s.get("last_updated"), s["retrieved_at"],
                                          s.get("source_hash"), s.get("hash_status", "UNKNOWN"))
        self.passages = json.loads((self.policy_dir / "passages.json").read_text())["passages"]
        for path in sorted((self.policy_dir / "rules").glob("*.json")):
            raw_bytes = path.read_bytes()
            doc = json.loads(raw_bytes)
            self.validate_rule_doc(doc)
            rule = Rule(doc["rule_id"], doc["version"], doc["status"], doc["jurisdiction"], doc["claim_category"],
                        doc["mode"], tuple(self.sources[s] for s in doc["source_ids"]), doc,
                        hashlib.sha256(raw_bytes).hexdigest())
            if rule.rule_id in self.rules:
                raise RegistryError(f"duplicate rule_id {rule.rule_id}")
            if rule.claim_category in self._by_category:
                raise RegistryError(f"two rules for category {rule.claim_category}")
            self.rules[rule.rule_id] = rule
            self._by_category[rule.claim_category] = rule
        self._check_name_collisions()

    # ---- validation -------------------------------------------------------------------------
    def validate_rule_doc(self, doc: Dict[str, Any]) -> None:
        missing = REQUIRED_RULE_KEYS - set(doc)
        if missing:
            raise RegistryError(f"{doc.get('rule_id')}: missing keys {sorted(missing)}")
        rid = doc["rule_id"]
        if doc["status"] not in RULE_STATUSES:
            raise RegistryError(f"{rid}: status must be one of {sorted(RULE_STATUSES)} (never 'VERIFIED')")
        if doc["mode"] not in RULE_MODES:
            raise RegistryError(f"{rid}: bad mode")
        if doc["claim_category"] not in {c.value for c in ClaimCategory}:
            raise RegistryError(f"{rid}: unknown claim_category")
        for sid in doc["source_ids"]:
            if sid not in self.sources:
                raise RegistryError(f"{rid}: unknown source {sid}")
        if doc["status"] != "UNREVIEWED":
            unhashed = [s for s in doc["source_ids"] if self.sources[s].source_hash is None]
            if unhashed:
                raise RegistryError(f"{rid}: cannot be {doc['status']} while sources {unhashed} have no raw-byte hash")
            if not doc.get("reviewed_by") or not doc.get("interpretation_reviewed"):
                raise RegistryError(f"{rid}: REVIEWED requires reviewed_by and interpretation_reviewed")
        if not doc["unknowns"] and doc["mode"] == "EVALUATE":
            raise RegistryError(f"{rid}: unknowns must be stated explicitly")
        ids = set()

        def need_passages(owner: str, pids: List[str], allow_empty: bool = False):
            if not pids and not allow_empty:
                raise RegistryError(f"{owner}: passage_ids must not be empty")
            for p in pids:
                if p not in self.passages:
                    raise RegistryError(f"{owner}: unknown passage id {p}")

        def uniq(i: str):
            if i in ids:
                raise RegistryError(f"{rid}: duplicate id {i}")
            ids.add(i)

        for g in doc["gates"]:
            uniq(g["gate_id"])
            if g["type"] not in GATE_TYPES:
                raise RegistryError(f"{g['gate_id']}: unknown gate type")
            if g["kind"] not in ITEM_KINDS:
                raise RegistryError(f"{g['gate_id']}: bad kind")
            need_passages(g["gate_id"], g["passage_ids"])
            for a in g.get("actions", {}).values():
                need_passages(g["gate_id"], a["passage_ids"])
            if g.get("interpretation") and not g.get("interpretation_note"):
                raise RegistryError(f"{g['gate_id']}: interpretation requires interpretation_note")
        for x in doc["exclusions"]:
            uniq(x["exclusion_id"])
            need_passages(x["exclusion_id"], x["passage_ids"])
        for c in doc["checks"]:
            uniq(c["check_id"])
            if c["kind"] not in ITEM_KINDS:
                raise RegistryError(f"{c['check_id']}: bad kind (UNKNOWN items belong in not_modeled/unknowns)")
            need_passages(c["check_id"], c["passage_ids"])
            if c.get("interpretation") and not c.get("interpretation_note"):
                raise RegistryError(f"{c['check_id']}: interpretation requires interpretation_note")
            self._check_evaluator(c["check_id"], c["evaluator"])
            if not c.get("establishes"):
                raise RegistryError(f"{c['check_id']}: `establishes` (field-level statement) is required")
            stated = c.get("sufficiency_stated_by_policy")
            if not isinstance(stated, bool):
                raise RegistryError(f"{c['check_id']}: sufficiency_stated_by_policy must be a boolean")
            if stated:
                need_passages(c["check_id"] + ".sufficiency", c.get("sufficiency_passage_ids", []))
            elif NOT_ESTABLISHED_CLAIM not in c.get("does_not_establish", []):
                raise RegistryError(f"{c['check_id']}: must list {NOT_ESTABLISHED_CLAIM} under does_not_establish "
                                    "unless the policy explicitly states sufficiency")
        for pc in doc["policy_conditions"]:
            uniq(pc["condition_id"])
            need_passages(pc["condition_id"], pc["passage_ids"])
            m = pc["mapping"]
            if m["established"]:
                need_passages(pc["condition_id"] + ".mapping", m["establishing_passage_ids"])
                if not m["satisfied_values"]:
                    raise RegistryError(f"{pc['condition_id']}: an established mapping must list satisfied_values")
            else:
                if m["satisfied_values"] or m["unsatisfied_values"] or m["establishing_passage_ids"]:
                    raise RegistryError(f"{pc['condition_id']}: status values may not appear in rule data unless the "
                                        "mapping is established by primary documentation (establishing_passage_ids)")
                if pc.get("status_semantics") != "UNKNOWN":
                    raise RegistryError(f"{pc['condition_id']}: status_semantics must stay UNKNOWN until established")
            need_passages(pc["condition_id"] + ".mapping.reviewed", m["reviewed_passage_ids"], allow_empty=True)
        for o in doc["open_requirements"]:
            uniq(o["open_id"])
            need_passages(o["open_id"], o["passage_ids"])
            self._check_evaluator(o["open_id"], o["evaluator"])
        for n in doc["not_modeled"]:
            uniq(n["id"])
            need_passages(n["id"], n["passage_ids"], allow_empty=True)
        for u in doc["unknowns"]:
            need_passages(u["id"], u["passage_ids"], allow_empty=True)
        need_passages(rid + ".policy_effect", doc["policy_effect"]["passage_ids"])
        need_passages(rid + ".eligibility_determination", doc["eligibility_determination"]["passage_ids"])

    def _check_evaluator(self, owner: str, name: str) -> None:
        if self._evaluator_names is not None and name not in self._evaluator_names:
            raise RegistryError(f"{owner}: evaluator {name!r} is not implemented")

    def _check_name_collisions(self) -> None:
        """A fact can never share a name with a policy item, so facts cannot overwrite requirements."""
        reserved = set()
        for r in self.rules.values():
            d = r.raw
            reserved |= {r.rule_id}
            reserved |= {g["gate_id"] for g in d["gates"]} | {x["exclusion_id"] for x in d["exclusions"]}
            reserved |= {c["check_id"] for c in d["checks"]} | {o["open_id"] for o in d["open_requirements"]}
            reserved |= {pc["condition_id"] for pc in d["policy_conditions"]}
        clash = reserved & (set(TRANSACTION_FACT_NAMES) | set(EVIDENCE_NAMES))
        if clash:
            raise RegistryError(f"policy ids collide with fact names: {sorted(clash)}")

    # ---- access -----------------------------------------------------------------------------
    def rule_for(self, category: str) -> Optional[Rule]:
        return self._by_category.get(category)

    def dump(self) -> Dict[str, Any]:
        return {rid: r.resolved(self.passages) for rid, r in sorted(self.rules.items())}

    def summary_rows(self) -> List[Dict[str, Any]]:
        return [{"rule_id": r.rule_id, "version": r.version, "status": r.status, "jurisdiction": r.jurisdiction,
                 "category": r.claim_category, "mode": r.mode,
                 "gates": len(r.raw["gates"]), "policy_conditions": len(r.raw["policy_conditions"]), "checks": len(r.raw["checks"]),
                 "exclusions": len(r.raw["exclusions"]), "unknowns": len(r.raw["unknowns"]),
                 "passages": len(r.all_passage_ids()),
                 "source_hashes": [s.source_hash for s in r.sources]} for r in self.rules.values()]
