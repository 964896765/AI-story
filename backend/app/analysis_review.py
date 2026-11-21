"""Immutable source-time review snapshots and explicit adoption into P4."""
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field, model_validator
from sqlalchemy import select, func
from sqlalchemy.orm import defer

from .analysis_engine import micros
from .analysis_service import artifact_intact, fingerprint
from .creative import create_entity, pack, require, version_ref
from .db import session
from .models import AnalysisRevision, Asset, MediaAnalysis, Project, Task
from .perception import align_to_shots, available_capabilities
from .story_schemas import Strict

router = APIRouter(prefix='/api/analysis', tags=['media-analysis-review'])


class TimedEvidence(Strict):
    start_us: int = Field(ge=0, le=345_600_000_000)
    end_us: int = Field(gt=0, le=345_600_000_000)
    kind: Literal['transcript', 'screen_text', 'speaker', 'observation']
    text: str = Field(min_length=1, max_length=2000)

    @model_validator(mode='after')
    def duration(self):
        if self.end_us <= self.start_us or not self.text.strip():
            raise ValueError('证据需要正文及有效时间范围')
        return self


class Candidate(Strict):
    kind: Literal['character', 'scene']
    title: str = Field(min_length=1, max_length=200, pattern=r'.*\S.*')
    description: str = Field(default='', max_length=4000)
    task_id: str
    artifact: int = Field(ge=0, le=239)
    fixed_version_id: str | None = None


class RevisionInput(Strict):
    expected_version: int = Field(ge=0)
    result_task_ids: list[str] = Field(min_length=1, max_length=20)
    cuts_us: list[int] | None = Field(default=None, max_length=239)
    evidence: list[TimedEvidence] = Field(default_factory=list, max_length=300)
    candidates: list[Candidate] = Field(default_factory=list, max_length=50)
    note: str = Field(min_length=1, max_length=4000, pattern=r'.*\S.*')
    idempotency_key: str = Field(min_length=1, max_length=64)


class AdoptInput(Strict):
    kind: Literal['character', 'scene', 'script']
    candidate: int | None = Field(default=None, ge=0, le=49)
    title: str = Field(min_length=1, max_length=200, pattern=r'.*\S.*')
    body: str = Field(default='', max_length=100000)
    note: str = Field(min_length=1, max_length=4000, pattern=r'.*\S.*')
    idempotency_key: str = Field(min_length=1, max_length=64)


def public(row, *, detail=True):
    return {'id': row.id, 'asset_id': row.asset_id, 'number': row.number, 'content_hash': row.content_hash,
            'created_at': row.created_at, 'payload': row.payload if detail else None}


@router.get('/capabilities')
def capabilities():
    return available_capabilities()


@router.get('/assets/{asset_id}/revisions')
def revisions(asset_id: str, db=Depends(session)):
    require(db, Asset, asset_id)
    return [public(row, detail=False) for row in db.scalars(select(AnalysisRevision)
        .options(defer(AnalysisRevision.payload)).where(AnalysisRevision.asset_id == asset_id)
        .order_by(AnalysisRevision.number.desc()).limit(100))]


@router.get('/revisions/{revision_id}')
def revision(revision_id: str, db=Depends(session)):
    return public(require(db, AnalysisRevision, revision_id))


def shot_timeline(detected, cuts):
    if cuts is None:
        return [{**s, 'origin': 'detected'} for s in detected]
    if not detected:
        raise HTTPException(422, '修订切点前须完成自动切镜')
    start, end = detected[0]['start_us'], detected[-1]['end_us']
    points = [start, *cuts, end]
    if any(b-a < 1_000 for a, b in zip(points, points[1:])):
        raise HTTPException(422, '切点必须有序、位于视频内且间隔至少 1 毫秒')
    return [{'start_us': a, 'end_us': b, 'origin': 'reviewed', 'score': None,
             'artifact': next((shot['artifact'] for shot in detected if a <= shot['start_us'] < b), None)}
            for a, b in zip(points, points[1:])]


@router.post('/assets/{asset_id}/revisions', status_code=201)
def create_revision(asset_id: str, body: RevisionInput, db=Depends(session)):
    asset = db.scalar(select(Asset).where(Asset.id == asset_id).with_for_update())
    if asset is None:
        raise HTTPException(404, '素材不存在')
    input_hash = fingerprint(body.model_dump(exclude={'idempotency_key'}))
    existing = db.scalar(select(AnalysisRevision).where(AnalysisRevision.asset_id == asset_id,
                         AnalysisRevision.request_key == body.idempotency_key))
    if existing:
        if existing.input_hash != input_hash:
            raise HTTPException(409, '审核请求键已用于其他内容')
        return public(existing)
    latest = db.scalar(select(func.max(AnalysisRevision.number)).where(AnalysisRevision.asset_id == asset_id)) or 0
    if latest != body.expected_version:
        raise HTTPException(409, '已有较新的审核快照，请重新打开后再保存')
    if len(set(body.result_task_ids)) != len(body.result_task_ids):
        raise HTTPException(422, '证据任务不可重复')
    results = {}
    for task_id in body.result_task_ids:
        task = require(db, Task, task_id)
        if task.asset_id != asset.id or task.project_id != asset.project_id or (
            task.input_snapshot.get('video', {}).get('sha256') != asset.sha256
        ):
            raise HTTPException(422, '解析证据须来自同一素材及原始哈希')
        results[task_id] = require(db, MediaAnalysis, task_id)
    scenes = [row for row in results.values() if row.payload['operation'] == 'scenes']
    if len(scenes) > 1:
        raise HTTPException(422, '一次审核仅选择一份自动切镜时间轴')
    shots = shot_timeline(scenes[0].payload['shots'] if scenes else [], body.cuts_us)
    duration_candidates = [shot['end_us'] for shot in shots]
    subtitles = []
    ocr_samples = []
    for task_id, row in results.items():
        media = row.payload.get('media', {})
        duration = media.get('format', {}).get('duration')
        if (converted := micros(duration)) is not None:
            duration_candidates.append(converted)
        if row.payload.get('duration_us'):
            duration_candidates.append(row.payload['duration_us'])
        for frame in row.payload.get('ocr', {}).get('frames', []):
            if frame['text']:
                time = frame['time_us']
                ocr_samples.append({'start_us': time, 'end_us': time+1, 'artifact': frame['artifact'],
                                    'text': frame['text'], 'task_id': task_id, 'origin': 'ocr_sample'})
        for track in row.payload.get('subtitle_tracks', []):
            if len(subtitles) + len(track['cues']) > 20000:
                raise HTTPException(422, '单个快照最多对齐 20000 条字幕，请选较少轨道')
            for number, cue in enumerate(track['cues']):
                duration_candidates.append(cue['end_us'])
                origin = 'hard_subtitle_ocr' if track['status'] == 'ocr_estimated' else 'soft_subtitle'
                subtitles.append({'start_us': cue['start_us'], 'end_us': cue['end_us'],
                                  'origin': origin, 'task_id': task_id,
                                  'stream_index': track['stream_index'], 'cue_number': number})
    candidates = []
    for candidate in body.candidates:
        row = results.get(candidate.task_id)
        if not row or candidate.artifact >= len(row.payload['artifacts']):
            raise HTTPException(422, '候选必须引用此快照中已验证的关键帧')
        entry = row.payload['artifacts'][candidate.artifact]
        if entry['role'] not in ('frame', 'shot_frame'):
            raise HTTPException(422, '候选参考只接受视频抽帧')
        if candidate.fixed_version_id:
            version_ref(db, asset.project_id, candidate.fixed_version_id, {candidate.kind})
        candidates.append({**candidate.model_dump(), 'origin': 'human', 'time_us': entry['time_us']})
    end = max(duration_candidates, default=0)
    items = [item.model_dump() | {'origin': 'human'} for item in body.evidence]
    if any(item['end_us'] > end for item in items):
        raise HTTPException(422, '证据时段超出已验证范围，请先完成流清单或切镜')
    payload = {'source_sha256': asset.sha256, 'result_task_ids': body.result_task_ids,
               'scene_task_id': scenes[0].task_id if scenes else None, 'cuts_us': body.cuts_us,
               'shots': shots, 'evidence': align_to_shots(items, shots), 'subtitle_cues': align_to_shots(subtitles, shots),
               'candidates': candidates, 'note': body.note, 'duration_us': end, 'origin': 'human_review'}
    if ocr_samples:
        payload['ocr_samples'] = align_to_shots(ocr_samples, shots)
    if len(json.dumps(payload, ensure_ascii=False).encode()) > 8 * 1024**2:
        raise HTTPException(422, '审核快照超过 8 MiB，请选较少字幕与证据')
    row = AnalysisRevision(asset_id=asset.id, number=latest+1, request_key=body.idempotency_key,
                           input_hash=input_hash, content_hash=fingerprint(payload), payload=payload)
    db.add(row)
    db.commit()
    return public(row)


@router.post('/revisions/{revision_id}/adopt', status_code=201)
def adopt(revision_id: str, body: AdoptInput, db=Depends(session)):
    snapshot = require(db, AnalysisRevision, revision_id)
    source = require(db, Asset, snapshot.asset_id)
    db.scalar(select(Project).where(Project.id == source.project_id).with_for_update())
    candidates = snapshot.payload['candidates']
    provenance = {'analysis_revision_id': snapshot.id, 'analysis_sha256': snapshot.content_hash,
                  'source_asset_id': source.id, 'origin': 'human_review'}
    if body.kind == 'script':
        if body.candidate is not None or not body.body.strip():
            raise HTTPException(422, '审核稿需要人工确认的正文')
        content = {'body': body.body, 'summary': snapshot.payload['note'],
                   'character_version_ids': list(dict.fromkeys(c['fixed_version_id'] for c in candidates
                            if c['kind'] == 'character' and c['fixed_version_id'])),
                   'scene_version_ids': list(dict.fromkeys(c['fixed_version_id'] for c in candidates
                            if c['kind'] == 'scene' and c['fixed_version_id']))}
    else:
        if body.candidate is None or body.candidate >= len(candidates):
            raise HTTPException(422, '请选择已审核的关键帧候选')
        candidate = candidates[body.candidate]
        if candidate['kind'] != body.kind or candidate['fixed_version_id']:
            raise HTTPException(422, '该候选类型不符或已关联固定版本')
        entry = require(db, MediaAnalysis, candidate['task_id']).payload['artifacts'][candidate['artifact']]
        if not artifact_intact(entry):
            raise HTTPException(409, '关键帧已缺失或损坏，请重新解析')
        asset = db.scalar(select(Asset).where(Asset.storage_key == entry['storage_key']))
        if not asset:
            asset = Asset(project_id=source.project_id, name=entry['name'], storage_key=entry['storage_key'],
                          sha256=entry['sha256'], size_bytes=entry['size_bytes'],
                          authorization=source.authorization, media_info={'derived_from_asset': source.id,
                          'analysis_task_id': candidate['task_id'], 'time_us': entry['time_us']})
            db.add(asset)
            db.flush()
        content = {'description': candidate['description'], 'reference_asset_ids': [asset.id]}
        provenance['candidate_index'] = body.candidate
    key = 'analysis-adopt:' + fingerprint({'snapshot': snapshot.id, 'key': body.idempotency_key})[:60]
    entity, version = create_entity(db, source.project_id, body.kind, body.title, content, key, body.note, provenance)
    if version.provenance != provenance:
        raise HTTPException(409, '采纳请求键已用于其他候选')
    db.commit()
    return pack(db, entity, version)
