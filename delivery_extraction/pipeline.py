from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from delivery_extraction.contradictions import Contradiction, detect
from delivery_extraction.extractor import Extractor, RawExtraction
from delivery_extraction.schema import Artifact, CandidateFact
from delivery_extraction.validate import ValidationReport, validate_output


@dataclass
class ArtifactResult:
    artifact: Artifact
    raw: RawExtraction
    report: ValidationReport


@dataclass
class ExtractionRun:
    results: List[ArtifactResult] = field(default_factory=list)
    contradictions: List[Contradiction] = field(default_factory=list)

    @property
    def artifacts(self) -> Dict[str, Artifact]:
        return {r.artifact.artifact_id: r.artifact for r in self.results}

    @property
    def candidates(self) -> List[CandidateFact]:
        return [f for r in self.results for f in r.report.accepted]

    def to_audit(self) -> Dict[str, Any]:
        return {"artifacts": [{"artifact_id": r.artifact.artifact_id, "declared_kind": r.artifact.declared_kind,
                               "sha256": r.artifact.sha256, "extractor_kind": r.raw.extractor_kind, "model": r.raw.model,
                               "prompt_sha256": r.raw.prompt_sha256, "request_sha256": r.raw.request_sha256,
                               "raw_output": r.raw.text, "validation": r.report.to_dict()} for r in self.results],
                "contradictions": [c.to_dict() for c in self.contradictions]}


def run_extraction(artifacts: Sequence[Artifact], extractor: Extractor,
                   groups: Optional[Dict[str, List[str]]] = None) -> ExtractionRun:
    """`groups` maps a case id to the artifact ids that describe that case; contradictions are only searched within a group.
    With groups=None ALL supplied artifacts are treated as one case, so only pass artifacts of a single transaction."""
    run = ExtractionRun()
    for a in artifacts:
        raw = extractor.extract(a)
        run.results.append(ArtifactResult(a, raw, validate_output(a, raw.text)))
    groups = groups or {"default": [a.artifact_id for a in artifacts]}
    for gid, ids in groups.items():
        members = [f for r in run.results if r.artifact.artifact_id in ids for f in r.report.accepted]
        run.contradictions += detect(members, gid)
    return run


def write_audit(run: ExtractionRun, path: Path) -> None:
    Path(path).write_text(json.dumps(run.to_audit(), indent=2, ensure_ascii=False))
