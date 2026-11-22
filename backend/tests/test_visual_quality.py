from hashlib import sha256
import subprocess

import pytest

from app.analysis_engine import Commands
from app.visual_quality import FRAME_BYTES, inspect_frames, inspect_video


def test_visual_decoding_count_and_report_limit():
    with pytest.raises(ValueError, match='帧数不符'):
        inspect_frames(bytes(FRAME_BYTES), 2, 'digest')
    segment = bytes(FRAME_BYTES * 6) + bytes([100]) * FRAME_BYTES
    report = inspect_frames(segment * 15, 105, 'digest')
    assert report['checked_frames'] == 105 and report['black_frames'] == 90
    assert report['status'] == 'review'
    assert len(report['findings']) == 8 and report['omitted_findings'] == 7


@pytest.mark.parametrize('source,filters,status,code', [
    ('testsrc2', None, 'clear', None),
    ('color=black', None, 'blocked', 'black_output'),
    ('color=gray', None, 'review', 'low_motion'),
    ('testsrc2', "drawbox=c=black:t=fill:enable='between(t,0.5,0.95)'", 'review', 'black_segment'),
    ('color=black', 'drawbox=x=60:y=35:w=45:h=45:c=white:t=fill', 'review', 'low_motion'),
])
def test_real_visual_fixtures(tmp_path,source,filters,status,code):
    path = tmp_path / 'fixture.mp4'
    source = source + (':' if '=' in source else '=') + 's=192x108:r=24:d=2'
    argv = ['ffmpeg','-v','error','-f','lavfi','-i',source]
    if filters:
        argv.extend(['-vf',filters])
    argv.extend(['-c:v','libx264','-pix_fmt','yuv420p','-threads','1',str(path)])
    subprocess.run(argv,check=True,timeout=15,capture_output=True)
    digest = sha256(path.read_bytes()).hexdigest()
    result = inspect_video(Commands(tmp_path/'checked',lambda *_:None),path,48,digest)
    assert result['status']==status and result['output_sha256']==digest
    assert result['checked_frames']==48
    if code:
        issue, = [issue for issue in result['findings'] if issue['code']==code]
        assert issue['start_ms']==(500 if code=='black_segment' else 0)
        assert issue['end_ms']==(958 if code=='black_segment' else 2000)
        assert issue['severity']==('error' if code=='black_output' else 'warning')
    else:
        assert result['findings']==[]
