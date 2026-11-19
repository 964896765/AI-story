"""Read-only, bounded local media analysis using FFmpeg and ffprobe."""
from __future__ import annotations

from array import array
from collections import Counter
from decimal import Decimal, InvalidOperation
from fractions import Fraction
from functools import lru_cache
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from .analysis_schemas import AnalysisOptions
from .perception_ocr import recognize, recognizer
from .process_guard import attach
from .render import display_size, file_hash, stop_process, write_manifest

ALGORITHM = 'ffmpeg-media-v1'
FORMATS = 'mov,matroska,webm,avi,wav,mp3'
MAX_BYTES = 5 * 1024**3
MAX_LOG = 16 * 1024**2
MAX_FRAMES = 240
MAX_OCR_FRAMES = 120
MEDIA_TYPES = {'.mkv': 'video/x-matroska', '.mka': 'audio/x-matroska',
               '.mp4': 'video/mp4', '.srt': 'text/plain; charset=utf-8', '.jpg': 'image/jpeg'}
TEXT_CODECS = {'subrip', 'ass', 'ssa', 'mov_text', 'webvtt', 'text'}


@lru_cache(maxsize=1)
def tools_version():
    return {
        tool: subprocess.check_output([tool, '-version'], timeout=10).decode(errors='replace').splitlines()[0]
        for tool in ('ffmpeg', 'ffprobe')
    }


def micros(value):
    try:
        return round(Decimal(str(value)) * 1_000_000)
    except (InvalidOperation, ValueError, OverflowError):
        return None


def probe_duration(info, stream=None):
    for candidate in ((stream or {}).get('duration'), info['format'].get('duration')):
        duration = micros(candidate)
        if duration is not None and duration > 0:
            return duration
    raise ValueError('媒体时长缺失或无效')


class Commands:
    def __init__(self, work, update):
        self.work = work
        self.output = work / 'files'
        self.output.mkdir(parents=True)
        self.update = update
        self.commands = []

    def run(self, argv, stage, progress, timeout=3600):
        index = len(self.commands) + 1
        stdout = self.work / f'{index:02d}.stdout'
        stderr = self.work / f'{index:02d}.stderr'
        self.commands.append({'argv': argv, 'stage': stage, 'stderr': stderr.name})
        write_manifest(self.work / 'commands.json', self.commands)
        self.update(stage, progress)
        with stdout.open('wb') as out, stderr.open('wb') as err:
            process = subprocess.Popen(argv, cwd=self.work, stdin=subprocess.DEVNULL, stdout=out, stderr=err)
            close_job = None
            try:
                close_job = attach(process)
                start = time.monotonic()
                while True:
                    self.update(stage, progress)
                    paths = list(self.output.iterdir())
                    if stdout.stat().st_size > MAX_LOG or stderr.stat().st_size > MAX_LOG:
                        raise ValueError('媒体分析日志超过 16 MiB')
                    if sum(path.stat().st_size for path in paths) > MAX_BYTES:
                        raise ValueError('本步骤输出超过 5 GiB')
                    pcm = self.work / 'waveform.pcm'
                    if pcm.exists() and pcm.stat().st_size > 232 * 1024**2:
                        raise ValueError('音频采样超过 4 小时上限')
                    if shutil.disk_usage(self.work).free < 128 * 1024**2:
                        raise OSError('磁盘可用空间不足 128 MiB')
                    if time.monotonic() - start > timeout:
                        raise TimeoutError(f'{stage} 超过单命令时间限制')
                    if process.poll() is not None:
                        break
                    time.sleep(0.15)
            finally:
                stop_process(process)
                if close_job:
                    close_job()
        with stderr.open('rb') as log:
            log.seek(max(0, stderr.stat().st_size - 4000))
            tail = log.read().decode('utf-8', errors='replace')
        if process.returncode:
            raise ValueError(f'{stage} 失败（退出码 {process.returncode}）\n{tail}')
        return stdout, stderr

    def probe(self, source, stage='analysis_probe', fmt=FORMATS, extra=()):
        stdout, _ = self.run(['ffprobe', '-v', 'error', '-protocol_whitelist', 'file,pipe',
                              '-format_whitelist', fmt, *extra, '-of', 'json', str(source)], stage,
                             87 if stage == 'analysis_verify' else 12, timeout=120)
        return json.loads(stdout.read_bytes())

    def ffmpeg(self, source, args, *, normalized=True, info=False):
        clock = ['-copyts', '-start_at_zero'] if normalized else []
        return self.run(['ffmpeg', '-hide_banner', '-nostdin', '-n', '-xerror', '-v', 'info' if info else 'error',
                         '-filter_threads', '2', *clock, '-protocol_whitelist', 'file,pipe',
                         '-format_whitelist', FORMATS, '-threads', '2', '-i', str(source), *args],
                        'analysis_process', 35)[1]


def inventory(commands, source):
    info = commands.probe(source, extra=['-show_streams', '-show_format'])
    streams = info.get('streams', [])
    if not streams or len(streams) > 64:
        raise ValueError('未检测到媒体流或媒体流超过 64 条')
    info['format'].pop('filename', None)
    info['timeline'] = {'unit': 'microsecond', 'origin': 'container_start',
                        'source_start_us': micros(info['format'].get('start_time'))}
    for stream in streams:
        stream['source_start_us'] = micros(stream.get('start_time'))
        if stream['codec_type'] == 'video' and not stream.get('disposition', {}).get('attached_pic'):
            stream['display_size'] = display_size(stream)
            stream['rotation'] = next((item['rotation'] for item in stream.get('side_data_list', [])
                                       if 'rotation' in item), stream.get('tags', {}).get('rotate', 0))
        stream['language'] = stream.get('tags', {}).get('language') or stream.get('tags', {}).get('LANGUAGE')
    return info


def typed_streams(info, *kinds):
    return [s for s in info['streams'] if s['codec_type'] in kinds and not s.get('disposition', {}).get('attached_pic')]


def choose(info, stream_index, *kinds):
    choices = typed_streams(info, *kinds)
    if stream_index is None:
        return choices[0] if choices else None
    for stream in choices:
        if stream['index'] == stream_index:
            return stream
    raise ValueError('指定流不存在或流类型不适用')


def require_video(info, index):
    stream = choose(info, index, 'video')
    if not stream:
        raise ValueError('素材没有可解码的视频流')
    width, height = stream['width'], stream['height']
    if max(width, height) > 8192 or width * height > 36_000_000:
        raise ValueError('视频超过本机解码尺寸限制')
    return stream


def cadence(commands, source, info):
    result = {}
    for stream in typed_streams(info, 'video')[:4]:
        frames = commands.probe(source, extra=['-select_streams', str(stream['index']), '-read_intervals', '%+#400',
                                                '-show_frames', '-show_entries', 'frame=best_effort_timestamp'])
        pts = [int(f['best_effort_timestamp']) for f in frames.get('frames', []) if 'best_effort_timestamp' in f]
        deltas = [b - a for a, b in zip(pts, pts[1:])]
        kind = 'insufficient_sample'
        if len(deltas) >= 2:
            kind = 'non_monotonic_sample' if min(deltas) <= 0 else (
                'variable_sample' if max(deltas)-min(deltas) > 1 else 'constant_sample')
        result[str(stream['index'])] = {'status': kind, 'sample_frames': len(pts),
                                        'delta_ticks': dict(Counter(deltas).most_common(12)),
                                        'time_base': stream.get('time_base')}
    return result


def verify_media(commands, path, expected, *, copied=False, duration_us=None):
    report = commands.probe(path, 'analysis_verify', extra=['-show_streams', '-show_format'])
    streams = report.get('streams', [])
    actual_types = [s['codec_type'] for s in streams]
    if actual_types != [s['codec_type'] for s in expected]:
        raise ValueError('产物媒体流映射与请求不一致')
    if copied and [s.get('codec_name') for s in streams] != [s.get('codec_name') for s in expected]:
        raise ValueError('转封装产物的编码类型发生变化')
    if duration_us is not None and abs(probe_duration(report) - duration_us) > max(500_000, duration_us // 100):
        raise ValueError('产物时长超出验证容差')
    return {key: [{k: s[k] for k in ('index', 'codec_type', 'codec_name', 'width', 'height',
              'time_base', 'start_time', 'duration', 'sample_rate', 'channels', 'pix_fmt',
              'avg_frame_rate', 'color_primaries', 'color_transfer', 'color_space', 'side_data_list') if k in s}
                   for s in streams] for key in ('streams',)} | {'duration_us': micros(report['format'].get('duration'))}


def descriptor(commands, path, role, **metadata):
    size = path.stat().st_size
    if not size:
        raise ValueError('产物为空')
    return {'name': path.name, 'role': role, 'media_type': MEDIA_TYPES[path.suffix], 'size_bytes': size,
            'sha256': file_hash(path, lambda *_: commands.update('analysis_verify', 93)), **metadata}


def media_copy(commands, source, info, options):
    streams = typed_streams(info, 'video', 'audio', 'subtitle')
    if options.stream is not None:
        streams = [choose(info, options.stream, 'video', 'audio', 'subtitle')]
    if not streams:
        raise ValueError('没有可分离的音视频或字幕流')
    if len(streams) > 24:
        raise ValueError('此操作最多处理 24 条流，请单选流索引')
    groups = [streams] if options.operation == 'remux' else [[stream] for stream in streams]
    outputs = []
    for group in groups:
        stream = group[0]
        remux = options.operation == 'remux'
        name = ('remux.' + options.container if remux else
                f"stream-{stream['index']}." + ('mka' if stream['codec_type'] == 'audio' else 'mkv'))
        path = commands.output / name
        mapping = [item for s in group for item in ('-map', f"0:{s['index']}")]
        commands.ffmpeg(source, [*mapping, '-map_metadata', '-1', '-c', 'copy', '-avoid_negative_ts',
                                'disabled', name_for(path)])
        metadata = verify_media(commands, path, group, copied=True,
                                duration_us=probe_duration(info) if remux else None)
        outputs.append(descriptor(commands, path, 'remux' if remux else 'track',
                                  source_streams=[s['index'] for s in group], **metadata))
    return {'artifacts': outputs}


def name_for(path):
    return str(Path('files') / path.name)


def transcode(commands, source, info, options):
    video = require_video(info, options.stream)
    if (video.get('color_transfer') in ('smpte2084', 'arib-std-b67') or
            video.get('pix_fmt') not in ('yuv420p', 'yuvj420p', 'nv12', 'yuv422p', 'yuvj422p', 'yuv444p', 'yuvj444p')):
        raise ValueError('该预设只处理 SDR 8-bit YUV。HDR 或其他像素格式请保留原片或转封装')
    width, height = video['display_size']
    ratio = min(1, options.max_edge / max(width, height))
    size = [max(2, round(edge * ratio / 2) * 2) for edge in (width, height)]
    filters = f'scale={size[0]}:{size[1]}:flags=lanczos,setsar=1'
    audio = choose(info, None, 'audio')
    args = ['-map', f"0:{video['index']}"]
    if audio:
        args += ['-map', f"0:{audio['index']}", '-c:a', 'aac', '-b:a', '192k', '-ar', str(options.sample_rate)]
        if options.channels:
            args += ['-ac', str(options.channels)]
    if options.fps:
        filters += f',fps={options.fps}'
    path = commands.output / 'proxy.mp4'
    commands.ffmpeg(source, [*args, '-vf', filters, '-fps_mode', 'passthrough', '-map_metadata', '-1',
                            '-c:v', 'libx264', '-threads:v', '2', '-preset', 'fast', '-crf', str(options.crf),
                            '-pix_fmt', 'yuv420p', '-movflags', '+faststart', name_for(path)])
    expected = [video, audio] if audio else [video]
    metadata = verify_media(commands, path, expected, duration_us=probe_duration(info))
    output = metadata['streams'][0]
    if (output['codec_name'] != 'h264' or [output['width'], output['height']] != size
            or output['pix_fmt'] != 'yuv420p' or any(item.get('rotation', 0) for item in output.get('side_data_list', []))):
        raise ValueError('代理画幅、旋转或编码验证失败')
    if audio:
        output_audio = metadata['streams'][1]
        if (output_audio['codec_name'] != 'aac' or int(output_audio['sample_rate']) != options.sample_rate
                or (options.channels and output_audio['channels'] != options.channels)):
            raise ValueError('代理音频编码、采样率或声道验证失败')
    return {'artifacts': [descriptor(commands, path, 'proxy',
                                    source_streams=[s['index'] for s in expected], **metadata)]}


def capture_frames(commands, source, info, options):
    stream = require_video(info, options.stream)
    width, height = stream['display_size']
    ocr = options.operation == 'ocr'
    ratio = min(1, (1440 if ocr else 480) / max(width, height))
    size = [max(2, round(edge * ratio / 2) * 2) for edge in (width, height)]
    scene_mode = options.operation == 'scenes'
    if scene_mode:
        expression = f'isnan(prev_selected_t)+gte(t-prev_selected_t,{options.minimum_shot_seconds})*gt(scene,{options.scene_threshold})'
    elif not ocr and options.frame_mode == 'keyframe':
        expression = 'key'
    elif not ocr and options.frame_mode == 'at':
        expression = f'gte(t,{options.frame_time})'
    else:
        expression = f'isnan(prev_selected_t)+gte(t-prev_selected_t,{options.frame_interval})'
    filters = f"select='{expression}',showinfo,scale={size[0]}:{size[1]},setsar=1"
    if scene_mode:
        filters += ',metadata=mode=print:key=lavfi.scene_score:file=scores.txt'
    limit = MAX_OCR_FRAMES if ocr else MAX_FRAMES
    cap = 1 if options.operation == 'frames' and options.frame_mode == 'at' else limit + 1
    log = commands.ffmpeg(source, ['-map', f"0:{stream['index']}", '-vf', filters, '-frames:v', str(cap),
                                   '-c:v', 'mjpeg', '-threads:v', '2', '-q:v', '3', '-fps_mode', 'passthrough',
                                   name_for(commands.output / 'frame-%05d.jpg')], info=True)
    paths = sorted(commands.output.glob('frame-*.jpg'))
    if not paths:
        raise ValueError('选定时段没有可用帧')
    pts = re.findall(r'showinfo[^\n]*?\bn:\s*\d+\s+pts:\s*(-?\d+)', log.read_text(encoding='utf-8', errors='replace'))
    if len(pts) < len(paths):
        raise ValueError('抽帧文件与解码时间戳无法对应')
    time_base = Fraction(stream['time_base'])
    times = [round(int(pts[i])*time_base*1_000_000) for i in range(len(paths))]
    if any(a >= b for a, b in zip(times, times[1:])) or min(times) < 0:
        raise ValueError('素材时间戳异常，无法生成可靠时间轴')
    if scene_mode and len(paths) > MAX_FRAMES:
        raise ValueError('检测到超过 240 个镜头，请提高阈值或最短镜头时长')
    truncated = len(paths) > limit
    if truncated:
        paths.pop().unlink()
    artifacts = []
    for index, path in enumerate(paths):
        with path.open('rb') as frame:
            header = frame.read(2)
            frame.seek(-2, 2)
            if header != b'\xff\xd8' or frame.read(2) != b'\xff\xd9':
                raise ValueError('缩略图不是完整 JPEG')
        artifacts.append(descriptor(commands, path, 'shot_frame' if scene_mode else 'frame',
                                    stream_index=stream['index'], pts=int(pts[index]), time_us=times[index],
                                    time_base=stream['time_base'], width=size[0], height=size[1]))
    payload = {'artifacts': artifacts, 'truncated': truncated}
    if scene_mode:
        scores = {}
        score_file = commands.work / 'scores.txt'
        if score_file.is_file():
            for tick, score in re.findall(r'pts:\s*(-?\d+)[^\n]*\n[^\n]*lavfi.scene_score=([\d.]+)',
                                          score_file.read_text(encoding='utf-8')):
                scores[int(tick)] = float(score)
        duration = probe_duration(info, stream)
        end = duration + max(0, times[0]) if stream.get('duration') not in (None, 'N/A') else duration
        if times[-1] >= end:
            raise ValueError('镜头切点超出视频结束时间')
        payload['shots'] = [{'start_us': item['time_us'], 'end_us': next_time,
                             'score': None if i == 0 else scores.get(item['pts']), 'artifact': i}
                            for i, (item, next_time) in enumerate(zip(artifacts, times[1:] + [end]))]
    return payload


SRT_TIME = re.compile(r'(\d{2,}):(\d{2}):(\d{2}),(\d{3})')


def read_cues(path):
    if path.stat().st_size > 2 * 1024**2:
        raise ValueError('单条字幕超过 2 MiB')
    blocks = re.split(r'\n[ \t]*\n', path.read_text(encoding='utf-8-sig').strip())
    if len(blocks) > 10000:
        raise ValueError('单条字幕超过 10000 条')
    cues = []
    for block in blocks:
        lines = block.splitlines()
        matches = list(SRT_TIME.finditer(lines[1])) if len(lines) >= 3 else []
        if len(matches) != 2 or not lines[0].isdigit():
            raise ValueError('提取字幕的时间结构无法解析')
        start, end = [(int(h)*3600000 + int(m)*60000 + int(s)*1000 + int(ms))*1000
                      for h, m, s, ms in (m.groups() for m in matches)]
        if end <= start:
            raise ValueError('提取字幕含无效时段')
        cues.append({'start_us': start, 'end_us': end, 'text': '\n'.join(lines[2:])})
    return cues


def subtitles(commands, source, info, options):
    streams = typed_streams(info, 'subtitle') if options.stream is None else [choose(info, options.stream, 'subtitle')]
    if len(streams) > 12:
        raise ValueError('字幕流超过 12 条，请逐条指定流索引')
    artifacts, tracks = [], []
    for stream in streams:
        index = stream['index']
        entry = {'stream_index': index, 'language': stream['language']}
        if stream['codec_name'] not in TEXT_CODECS:
            tracks.append({**entry, 'status': 'bitmap_or_unsupported', 'cues': []})
            continue
        path = commands.output / f'subtitles-{index}.srt'
        commands.ffmpeg(source, ['-map', f'0:{index}', '-c:s', 'srt', name_for(path)])
        if not path.is_file() or not path.stat().st_size:
            path.unlink(missing_ok=True)
            tracks.append({**entry, 'status': 'empty_stream', 'cues': []})
            continue
        cues = read_cues(path)
        tracks.append({**entry, 'status': 'extracted', 'artifact': len(artifacts), 'cues': cues})
        artifacts.append(descriptor(commands, path, 'subtitles', **entry))
    return {'artifacts': artifacts, 'subtitle_tracks': tracks}


def waveform(commands, source, info, options):
    stream = choose(info, options.stream, 'audio')
    if not stream:
        return {'audio_status': 'no_audio', 'bins': [], 'silences': []}
    duration = probe_duration(info, stream)
    if duration > 4 * 3600 * 1_000_000:
        raise ValueError('波形步骤最多分析 4 小时音频')
    origin = info['timeline']['source_start_us'] or 0
    offset = max(0, (stream['source_start_us'] if stream['source_start_us'] is not None else origin) - origin)
    pcm = commands.work / 'waveform.pcm'
    filt = (f'aresample=8000:async=1:first_pts=0,silencedetect=n={options.silence_db}dB:'
            f'd={options.silence_seconds}')
    log = commands.ffmpeg(source, ['-map', f"0:{stream['index']}", '-af', filt, '-ac', '1', '-ar', '8000',
                                   '-f', 's16le', '-c:a', 'pcm_s16le', pcm.name], info=True)
    # PCM is anchored to container zero. Decode discontinuities become silence via aresample.
    samples = pcm.stat().st_size // 2
    if not samples or pcm.stat().st_size % 2:
        raise ValueError('没有有效音频采样')
    block = max(80, (samples + 2047) // 2048)
    bins = []
    try:
        with pcm.open('rb') as raw:
            while chunk := raw.read(block * 2):
                values = array('h')
                values.frombytes(chunk)
                if sys.byteorder != 'little':
                    values.byteswap()
                bins.append(round(max(abs(min(values)), abs(max(values))) / 32768, 5))
                commands.update('analysis_waveform', 82)
    finally:
        pcm.unlink(missing_ok=True)
    silences, start = [], None
    for kind, position in re.findall(r'silence_(start|end):\s*([-+\d.eE]+)', log.read_text(encoding='utf-8', errors='replace')):
        t = micros(position)
        if t is None:
            continue
        t = max(0, min(t, samples * 125))
        if kind == 'start':
            start = t
        elif start is not None:
            if t > start:
                silences.append({'start_us': start, 'end_us': t})
            start = None
    if start is not None and samples * 125 > start:
        silences.append({'start_us': start, 'end_us': samples * 125})
    if len(silences) > 20000:
        raise ValueError('静音段超过 20000 条，请提高最短静音时长')
    return {'audio_status': 'measured', 'stream_index': stream['index'], 'bins': bins, 'silences': silences,
            'bin_us': block * 125, 'duration_us': samples * 125, 'stream_offset_us': offset, 'start_us': 0}


def recognize_screen_text(commands, source, info, options):
    adapter = recognizer(options.ocr_language)
    payload = capture_frames(commands, source, info, options)
    payload['ocr'] = {**adapter, 'frames': recognize(commands, payload['artifacts'], adapter)}
    payload['duration_us'] = probe_duration(info)
    return payload


OPERATIONS = {'split': media_copy, 'remux': media_copy, 'transcode': transcode, 'frames': capture_frames,
              'scenes': capture_frames, 'subtitles': subtitles, 'waveform': waveform, 'ocr': recognize_screen_text}


def analyze(source: Path, work: Path, options: AnalysisOptions, update):
    commands = Commands(work, update)
    info = inventory(commands, source)
    payload = {'algorithm': ALGORITHM, 'tools': tools_version(), 'operation': options.operation,
               'timeline': info['timeline'], 'artifacts': []}
    if options.operation == 'inspect':
        payload.update({'media': info, 'cadence': cadence(commands, source, info)})
    else:
        payload.update(OPERATIONS[options.operation](commands, source, info, options))
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 12 * 1024**2:
        raise ValueError('解析结果超过 12 MiB，请选单流或降低采样密度')
    return payload
