"""Offline OCR through Windows recognizers already installed on this machine."""
from functools import lru_cache
import json
import os
from pathlib import Path
import platform
import subprocess
from unicodedata import normalize

from .config import ROOT

ENGINE = 'windows-ocr-v1'


def command():
    executable = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    if os.name != 'nt' or not executable.is_file():
        raise ValueError('此系统不提供 Windows 本机 OCR')
    return [str(executable), '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass', '-File',
            str(ROOT / 'scripts' / 'recognize_frames.ps1')]


@lru_cache(maxsize=1)
def installed_languages():
    try:
        result = subprocess.run([*command(), '-List'], capture_output=True, timeout=15, check=True)
        languages = json.loads(result.stdout.decode('utf-8-sig'))
    except (ValueError, OSError, subprocess.SubprocessError):
        return ()
    return tuple(languages)


def recognizer(language):
    languages = installed_languages()
    if not languages:
        raise ValueError('未发现 Windows 本机 OCR 识别器')
    language = language or languages[0]
    if language not in languages:
        raise ValueError('所选 OCR 语言未安装')
    return {'engine': ENGINE, 'language': language, 'system_version': platform.version()}


def recognize(commands, artifacts, adapter):
    stdout, _ = commands.run([*command(), '-FrameDirectory', str(commands.output), '-Language', adapter['language']],
                             'analysis_ocr', 73, timeout=180)
    frames = json.loads(stdout.read_bytes())
    if [item['name'] for item in frames] != [item['name'] for item in artifacts]:
        raise ValueError('OCR 输出与采样帧无法对应')
    return [{'artifact': i, 'time_us': artifact['time_us'], 'text': frame['text'].strip(), 'lines': frame['lines']}
            for i, (frame, artifact) in enumerate(zip(frames, artifacts))]


def estimate_subtitle_cues(frames, interval_us, end_us):
    """Join matching observations and bound each cue by the next sample and scan end."""
    cues = []
    previous_key = ''
    for index, frame in enumerate(frames):
        text = '\n'.join(line.strip() for line in frame['lines'] if line.strip()) or frame['text'].strip()
        key = ' '.join(normalize('NFKC', text).split())
        start = frame['time_us']
        next_time = frames[index+1]['time_us'] if index+1 < len(frames) else end_us
        # Tolerate small sampling jitter without extending cues across large gaps.
        end = min(next_time, end_us)
        if end-start > interval_us * 1.5:
            end = start + interval_us
        if key and end > start:
            if key == previous_key and cues[-1]['end_us'] == start:
                cues[-1]['end_us'] = end
                cues[-1]['sample_count'] += 1
            else:
                cues.append({'start_us': start, 'end_us': end, 'text': text,
                             'artifact': frame['artifact'], 'sample_count': 1})
            previous_key = key
        else:
            previous_key = ''
    return cues
