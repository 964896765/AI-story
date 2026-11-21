import os
from pathlib import Path
import subprocess

import pytest

from app.analysis_engine import analyze
from app.analysis_schemas import AnalysisOptions
from app.perception_ocr import estimate_subtitle_cues, installed_languages
from app.subtitle_revision import compile_srt


def test_ocr_cues_do_not_bridge_blank_frames_or_large_timestamp_gaps():
    captions = ['回家的路', '回家的路', '', '回家的路', '回家的路', '下一站']
    frames = [{'artifact': i, 'time_us': t, 'lines': [text], 'text': text}
              for i, (t, text) in enumerate(zip([0, 250000, 500000, 750000, 2000000, 2250000], captions))]
    cues = estimate_subtitle_cues(frames, 250000, 2400000)
    assert [(c['start_us'], c['end_us'], c['sample_count'], c['artifact']) for c in cues] == [
        (0, 500000, 2, 0), (750000, 1000000, 1, 3), (2000000, 2250000, 1, 4), (2250000, 2400000, 1, 5),
    ]
    assert estimate_subtitle_cues(frames[2:3], 250000, 750000) == []


def test_hard_subtitle_scan_rejects_reversed_window_and_pins_sampling_parameters():
    with pytest.raises(ValueError, match='终点必须晚于起点'):
        AnalysisOptions(operation='hard_subtitles', scan_start_ms=500, scan_end_ms=400)
    options = AnalysisOptions(operation='hard_subtitles', scan_start_ms=200, scan_end_ms=2500, subtitle_interval=.25)
    assert options.signature_parameters() == {
        'operation': 'hard_subtitles', 'stream': None, 'scan_start_ms': 200, 'scan_end_ms': 2500,
        'subtitle_interval': .25, 'subtitle_region': 'lower', 'ocr_language': None,
    }


def test_ffmpeg_and_windows_ocr_recover_two_known_subtitle_intervals(tmp_path):
    if 'zh-Hans-CN' not in installed_languages():
        pytest.skip('Windows simplified-Chinese OCR recognizer unavailable')
    font = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'Fonts' / 'simhei.ttf'
    if not font.is_file():
        pytest.skip('System font required for the authored fixture is unavailable')
    (tmp_path/'fixture.ttf').write_bytes(font.read_bytes())
    source = tmp_path/'source.mp4'
    subtitles = ",".join(
        f"drawtext=fontfile=fixture.ttf:text='{text}':fontsize=92:fontcolor=black:"
        f"x=(w-tw)/2:y={y}:enable='gte(t,{start})*lt(t,{end})'"
        for text, y, start, end in [('画面水印', '20', 0, 3), ('灯塔坐标', 'h-th-32', .5, 1.25),
                                   ('日出时间', 'h-th-32', 1.75, 2.5)])
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=white:s=960x540:r=24:d=3',
                    '-vf', subtitles, '-c:v', 'libx264', '-threads', '2', str(source)],
                   cwd=tmp_path, check=True, timeout=25)
    options = AnalysisOptions(operation='hard_subtitles', ocr_language='zh-Hans-CN',
                              scan_start_ms=250, scan_end_ms=2750, subtitle_interval=.25)
    with pytest.raises(ValueError, match='范围超出素材时长'):
        analyze(source, tmp_path/'out-of-range', options.model_copy(update={'scan_end_ms': 4500}), lambda *_: None)
    result = analyze(source, tmp_path/'run', options, lambda *_: None)
    track = result['subtitle_tracks'][0]
    assert track['status'] == 'ocr_estimated'
    assert [frame['time_us'] for frame in result['ocr']['frames']] == list(range(250000, 2750000, 250000))
    assert all(artifact['height'] == 216 for artifact in result['artifacts'])
    assert [''.join(cue['text'].split()) for cue in track['cues']] == ['灯塔坐标', '日出时间']
    assert [(cue['start_us'], cue['end_us'], cue['sample_count']) for cue in track['cues']] == [
        (500000, 1250000, 3), (1750000, 2500000, 3),
    ]
    srt, count = compile_srt(track['cues'], {}, result['duration_us'])
    assert count == 2 and b'00:00:00,500 --> 00:00:01,250' in srt
