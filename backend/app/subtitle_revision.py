"""Save reviewed soft subtitles as immutable project media."""
import hashlib
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import func, select

from . import storage
from .analysis_engine import micros
from .analysis_service import artifact_intact
from .models import Asset, MediaAnalysis
from .story_schemas import Strict


class CueEdit(Strict):
    start_ms: int = Field(ge=0, le=86_400_000, strict=True)
    end_ms: int = Field(ge=1, le=86_400_000, strict=True)
    text: str = Field(max_length=4000)


class SubtitleRevisionInput(Strict):
    # Only the changed rows are submitted. A null row removes that source cue.
    edits: dict[int, CueEdit | None] = Field(default_factory=dict, max_length=10_000)


def srt_time(ms: int) -> str:
    seconds, remainder = divmod(ms, 1000)
    return f'{seconds//3600:02d}:{seconds//60%60:02d}:{seconds%60:02d},{remainder:03d}'


def compile_srt(cues, edits, duration_us):
    if any(not 0 <= index < len(cues) for index in edits):
        raise HTTPException(422, '字幕行号不在此轨道中')
    reviewed = []
    for index, cue in enumerate(cues):
        if index in edits:
            edit = edits[index]
            if edit is None:
                continue
            start, end, text = edit.start_ms, edit.end_ms, edit.text
        else:
            start, end, text = cue['start_us']//1000, cue['end_us']//1000, cue['text']
        text = text.replace('\r\n', '\n').replace('\r', '\n').strip()
        if not text or re.search(r'\n[ \t]*\n|[\x00-\x08\x0b-\x1f\x7f\ud800-\udfff]', text):
            raise HTTPException(422, f'第 {index + 1} 条字幕为空或含空行及无效字符')
        if not 0 <= start < end <= 86_400_000 or (
                duration_us and end > (duration_us+999)//1000):
            raise HTTPException(422, f'第 {index + 1} 条字幕时间无效或超出源媒体时长')
        reviewed.append((start, end, index+1, text))
    if not reviewed:
        raise HTTPException(422, '至少保留一条字幕')
    reviewed.sort()
    for earlier, later in zip(reviewed, reviewed[1:]):
        if earlier[1] > later[0]:
            raise HTTPException(422, f'第 {earlier[2]} 条与第 {later[2]} 条字幕时间重叠')
    content = '\n\n'.join(f'{i}\n{srt_time(start)} --> {srt_time(end)}\n{text}'
                          for i, (start, end, _, text) in enumerate(reviewed, 1)) + '\n'
    data = content.encode('utf-8')
    if len(data) > 2 * 1024**2:
        raise HTTPException(422, '校对后的 SRT 超过 2 MiB')
    return data, len(reviewed)


def verified_track(db, task, source, stream_index):
    row = db.get(MediaAnalysis, task.id)
    if not row or task.status != 'succeeded' or row.payload['operation'] != 'subtitles':
        raise HTTPException(404, '此任务没有已验证的字幕结果')
    if task.input_snapshot.get('video', {}).get('sha256') != source.sha256:
        raise HTTPException(409, '素材哈希与解析时不一致，请重新解析')
    track = next((item for item in row.payload['subtitle_tracks'] if item['stream_index'] == stream_index), None)
    if not track or track['status'] != 'extracted' or not track['cues']:
        raise HTTPException(404, '此轨道没有可校对的软字幕')
    return row, track


def publish_srt(key, data, digest):
    target = storage.resolve_key(key)
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        with NamedTemporaryFile(dir=target.parent, suffix='.tmp', delete=False) as file:
            temporary = Path(file.name)
            try:
                file.write(data)
                file.flush()
                os.fsync(file.fileno())
                file.close()
                os.link(temporary, target)
            finally:
                file.close()
                temporary.unlink(missing_ok=True)
    # A process can stop after publishing the file and before committing its record.
    if not artifact_intact({'storage_key': key, 'size_bytes': len(data), 'sha256': digest}):
        raise HTTPException(409, '保存的字幕文件校验失败')


def revision_scope(source, task, stream_index):
    prefix = f'analysis/{task.id}/subtitles/{stream_index}/'
    return prefix, (Asset.project_id == source.project_id, Asset.storage_key.startswith(prefix, autoescape=True))


def revision_list(db, source, task, stream_index):
    verified_track(db, task, source, stream_index)
    _, scope = revision_scope(source, task, stream_index)
    return db.scalars(select(Asset).where(*scope).order_by(Asset.version.desc()).limit(20)).all()


def save_revision(db, source, task, stream_index, edits):
    row, track = verified_track(db, task, source, stream_index)
    duration = row.payload.get('duration_us') or micros(source.media_info.get('format', {}).get('duration'))
    data, count = compile_srt(track['cues'], edits, duration if duration and duration > 0 else None)
    digest = hashlib.sha256(data).hexdigest()
    prefix, scope = revision_scope(source, task, stream_index)
    key = prefix + digest + '.srt'
    existing = db.scalar(select(Asset).where(*scope, Asset.storage_key == key))
    if existing:
        if not artifact_intact({'storage_key': key, 'size_bytes': existing.size_bytes, 'sha256': existing.sha256}):
            raise HTTPException(409, '已保存的字幕文件缺失或校验失败')
        return existing
    artifact = row.payload['artifacts'][track['artifact']]
    if not artifact_intact(artifact):
        raise HTTPException(409, '提取的字幕文件缺失或校验失败，请重新提取')
    version = (db.scalar(select(func.max(Asset.version)).where(*scope)) or 0) + 1
    publish_srt(key, data, digest)
    name = f'{Path(source.name).stem[:220]} · 字幕流 {stream_index} v{version}.srt'
    asset = Asset(project_id=source.project_id, name=name, storage_key=key, sha256=digest,
                  size_bytes=len(data), authorization=source.authorization, version=version,
                  media_info={'origin': 'subtitle_review', 'derived_from_asset': source.id,
                              'source_sha256': source.sha256, 'analysis_task_id': task.id,
                              'subtitle_stream': stream_index, 'subtitle_source_sha256': artifact['sha256'],
                              'cue_count': count})
    db.add(asset)
    db.commit()
    return asset
