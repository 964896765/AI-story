"""Persist analysis through the existing task ownership and retry flow."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import select

from . import storage
from .analysis_engine import ALGORITHM, analyze, tools_version
from .analysis_schemas import AnalysisOptions, OCR_OPERATIONS
from .models import MediaAnalysis
from .perception_asr import recognizer as speech_recognizer
from .perception_ocr import recognizer
from .render import file_hash


def fingerprint(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def artifact_intact(artifact, update=None):
    try:
        path = storage.resolve_key(artifact['storage_key'])
        return path.stat().st_size == artifact['size_bytes'] and file_hash(path, update) == artifact['sha256']
    except (OSError, ValueError):
        return False


def execute_analysis(task_id, attempt, parameters, input_snapshot, update, factory):
    options = AnalysisOptions.model_validate(parameters)
    source = input_snapshot['video']
    path = storage.resolve_key(source['storage_key'])
    update('analysis_hash', 3)
    actual = file_hash(path, lambda *_: update('analysis_hash', 3))
    if actual != source['sha256']:
        raise ValueError('源文件与导入时的 SHA-256 不一致，请重新导入未修改的素材')
    adapter = None
    if options.operation in OCR_OPERATIONS:
        pinned = input_snapshot.get('ocr')
        adapter = recognizer(pinned['language'] if pinned else options.ocr_language)
        if pinned and adapter != pinned:
            raise ValueError('本机 OCR 识别器环境已变更，请重新提交解析')
        options = options.model_copy(update={'ocr_language': adapter['language']})
    elif options.operation == 'asr':
        pinned = input_snapshot.get('asr')
        adapter = speech_recognizer(pinned['language'] if pinned else options.asr_language)
        if pinned != adapter:
            raise ValueError('本机语音识别器环境已变更，请重新提交转写')
        options = options.model_copy(update={'asr_language': adapter['language']})
    inputs = {'algorithm': ALGORITHM, 'tools': tools_version(), 'source': actual,
              'asset_id': source['id'], 'options': options.signature_parameters()}
    if adapter:
        inputs['recognizer'] = adapter
    signature = fingerprint(inputs)
    with factory() as db:
        cached = db.scalars(select(MediaAnalysis).where(MediaAnalysis.signature == signature)
                            .order_by(MediaAnalysis.created_at.desc()).limit(5)).all()
    for candidate in cached:
        if all(artifact_intact(a, lambda *_: update('analysis_cache', 18)) for a in candidate.payload['artifacts']):
            update('analysis_cache', 96)
            return signature, {**candidate.payload, 'reused_from_task_id': candidate.task_id}
    work = storage.resolve_key(f'tmp/{task_id}/{attempt}')
    payload = analyze(path, work, options, update)
    # Keep output inaccessible by HTTP until the Worker commits the result and task together.
    update('analysis_publish', 97)
    if payload['artifacts']:
        prefix = f'analysis/{task_id}/{attempt}'
        destination = storage.resolve_key(prefix)
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise FileExistsError('解析输出目录已存在')
        (work / 'files').rename(destination)
        for artifact in payload['artifacts']:
            artifact['storage_key'] = f"{prefix}/{artifact['name']}"
    return signature, payload


def analysis_public(row):
    return {'task_id': row.task_id, 'signature': row.signature, 'created_at': row.created_at,
            **row.payload, 'artifacts': [
                {k: v for k, v in artifact.items() if k != 'storage_key'} | {'id': i}
                for i, artifact in enumerate(row.payload['artifacts'])
            ]}
