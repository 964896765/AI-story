import asyncio
import io
import shutil
import subprocess
import pytest
from fastapi.testclient import TestClient
from starlette.datastructures import UploadFile
from app import storage
from app.media import probe
from app.main import app

def test_path_escape_and_symlink(tmp_path):
    with pytest.raises(ValueError):
        storage.resolve_key('../escape', tmp_path)
    with pytest.raises(ValueError):
        storage.resolve_key(str(tmp_path.parent / 'outside'), tmp_path)
    assert storage.resolve_key('originals/a.mp4', tmp_path).is_relative_to(tmp_path)

def test_upload_checksum_and_size_cleanup(tmp_path, monkeypatch):
    monkeypatch.setattr(storage, 'resolve_key', lambda key: tmp_path / key)
    digest, size = asyncio.run(storage.save_upload(UploadFile(io.BytesIO(b'abc')), 'video'))
    assert size == 3 and digest == 'ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad'
    with pytest.raises(FileExistsError):
        asyncio.run(storage.save_upload(UploadFile(io.BytesIO(b'new')), 'video'))
    assert (tmp_path / 'video').read_bytes() == b'abc'
    monkeypatch.setattr(storage, 'MAX_UPLOAD', 2)
    with pytest.raises(ValueError):
        asyncio.run(storage.save_upload(UploadFile(io.BytesIO(b'abc')), 'oversize'))
    assert not (tmp_path / 'oversize').exists()

def test_real_video_probe(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg required')
    video = tmp_path / 'owned-fixture.mp4'
    subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'testsrc2=size=320x240:rate=12', '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '1', '-c:v', 'mpeg4', '-c:a', 'aac', str(video)], check=True, timeout=30)
    data = probe(video)
    assert {s['codec_type'] for s in data['streams']} == {'video', 'audio'}
    assert float(data['format']['duration']) >= 1

def test_reject_invalid_media(tmp_path):
    media = tmp_path / 'invalid.mp4'
    media.write_bytes(b'not a video')
    with pytest.raises(ValueError):
        probe(media)

def test_host_and_origin_protection():
    client = TestClient(app)
    assert client.get('/api/health', headers={'host':'evil.example'}).status_code == 400
    assert client.post('/api/projects', headers={'origin':'https://evil.example'}, json={'name':'bad'}).status_code == 403

def test_project_input_validation():
    from app.main import ProjectInput
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ProjectInput(name='   ')
    with pytest.raises(ValidationError):
        ProjectInput(name='demo', budget_cents=-1)
