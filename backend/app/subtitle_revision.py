"""Save reviewed subtitles as immutable project media."""
import hashlib
import os
from pathlib import Path
import re
from tempfile import NamedTemporaryFile

from fastapi import HTTPException
from pydantic import Field
from sqlalchemy import func, select

from . import storage
from .analysis_engine import format_srt, micros, parse_cues
from .analysis_service import artifact_intact, fingerprint
from .models import Asset, MediaAnalysis
from .story_schemas import Strict


class CueEdit(Strict):
    start_ms: int = Field(ge=0, le=86_400_000, strict=True)
    end_ms: int = Field(ge=1, le=86_400_000, strict=True)
    text: str = Field(max_length=4000)


class SubtitleRevisionInput(Strict):
    # Only the changed rows are submitted. A null row removes that source cue.
    edits: dict[int, CueEdit | None] = Field(default_factory=dict, max_length=10_000)
    base_revision_id: str | None = Field(default=None, min_length=1, max_length=36)


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
    content = format_srt((start, end, text) for start, end, _, text in reviewed)
    data = content.encode('utf-8')
    if len(data) > 2 * 1024**2:
        raise HTTPException(422, '校对后的 SRT 超过 2 MiB')
    return data, len(reviewed)


def verified_track(db, task, source, stream_index):
    row = db.get(MediaAnalysis, task.id)
    if not row or task.status != 'succeeded' or row.payload['operation'] not in ('subtitles', 'hard_subtitles', 'asr'):
        raise HTTPException(404, '此任务没有已验证的字幕结果')
    if task.input_snapshot.get('video', {}).get('sha256') != source.sha256:
        raise HTTPException(409, '素材哈希与解析时不一致，请重新解析')
    track = next((item for item in row.payload['subtitle_tracks'] if item['stream_index'] == stream_index), None)
    if not track or track['status'] not in ('extracted', 'ocr_estimated', 'asr_estimated') or not track['cues']:
        raise HTTPException(404, '此轨道没有可校对的字幕')
    return row, track


def subtitle_provenance(payload, track):
    if track['status'] in ('extracted', 'asr_estimated'):
        artifact = payload['artifacts'][track['artifact']]
        if not artifact_intact(artifact):
            raise HTTPException(409, '提取的字幕文件缺失或校验失败，请重新提取')
        provenance = {'subtitle_source_sha256': artifact['sha256']}
        if track['status'] == 'asr_estimated':
            provenance.update(subtitle_origin='asr_estimated', speech=payload['speech'])
        return provenance
    artifacts = payload['artifacts']
    if not artifacts or not all(artifact_intact(entry) for entry in artifacts):
        raise HTTPException(409, '硬字幕采样帧缺失或校验失败，请重新识别')
    scan = payload['hard_subtitle_scan']
    return {'subtitle_origin': 'ocr_estimated', 'subtitle_scan': scan,
            'subtitle_evidence_sha256': fingerprint({
                'scan': scan, 'ocr': payload['ocr'], 'cues': track['cues'],
                'frame_hashes': [entry['sha256'] for entry in artifacts],
            })}


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


def read_revision(db, scope, revision_id):
    asset = db.scalar(select(Asset).where(*scope, Asset.id == revision_id))
    if asset is None:
        raise HTTPException(404, '此字幕版本不属于当前素材、任务或轨道')
    try:
        with storage.resolve_key(asset.storage_key).open('rb') as file:
            data = file.read(2*1024**2+1)
        if len(data) > 2*1024**2 or len(data) != asset.size_bytes or hashlib.sha256(data).hexdigest() != asset.sha256:
            raise ValueError('字幕版本哈希不匹配')
        cues = parse_cues(data.decode('utf-8-sig'))
    except (ValueError, OSError) as exc:
        raise HTTPException(409, '已保存的字幕文件缺失或校验失败') from exc
    return asset, cues


def revision_detail(db, source, task, stream_index, revision_id):
    verified_track(db, task, source, stream_index)
    _, scope = revision_scope(source, task, stream_index)
    asset, cues = read_revision(db, scope, revision_id)
    return {'id': asset.id, 'version': asset.version, 'sha256': asset.sha256, 'cues': cues,
            'parent_revision_id': asset.media_info.get('subtitle_parent_asset_id')}


def save_revision(db, source, task, stream_index, body):
    row, track = verified_track(db, task, source, stream_index)
    prefix, scope = revision_scope(source, task, stream_index)
    cues = track['cues']
    lineage = {}
    if body.base_revision_id is not None:
        base, cues = read_revision(db, scope, body.base_revision_id)
        lineage = {'subtitle_parent_asset_id': base.id, 'subtitle_parent_sha256': base.sha256}
    duration = row.payload.get('duration_us') or micros(source.media_info.get('format', {}).get('duration'))
    data, count = compile_srt(cues, body.edits, duration if duration and duration > 0 else None)
    digest = hashlib.sha256(data).hexdigest()
    key = prefix + digest + '.srt'
    existing = db.scalar(select(Asset).where(*scope, Asset.storage_key == key))
    if existing:
        if not artifact_intact({'storage_key': key, 'size_bytes': existing.size_bytes, 'sha256': existing.sha256}):
            raise HTTPException(409, '已保存的字幕文件缺失或校验失败')
        return existing
    provenance = subtitle_provenance(row.payload, track)
    version = (db.scalar(select(func.max(Asset.version)).where(*scope)) or 0) + 1
    publish_srt(key, data, digest)
    label = {'ocr_estimated': '硬字幕 OCR', 'asr_estimated': '语音转写'}.get(track['status'], '字幕流')
    name = f'{Path(source.name).stem[:220]} · {label} {stream_index} v{version}.srt'
    asset = Asset(project_id=source.project_id, name=name, storage_key=key, sha256=digest,
                  size_bytes=len(data), authorization=source.authorization, version=version,
                  media_info={'origin': 'subtitle_review', 'derived_from_asset': source.id,
                              'source_sha256': source.sha256, 'analysis_task_id': task.id,
                              'subtitle_stream': stream_index, 'cue_count': count, **provenance, **lineage})
    db.add(asset)
    db.commit()
    return asset
