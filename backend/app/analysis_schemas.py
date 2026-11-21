from typing import Literal

from pydantic import Field, model_validator

from .story_schemas import Strict

Operation = Literal['inspect', 'split', 'remux', 'transcode', 'frames', 'scenes', 'subtitles', 'waveform', 'ocr', 'hard_subtitles', 'asr']
OCR_OPERATIONS = {'ocr', 'hard_subtitles'}


class AnalysisOptions(Strict):
    operation: Operation
    stream: int | None = Field(default=None, ge=0, le=1023)
    container: Literal['mkv', 'mp4'] = 'mkv'
    max_edge: Literal[480, 720, 1080, 1920, 3840] = 720
    crf: int = Field(default=20, ge=0, le=28)
    fps: Literal[24, 25, 30, 60] | None = None
    sample_rate: Literal[32000, 44100, 48000] = 48000
    channels: Literal[1, 2] | None = None
    frame_mode: Literal['interval', 'keyframe', 'at'] = 'interval'
    frame_interval: float = Field(default=5, ge=0.25, le=3600)
    frame_time: float = Field(default=0, ge=0, le=86400)
    scene_threshold: float = Field(default=0.30, ge=0.05, le=0.95)
    minimum_shot_seconds: float = Field(default=0.30, ge=0.1, le=60)
    silence_db: int = Field(default=-40, ge=-99, le=-10)
    silence_seconds: float = Field(default=0.4, ge=0.1, le=60)
    ocr_language: str | None = Field(default=None, pattern=r'^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$', max_length=48)
    asr_language: str | None = Field(default=None, pattern=r'^[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*$', max_length=48)
    scan_start_ms: int = Field(default=0, ge=0, lt=86_400_000, strict=True)
    scan_end_ms: int | None = Field(default=None, gt=0, le=86_400_000, strict=True)
    subtitle_interval: float = Field(default=0.5, ge=0.25, le=2)
    subtitle_region: Literal['lower', 'full'] = 'lower'

    @model_validator(mode='after')
    def stream_options(self):
        if self.stream is not None and self.operation in ('inspect', 'remux'):
            raise ValueError('流清单与转封装作用于整份素材，不接受单流索引')
        if self.operation == 'hard_subtitles' and self.scan_end_ms is not None and self.scan_end_ms <= self.scan_start_ms:
            raise ValueError('硬字幕扫描终点必须晚于起点')
        if self.operation == 'asr' and self.scan_end_ms is not None and self.scan_end_ms <= self.scan_start_ms:
            raise ValueError('语音转写终点必须晚于起点')
        return self

    def signature_parameters(self):
        fields = {
            'remux': {'container'},
            'transcode': {'max_edge', 'crf', 'fps', 'sample_rate', 'channels'},
            'frames': {'frame_mode', 'frame_interval', 'frame_time'},
            'scenes': {'scene_threshold', 'minimum_shot_seconds'},
            'waveform': {'silence_db', 'silence_seconds'},
            'ocr': {'frame_interval', 'ocr_language'},
            'hard_subtitles': {'subtitle_interval', 'ocr_language', 'scan_start_ms', 'scan_end_ms', 'subtitle_region'},
            'asr': {'asr_language', 'scan_start_ms', 'scan_end_ms'},
        }
        return self.model_dump(include={'operation', 'stream'} | fields.get(self.operation, set()))


class AnalysisRequest(Strict):
    asset_id: str
    steps: list[AnalysisOptions] = Field(min_length=1, max_length=12)
    idempotency_key: str = Field(min_length=1, max_length=64)
