"""Bounded local tools for the Agent role registry."""

from math import ceil
import re
from fastapi import HTTPException

from . import storage
from .analysis_service import fingerprint
from .creative import digest, split_units, version_ref
from .production_specs import approval_spec, task_fields
from .render import file_hash
from .series import series_report
from .story_schemas import Timeline
from .timeline import render_snapshot

RULE_VERSION = 'local-agent-tools-v1'
WORKFLOWS = {
    'story': ('director','analysis','writer'),
    'preflight': ('director','art','storyboard','shot_review','postproduction'),
}
ROLES = {
    'director': ('总导演','目标与固定制作规格','制作委托与角色顺序','读取固定规格'),
    'analysis': ('剧情分析','固定原稿','原稿结构统计与开头摘录','读取原稿'),
    'writer': ('编剧','原稿与结构检查','按字符整理的分集草案','读取原稿和已完成的上一步'),
    'art': ('美术设计','批准故事圣经','角色、场景及风格引用清单','读取固定参考和合同'),
    'storyboard': ('分镜导演','批准计划与镜头合同','分集时长与镜头分布','读取分镜与连续性摘要'),
    'shot_review': ('镜头审核','固定镜头合同与连续性报告','Guardian 规则、告警和证据依据','读取 Guardian 报告'),
    'postproduction': ('后期制作','固定时间轴和素材快照','渲染前检查与文件哈希核验','只读校验本机素材'),
}


def version_record(version):
    return {'id':version.id,'version':version.number,'sha256':version.content_hash,'title':version.title}


def checked_version(db, project_id, snapshot):
    entity, version = version_ref(db,project_id,snapshot['id'])
    if (version_record(version)!=snapshot
        or digest(entity.kind,version.title,version.content)!=snapshot['sha256']):
        raise ValueError('固定创作版本的内容校验失败')
    return entity,version


def outline(text, count):
    chunks = split_units(text,max(100,ceil(len(text)/count)))
    return {'kind':'rule_outline','requires_human_edit':True,'requested_episodes':count,
            'available_chunks':len(chunks),'listed_chunks':min(len(chunks),count),
            'episodes':[{'number':index,'source_excerpt':chunk[:350],'source_length':len(chunk)}
                        for index,chunk in enumerate(chunks[:count],1)]}


def frozen(db, project_id, request):
    """Prepare immutable refs using exactly the same render checks as the workbench."""
    spec = approval_spec(db,project_id,{'production_spec_version_id':request['production_spec_version_id']})
    inputs = {'rule_version':RULE_VERSION,**task_fields(spec)}
    if request['workflow']=='story':
        _, version = version_ref(db,project_id,request['source_version_id'],{'novel','script','episode'})
        declared = version.content.get('production_spec_version_id')
        if declared and declared!=spec['id']:
            raise HTTPException(422,'原稿已固定到另一制作规格版本')
        return {**inputs,'source':version_record(version)}
    _, plan = version_ref(db,project_id,request['series_version_id'],{'story_bible'})
    _, timeline = version_ref(db,project_id,request['timeline_version_id'],{'timeline'})
    if (not plan.provenance.get('guardian_manifest') or timeline.content['source_version_id']!=plan.id
        or any(item.content.get('production_spec_version_id')!=spec['id'] for item in (plan,timeline))):
        raise HTTPException(422,'预检须固定同一规格的已批准 Guardian 计划及其时间轴')
    source = render_snapshot(db,project_id,timeline,Timeline.model_validate(timeline.content))
    return {**inputs,'series':version_record(plan),'timeline':version_record(timeline),'assets':source['assets']}


def execute_role(db, run, role, previous, update):
    request, inputs = run.request, run.inputs
    settings = inputs['production_spec']['settings']
    if role=='director':
        return {'goal':request['goal'],'planned_episodes':settings['episode_count'],
                'target_duration_ms':settings['episode_duration_ms'],'style':settings['style'],
                'workflow':list(WORKFLOWS[request['workflow']]),'external_budget_cents':0}
    if request['workflow']=='story':
        _, version = checked_version(db,run.project_id,inputs['source'])
        text = version.content.get('text') or version.content.get('body') or ''
        if not text.strip():
            raise ValueError('固定原稿没有可分析的正文')
        if role=='analysis':
            groups = [part for part in re.split(r'\n\s*\n',text) if part.strip()]
            return {'kind':'text_structure','characters':len(text),'paragraphs':len(groups),
                    'opening_excerpt':groups[0][:350]}
        document = outline(text,settings['episode_count'])
        return {**document,'analysis_sha256':previous['result_sha256']}

    entity, plan = checked_version(db,run.project_id,inputs['series'])
    if role=='art':
        canon = plan.content['guardian']
        return {'characters':canon['character_version_ids'],'scenes':canon['scene_version_ids'],
                'style':canon['style'],'registered_props':sorted(canon['props'])}
    if role in ('storyboard','shot_review'):
        report = series_report(db,entity,plan)
        if role=='storyboard':
            return {'episodes':[{'number':episode['number'],'shot_count':len(episode['shots']),
                    'duration_ms':episode['planned_duration_ms'],'target_ms':episode['target_duration_ms']}
                    for episode in report['episodes']]}
        if not report['ready_for_review'] or report['guardian']['contracts']!=plan.provenance['guardian_manifest']:
            raise ValueError('Guardian 规则或镜头合同与批准记录不符')
        return {'rule_version':report['rule_version'],'shot_count':report['guardian']['shot_count'],
                'issue_count':len(report['issues']),'findings':report['issues'][:20]}

    _, version = checked_version(db,run.project_id,inputs['timeline'])
    timeline = Timeline.model_validate(version.content)
    verify = render_snapshot(db,run.project_id,version,timeline)
    if fingerprint(verify['assets'])!=fingerprint(inputs['assets']):
        raise ValueError('时间轴素材快照已变化')
    for asset_id, metadata in inputs['assets'].items():
        path = storage.resolve_key(metadata['storage_key'])
        if not path.is_file() or file_hash(path,lambda *_:update('agent_verify_media',75))!=metadata['sha256']:
            raise ValueError(f'固定素材 {asset_id} 缺失或哈希不符')
    return {'profile':timeline.profile,'fps':timeline.frame_rate,'frames':timeline.frames,
            'verified_asset_count':len(inputs['assets']),'asset_ids':sorted(inputs['assets'])}
