"""Extension boundary for local perception, separate from governed P5 text calls."""
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from .text_adapters import live_gate

Capability = Literal['asr', 'ocr', 'diarization', 'source_separation', 'video_understanding']


@dataclass(frozen=True)
class PerceptionInput:
    asset_sha256: str
    media_path: Path
    start_us: int
    end_us: int
    stream_index: int


@dataclass(frozen=True)
class Observation:
    start_us: int
    end_us: int
    text: str
    confidence: float | None = None


@dataclass(frozen=True)
class PerceptionOutput:
    adapter_version: str
    observations: tuple[Observation, ...] = ()
    # Local stems are written to a Worker-owned staging directory, like FFmpeg artifacts.
    staged_files: tuple[Path, ...] = ()


class PerceptionAdapter(Protocol):
    capability: Capability

    def run(self, source: PerceptionInput, staging: Path) -> PerceptionOutput: ...


CAPABILITIES = {
    'asr': '语音转写',
    'ocr': '画面文字识别',
    'diarization': '说话人分段',
    'source_separation': '音源分离',
    'video_understanding': '视频内容理解',
}


def available_capabilities():
    return {'capabilities': [{'id': key, 'label': label, 'status': 'pending_integration',
                             'available': False} for key, label in CAPABILITIES.items()],
            'text_live_authorized': live_gate(),
            'text_gate': '/api/text/status'}


def align_to_shots(items, shots):
    """Index all overlapping half-open intervals without rewriting source timestamps."""
    from bisect import bisect_right

    ends = [shot['end_us'] for shot in shots]
    aligned = []
    for item in items:
        first = bisect_right(ends, item['start_us'])
        indices = []
        for i in range(first, len(shots)):
            if shots[i]['start_us'] >= item['end_us']:
                break
            indices.append(i + 1)
        aligned.append({**item, 'shots': indices})
    return aligned
