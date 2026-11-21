"""Use the Windows desktop dictation recognizers already installed locally."""
from functools import lru_cache
import json
import math
import os
from pathlib import Path
import platform
import subprocess

from .config import ROOT

ENGINE = 'windows-sapi-dictation-v1'
MAX_SCAN_SECONDS = 180


def command():
    executable = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    if os.name != 'nt' or not executable.is_file():
        raise ValueError('此系统不提供 Windows 本机语音转写')
    return [str(executable), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
            str(ROOT / 'scripts' / 'recognize_speech.ps1')]


@lru_cache(maxsize=1)
def installed_recognizers():
    try:
        result = subprocess.run([*command(), '-List'], capture_output=True, timeout=15, check=True)
        return tuple(json.loads(result.stdout.decode('utf-8-sig')))
    except (ValueError, OSError, subprocess.SubprocessError):
        return ()


def recognizer(language):
    installed = installed_recognizers()
    if not installed:
        raise ValueError('未发现 Windows 本机语音识别器')
    match = next((item for item in installed if language is None or item['language'] == language), None)
    if match is None:
        raise ValueError('所选 Windows 语音识别语言未安装')
    return {'engine': ENGINE, 'language': match['language'], 'recognizer_id': match['id'],
            'system_version': platform.version()}


def normalize_segments(segments, start_us, audio_duration_us):
    if not isinstance(segments, list) or len(segments) > 10_000:
        raise ValueError('本机转写结果格式无效或超过字幕条数上限')
    cues = []
    for segment in segments:
        if not isinstance(segment, dict):
            raise ValueError('本机转写分段格式无效')
        start, end = segment.get('start_us'), segment.get('end_us')
        text, confidence = segment.get('text'), segment.get('confidence')
        if (type(start) is not int or type(end) is not int or not 0 <= start < end or
                end > audio_duration_us + 20_000 or not isinstance(text, str) or
                type(confidence) not in (float, int) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ValueError('本机转写返回无效时间、文本或置信值')
        text = ' '.join(text.split())
        if not text:
            continue
        # Match the millisecond time base used by review and exported SRT.
        start = (start + start_us)//1000*1000
        end = (min(end, audio_duration_us) + start_us)//1000*1000
        if end <= start or (cues and start < cues[-1]['end_us']):
            raise ValueError('本机转写分段的时间无效或重叠')
        cues.append({'start_us': start, 'end_us': end, 'text': text, 'confidence': round(confidence, 6)})
    return cues


def transcribe(commands, path, adapter, start_us, audio_duration_us):
    stdout, _ = commands.run([*command(), '-InputWave', str(path), '-Recognizer', adapter['recognizer_id']],
                             'analysis_asr', 70, timeout=600)
    return normalize_segments(json.loads(stdout.read_bytes()), start_us, audio_duration_us)
