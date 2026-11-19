"""Check continuity and approve a fixed series plan through the creative version chain."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from sqlalchemy import select

from .creative import append_version, pack, require, validate_content, version_ref
from .db import session
from .models import StoryEntity, StoryVersion
from .story_schemas import Strict

router = APIRouter(prefix='/api/series', tags=['series-planning'])


class Approval(Strict):
    expected_version: int = Field(ge=1)
    note: str = Field(min_length=1, max_length=4000, pattern=r'.*\S.*')
    idempotency_key: str = Field(min_length=1, max_length=70)


def series_report(db, entity, version):
    content = version.content
    issues, episodes = [], []
    cache = {}

    def issue(code, episode, detail, severity='error', shot=None):
        issues.append({'code':code, 'episode':episode, 'detail':detail, 'severity':severity, 'shot':shot})

    def get(key, kind):
        if key not in cache:
            cache[key] = version_ref(db,entity.project_id,key,{kind})
        return cache[key]

    def boundary(states, number, edge):
        indexed = {}
        for state in states:
            character, _ = get(state['character_version_id'],'character')
            if character.id in indexed:
                issue('duplicate_boundary_state',number, f'{edge}重复登记同一角色的状态')
            indexed[character.id] = state
        return indexed

    previous = {}
    script_id = content['script_version_id']
    seen_shots = set()
    for index, block in enumerate(content['episodes'],1):
        _, episode = get(block['episode_version_id'],'episode')
        storyboard, board_version = get(block['storyboard_version_id'],'storyboard')
        number = episode.content['number']
        if number != index:
            issue('episode_order',number,f'此计划位置要求第 {index} 集')
        if episode.content.get('source_version_id') != script_id:
            issue('episode_source',number,'分集必须引用计划固定的总剧本版本')
        if board_version.content['source_version_id'] != episode.id:
            issue('storyboard_source',number,'分镜必须直接引用本集固定版本')
        opener = boundary(block['opener'],number,'开场')
        closer = boundary(block['closer'],number,'收尾')
        if index > 1:
            carried = previous.keys() | opener.keys()
            for character_id in sorted(carried):
                before = previous.get(character_id)
                after = opener.get(character_id)
                if before != after:
                    name = get((before or after)['character_version_id'],'character')[1].title
                    bridged = bool(block['bridge_note'].strip())
                    issue('boundary_change',number,f'角色「{name}」状态与上一集收尾不同',
                          severity='warning' if bridged else 'error')
        previous = closer
        shots = []
        planned_ms = 0
        for shot in sorted(board_version.content['shots'],key=lambda item:item['number']):
            shot_id = shot.get('shot_id') or f"{storyboard.id}-{shot['number']}"
            if shot_id in seen_shots:
                issue('duplicate_shot_id',number,'稳定镜头 ID 已存在于本季其他镜头',shot=shot_id)
            seen_shots.add(shot_id)
            length = round(shot['planned_duration']*1000)
            if shot.get('dialogue') and (not shot.get('speaker_version_id') or not shot.get('dialogue_ms')):
                issue('dialogue_unmeasured',number,'对白缺少固定说话者或人工估计时长','warning',shot_id)
            shots.append({'shot_id':shot_id, 'number':shot['number'], 'start_ms':planned_ms,
                          'duration_ms':length, 'description':shot['description'][:300],
                          'strategy':shot.get('strategy','manual'), 'scene_version_id':shot.get('scene_version_id'),
                          'character_version_ids':shot['character_version_ids']})
            planned_ms += length
        target = block['target_duration_ms']
        if abs(planned_ms-target)>max(250,round(target*0.03)):
            issue('duration_mismatch',number,f'分镜合计 {planned_ms} ms，目标 {target} ms')
        episodes.append({'number':number,'title':episode.title,'episode_version_id':episode.id,
                         'storyboard_version_id':board_version.id,'planned_duration_ms':planned_ms,
                         'target_duration_ms':target,'shots':shots,'bridge_note':block['bridge_note']})
    for thread in content['threads']:
        setup,payoff=thread['setup_episode'],thread['payoff_episode']
        if setup>len(episodes) or (payoff is not None and not setup<=payoff<=len(episodes)):
            issue('thread_order',setup,f'伏笔「{thread["label"]}」的埋设或回收集数超出有效顺序')
        elif payoff is None:
            issue('open_thread',setup,f'伏笔「{thread["label"]}」尚未指定回收集','warning')
    should_block = any(item['severity']=='error' for item in issues)
    return {'version_id':version.id,'rule_version':'continuity-v1','analysis_kind':'deterministic',
            'approved':bool(version.provenance.get('series_approved')),
            'ready_for_review':not should_block,'episodes':episodes,'issues':issues}


@router.get('/versions/{version_id}/continuity')
def continuity(version_id: str, db=Depends(session)):
    version = require(db,StoryVersion,version_id)
    entity = require(db,StoryEntity,version.entity_id)
    if entity.kind!='story_bible':
        raise HTTPException(422,'只有故事圣经可以检查连续性')
    return series_report(db,entity,version)


@router.post('/entities/{entity_id}/approve', status_code=201)
def approve(entity_id: str, body: Approval, db=Depends(session)):
    entity = db.scalar(select(StoryEntity).where(StoryEntity.id==entity_id).with_for_update())
    if entity is None or entity.kind!='story_bible':
        raise HTTPException(404,'故事圣经不存在')
    key = 'series-approve:'+body.idempotency_key
    previous = db.scalar(select(StoryVersion).where(StoryVersion.entity_id==entity.id, StoryVersion.request_key==key))
    if previous:
        if previous.note!=body.note or previous.provenance.get('reviewed_version')!=body.expected_version:
            raise HTTPException(409,'审核请求键已用于其他内容')
        return pack(db,entity,previous)
    if entity.current_version!=body.expected_version:
        raise HTTPException(409,'工作稿已变化，请重新读取后审核')
    source = db.scalar(select(StoryVersion).where(StoryVersion.entity_id==entity.id,
                    StoryVersion.number==entity.current_version))
    report = series_report(db,entity,source)
    if not report['ready_for_review']:
        raise HTTPException(422,{'message':'计划仍有阻断项','issues':report['issues']})
    normalized, refs = validate_content(db,entity.project_id,'story_bible',source.content)
    entity.current_version += 1
    approved = append_version(db,entity,source.title,normalized,refs,key,body.note,
        {'series_approved':True,'reviewed_version':source.number,'reviewed_version_id':source.id,
         'review_rule_version':report['rule_version'],'warning_count':len(report['issues'])})
    db.commit()
    return pack(db,entity,approved)
