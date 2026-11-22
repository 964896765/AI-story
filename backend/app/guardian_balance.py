"""Measure dialogue against the background tracks in a fixed timeline mix."""
from array import array
from math import isfinite, log10
import subprocess
from sys import byteorder

from . import storage
from .media import probe
from .render import file_hash
from .story_schemas import Timeline
from .timeline_render import AUDIO, FPS, MEDIA_FORMATS, audio_filter, audio_mix, duck_music, music_ducking_applies

RULE_VERSION = 'guardian-dialogue-balance-v1'
STAGE = 'qc_dialogue_balance'
BACKGROUND = {'music', 'sfx'}
RATE = 16000
FRAMES_PER_MS = RATE // 1000
BYTES_PER_FRAME = 8
BLOCK_MS = 100
MIN_OVERLAP_MS = 300
MIN_MARGIN_DB = 6
MARGIN_POWER_RATIO = 10 ** (MIN_MARGIN_DB / 10)
VOICE_FLOOR_POWER = 10 ** (-75 / 10)
BACKGROUND_FLOOR_POWER = 10 ** (-50 / 10)


def overlaps(clip, line):
    return (clip.at * 1000 < line['end_ms'] * FPS
            and (clip.at + clip.frames) * 1000 > line['start_ms'] * FPS)


def pre_limiter_mix(commands, audio, snapshots, frames, targets, *, ducking):
    graph, arguments, records = [], [], {}
    labels = {role: [] for role in AUDIO}
    for index, (role, clip, volume) in enumerate(audio):
        if clip.asset_id not in records:
            source = snapshots[clip.asset_id]
            path = storage.resolve_key(source['storage_key'])
            commands.update(STAGE, 95)
            if file_hash(path, lambda *_: commands.update(STAGE, 95)) != source['sha256']:
                raise ValueError('混音分析所需的固定素材哈希已变化')
            records[clip.asset_id] = (path, probe(path))
        path, metadata = records[clip.asset_id]
        arguments.extend(['-protocol_whitelist', 'file,pipe', '-format_whitelist', MEDIA_FORMATS, '-i', str(path)])
        graph.append(audio_filter(index, clip, metadata, volume))
        labels[role].append(f'[clipa{index}]')

    argv = ['ffmpeg', '-nostdin', '-v', 'error', '-n', '-xerror', '-filter_complex_threads', '2', *arguments]
    if ducking:
        dialogue, music = duck_music(graph, labels['dialogue'], labels['music'], frames)
        graph.append(dialogue + 'anull[speech]')
        background = [music, *labels['sfx']]
    else:
        graph.append(audio_mix(labels['dialogue'], frames) + '[speech]')
        background = [*labels['music'], *labels['sfx']]
    graph.append(audio_mix(background, frames) + '[background]')
    script = commands.work / 'dialogue-balance-graph.txt'
    script.write_text(';\n'.join(graph), encoding='utf-8')
    argv.extend(['-filter_complex_script', script.name])
    for group, target in zip(('speech', 'background'), targets):
        argv.extend(['-map', f'[{group}]', '-ar', str(RATE), '-c:a', 'pcm_f32le', '-f', 'f32le', str(target)])
    commands.run(argv, STAGE, 95, timeout=240)
    length = round(frames * RATE / FPS) * BYTES_PER_FRAME
    if any(abs(target.stat().st_size - length) > BYTES_PER_FRAME for target in targets):
        raise ValueError('分轨长度与固定时间轴不符')


def power(handle, duration_ms):
    expected = duration_ms * FRAMES_PER_MS * BYTES_PER_FRAME
    raw = handle.read(expected)
    if len(raw) != expected:
        raise ValueError('分轨音频不足以覆盖对白时段')
    samples = array('f')
    samples.frombytes(raw)
    if byteorder != 'little':
        samples.byteswap()
    result = sum(sample * sample for sample in samples) / len(samples)
    if not isfinite(result):
        raise ValueError('分轨音频包含无效采样值')
    return result


def measure_window(speech, background, start_ms, end_ms):
    for handle in (speech, background):
        handle.seek(start_ms * FRAMES_PER_MS * BYTES_PER_FRAME)
    active_ms = 0
    interval = []
    longest = []
    for start in range(start_ms, end_ms, BLOCK_MS):
        end = min(start + BLOCK_MS, end_ms)
        duration = end - start
        voice_power = power(speech, duration)
        bed_power = power(background, duration)
        active = voice_power >= VOICE_FLOOR_POWER
        if active:
            active_ms += duration
        if active and bed_power >= BACKGROUND_FLOOR_POWER and voice_power < bed_power * MARGIN_POWER_RATIO:
            interval.append((start, end, voice_power, bed_power))
            if not longest or end - interval[0][0] > longest[-1][1] - longest[0][0]:
                longest = interval
        else:
            interval = []
    result = {'status': 'clear' if active_ms else 'no_speech_signal', 'active_dialogue_ms': active_ms}
    if longest and longest[-1][1] - longest[0][0] >= MIN_OVERLAP_MS:
        start, end = longest[0][0], longest[-1][1]
        voice_power = sum((stop - begin) * voice for begin, stop, voice, _ in longest) / (end - start)
        bed_power = sum((stop - begin) * bed for begin, stop, _, bed in longest) / (end - start)
        result.update(status='review', start_ms=start, end_ms=end, background_dbfs=round(10 * log10(bed_power), 1),
                      dialogue_dbfs=round(10 * log10(voice_power), 1),
                      margin_db=round(10 * log10(voice_power / bed_power), 1))
    return result


def check_balance(commands, render, lines, add):
    timeline = Timeline.model_validate(render.parameters['timeline'])
    candidates = [line for line in lines if line['audio_status'] == 'signal']
    all_audio = [(track.role, clip, track.volume) for track in timeline.tracks if track.enabled and track.role in AUDIO
                 for clip in sorted(track.clips,key=lambda item:item.at)]
    relevant = [(role, clip, gain) for role, clip, gain in all_audio
                if gain and any(overlaps(clip, line) for line in candidates)]
    roles = {role for role, _, _ in relevant}
    result = {'rule_version': RULE_VERSION, 'status': 'not_needed', 'minimum_margin_db': MIN_MARGIN_DB,
              'minimum_duration_ms': MIN_OVERLAP_MS}
    if 'dialogue' not in roles or not roles & BACKGROUND:
        return result

    targets = [commands.output / name for name in ('dialogue-f32.pcm', 'background-f32.pcm')]
    try:
        snapshots = render.input_snapshot['assets']
        ducking = music_ducking_applies(timeline)
        # Earlier clips can affect the compressor's release time inside a dialogue window.
        pre_limiter_mix(commands, all_audio if ducking else relevant, snapshots, timeline.frames, targets, ducking=ducking)
        available_ms = min(target.stat().st_size for target in targets) // (BYTES_PER_FRAME * FRAMES_PER_MS)
        measured = []
        with targets[0].open('rb') as speech, targets[1].open('rb') as background:
            for line in candidates:
                commands.update(STAGE, 96)
                measured.append((line, measure_window(speech, background, line['start_ms'], min(line['end_ms'], available_ms))))
    except (KeyError, OSError, ValueError, subprocess.SubprocessError) as exc:
        commands.update(STAGE, 96)
        (commands.work / 'dialogue-balance.error').write_text(str(exc), encoding='utf-8')
        add('dialogue_balance_unavailable', 'warning', '未能测量对白与背景声，请回听实际成片')
        result['status'] = 'unavailable'
        return result
    finally:
        for target in targets:
            target.unlink(missing_ok=True)

    result['status'] = 'checked'
    for line, measurement in measured:
        line['balance'] = measurement
        if measurement['status'] == 'review':
            add('dialogue_background_masking', 'warning', f"第 {line['shot_number']} 镜的背景声可能盖住对白，请回听",
                measurement['start_ms'], measurement['end_ms'])
        elif measurement['status'] == 'no_speech_signal':
            add('dialogue_background_masking', 'warning', f"第 {line['shot_number']} 镜的对白轨信号过低，请回听",
                line['start_ms'], line['end_ms'])
    return result
