from array import array
from math import cos, hypot, log10, sin, tau
import subprocess

import pytest
from pydantic import ValidationError

from app import timeline_render as timeline_module
from app.render import file_hash
from app.story_schemas import Timeline
from app.timeline_render import MUSIC_DUCKING_PRESET, music_ducking_applies


def tone_level(samples, frequency, start, end):
    window = samples[round(48000 * start):round(48000 * end)]
    radians = tau * frequency / 48000
    real = sum(value * cos(index * radians) for index, value in enumerate(window))
    imaginary = sum(value * sin(index * radians) for index, value in enumerate(window))
    return 2 * hypot(real, imaginary) / len(window)


def test_ducking_is_opt_in_and_requires_live_music_and_dialogue():
    content = {'frames': 24, 'tracks': [{'id': 'main', 'role': 'main'}]}
    old = Timeline.model_validate(content)
    off = Timeline.model_validate({**content, 'music_ducking': False})
    assert 'music_ducking' not in old.model_dump()
    assert off.model_dump() == old.model_dump()
    with pytest.raises(ValidationError):
        Timeline.model_validate({**content, 'music_ducking': 'true'})

    tracks = [*content['tracks'],
              {'id': 'voice', 'role': 'dialogue', 'volume': 0, 'clips': [{'id': 'v', 'asset_id': 'voice', 'at': 0, 'frames': 24}]},
              {'id': 'bed', 'role': 'music', 'clips': [{'id': 'm', 'asset_id': 'bed', 'at': 0, 'frames': 24}]}]
    content = {**content, 'tracks': tracks, 'music_ducking': True}
    assert not music_ducking_applies(Timeline.model_validate(content))
    tracks[1]['volume'] = 1
    assert music_ducking_applies(Timeline.model_validate(content))
    tracks[2]['enabled'] = False
    assert not music_ducking_applies(Timeline.model_validate(content))


def test_real_mp4_reduces_music_only_during_dialogue_and_recovers_afterward(tmp_path, monkeypatch, record_testsuite_property):
    def ffmpeg(*args, capture=False):
        result = subprocess.run(['ffmpeg', '-nostdin', '-v', 'error', *args], check=True, timeout=25, capture_output=capture)
        return result.stdout

    video = tmp_path / 'video.mp4'
    ffmpeg('-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=24:duration=4', '-c:v', 'libx264', '-threads', '2', str(video))
    sources = {video.stem: video}
    for name, frequency, duration in [('voice', 440, 1), ('music', 1200, 4), ('sfx', 2100, 1)]:
        path = tmp_path / f'{name}.wav'
        ffmpeg('-f', 'lavfi', '-i', f'sine=frequency={frequency}:sample_rate=48000:duration={duration}', str(path))
        sources[name] = path

    def track(role, asset, start, frames):
        return {'id': role, 'role': role, 'clips': [{'id': asset, 'asset_id': asset, 'at': start, 'frames': frames}]}

    content = {'profile': 'square', 'frames': 96, 'tracks': [track('main','video',0,96), track('dialogue','voice',24,24),
                                                          track('music','music',0,96), track('sfx','sfx',24,24)]}
    snapshot = {'assets': {key: {'sha256': file_hash(path), 'storage_key': path.name} for key, path in sources.items()}}
    monkeypatch.setattr(timeline_module.storage, 'resolve_key', lambda key: tmp_path / key)

    def render(task_id, timeline):
        return timeline_module.timeline_render(task_id, 1, {'timeline': timeline}, snapshot, lambda *_: None)

    def decode(result):
        samples = array('f')
        samples.frombytes(ffmpeg('-i', str(tmp_path/result['storage_key']), '-map', '0:a:0', '-af', 'pan=mono|c0=c0',
                                 '-f', 'f32le', 'pipe:1', capture=True))
        return samples

    original = render('original', content)
    enabled = {**content, 'music_ducking': True}
    priority = render('priority', enabled)
    assert 'music_ducking' not in original
    assert priority['music_ducking'] == {'status': 'applied', 'preset': MUSIC_DUCKING_PRESET}
    assert priority['frames'] == original['frames'] == 96
    assert render('priority', enabled) == priority
    assert all(file_hash(sources[key]) == entry['sha256'] for key, entry in snapshot['assets'].items())
    original_pcm, priority_pcm = decode(original), decode(priority)
    for start, end in [(0.2, 0.8), (3.1, 3.7)]:
        assert tone_level(priority_pcm, 1200, start, end) == pytest.approx(tone_level(original_pcm, 1200, start, end), rel=0.04)
    music_ratio = tone_level(priority_pcm, 1200, 1.2, 1.8) / tone_level(original_pcm, 1200, 1.2, 1.8)
    assert music_ratio < 0.15
    record_testsuite_property('ducking_music_change_during_dialogue_db', round(20 * log10(music_ratio), 2))
    for frequency in (440, 2100):
        assert tone_level(priority_pcm, frequency, 1.2, 1.8) == pytest.approx(tone_level(original_pcm, frequency, 1.2, 1.8), rel=0.06)
