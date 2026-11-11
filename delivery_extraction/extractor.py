from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from delivery_extraction.schema import Artifact


@dataclass(frozen=True)
class RawExtraction:
    text: str
    extractor_kind: str                  
    model: Optional[str] = None
    prompt_sha256: Optional[str] = None
    request_sha256: Optional[str] = None


class Extractor(Protocol):
    def extract(self, artifact: Artifact) -> RawExtraction: ...


class RecordedExtractor:
    """Replays eval/recorded_outputs/<artifact_id>.json. Those files were produced by the assistant that built this repo,
    following delivery_extraction/prompt.py, NOT by an automated API call (see recorded_outputs/MANIFEST.json)."""
    KIND = "RECORDED_ASSISTANT_OUTPUT"

    def __init__(self, directory: Path, prompt_sha256: Optional[str] = None):
        self.dir, self.prompt_sha256 = Path(directory), prompt_sha256

    def extract(self, artifact: Artifact) -> RawExtraction:
        return RawExtraction((self.dir / f"{artifact.artifact_id}.json").read_text(), self.KIND, None, self.prompt_sha256, None)


class MappingExtractor:
    """Test helper: returns canned text per artifact id (used to inject deliberately bad model outputs)."""
    KIND = "TEST_INJECTED_OUTPUT"

    def __init__(self, outputs):
        self.outputs = dict(outputs)

    def extract(self, artifact: Artifact) -> RawExtraction:
        return RawExtraction(self.outputs[artifact.artifact_id], self.KIND)
