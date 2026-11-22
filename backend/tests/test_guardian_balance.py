from array import array
from io import BytesIO
import subprocess
from types import SimpleNamespace

import pytest

from app import guardian_balance
from app.analysis_engine import Commands
from app.guardian_balance import FRAMES_PER_MS, check_balance, measure_window
from app.render import file_hash


def pcm(*blocks):
    data = array('f')
    for duration, left, right in blocks:
        data.extend(array('f', [left, right]) * (duration * FRAMES_PER_MS))
    return BytesIO(data.tobytes())


def test_measurement_ignores_pauses_and_short_bursts_and_keeps_stereo_energy():
    speech = pcm((400, 0, 0), (500, 0.02, -0.02), (100, 0.02, -0.02))
    background = pcm((400, 0.2, 0.2), (500, 0, 0), (100, 0.2, 0.2))
    assert measure_window(speech, background, 0, 1000) == {'status': 'clear', 'active_dialogue_ms': 600}
    background = pcm((400, 0.2, 0.2), (300, 0.2, -0.2), (300, 0, 0))
    assert measure_window(speech, background, 0, 1000) == {
        'status': 'review', 'active_dialogue_ms': 600, 'start_ms': 400, 'end_ms': 700,
        'dialogue_dbfs': -34.0, 'background_dbfs': -14.0, 'margin_db': -20.0,
    }


@pytest.mark.parametrize(('gain', 'corrupt', 'status', 'issue'), [
    (1, False, 'checked', 'dialogue_background_masking'),
    (0.05, False, 'checked', None),
    (1, True, 'unavailable', 'dialogue_balance_unavailable'),
])
def test_fixed_mix_with_real_ffmpeg_audio(tmp_path, monkeypatch, gain, corrupt, status, issue):
    sources = {}
    for name, frequency in [('voice', 340), ('music', 900)]:
        audio = tmp_path / f'{name}.wav'
        subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i',
                        f'sine=frequency={frequency}:sample_rate=48000:duration=1.1', str(audio)],
                       check=True, timeout=20)
        sources[name] = {'storage_key': audio.name, 'sha256': file_hash(audio)}
    if corrupt:
        sources['music']['sha256'] = '0' * 64

    monkeypatch.setattr(guardian_balance.storage, 'resolve_key', lambda key: tmp_path / key)
    tracks = [
        {'id': 'main', 'role': 'main'},
        {'id': 'voice', 'role': 'dialogue', 'volume': 0.4,
         'clips': [{'id': 'speech', 'asset_id': 'voice', 'at': 0, 'frames': 25}]},
        {'id': 'bed', 'role': 'music', 'volume': gain,
         'clips': [{'id': 'bed', 'asset_id': 'music', 'at': 12, 'frames': 12, 'source_in': 1}]},
        {'id': 'muted', 'role': 'sfx', 'volume': 0,
         'clips': [{'id': 'ignored', 'asset_id': 'absent', 'at': 0, 'frames': 25}]},
    ]
    render = SimpleNamespace(parameters={'timeline': {'frames': 25, 'tracks': tracks}}, input_snapshot={'assets': sources})
    commands = Commands(tmp_path / 'qc', lambda *_: None)
    issues = []
    lines = [{'shot_number': 1, 'start_ms': 0, 'end_ms': 1042, 'audio_status': 'signal'}]
    result = check_balance(commands, render, lines, lambda *finding: issues.append(finding))
    assert result['status'] == status
    assert [row[0] for row in issues] == ([issue] if issue else [])
    assert not list(commands.output.iterdir())
    if not corrupt:
        balance = lines[0]['balance']
        assert balance['status'] == ('review' if issue else 'clear')
        if issue:
            assert (balance['start_ms'], balance['end_ms']) == (500, 1000)
            assert balance['margin_db'] == pytest.approx(-8, abs=0.3)
