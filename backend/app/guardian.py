"""Validate declared canon and freeze per-shot production inputs."""
from fastapi import HTTPException
from sqlalchemy import select

from .analysis_service import fingerprint
from .models import Asset, StoryVersion


RULE_VERSION = 'guardian-contract-v1'
STATE_FIELDS = ('wardrobe_id', 'left_hand', 'right_hand', 'action', 'position')


class Guardian:
    def __init__(self, db, canon, get, issue, production_spec=None):
        self.db, self.canon, self.get, self.issue = db, canon, get, issue
        self.production_spec = production_spec
        self.characters = self.roster('character')
        self.scenes = self.roster('scene')
        self.images = {}
        self.previous = None
        self.contracts = {}
        for character in self.characters.values():
            if not character.content.get('identity') or not character.content.get('reference_asset_ids'):
                issue('identity_incomplete', 0, f'角色「{character.title}」需设置身份、服装及参考图')

    def roster(self, kind):
        roster, seen = {}, set()
        for key in self.canon[f'{kind}_version_ids']:
            entity, version = self.get(key, kind)
            if entity.id in seen:
                self.issue('duplicate_canon_version', 0, f'「{version.title}」在正史中只能固定一个版本')
            seen.add(entity.id)
            roster[key] = version
        return roster

    def check_roster(self, character_ids, scene_ids, issue):
        for kind, keys, approved in (('character', character_ids, self.characters), ('scene', scene_ids, self.scenes)):
            for key in dict.fromkeys(keys):
                if key not in approved:
                    issue(f'{kind}_not_in_canon', '引用版本与正史锁定版本不符',
                          evidence={'observed_version_id': key, 'allowed_version_ids': list(approved)})

    def approved_sources(self, character_ids, scene_id, source_ids):
        asset_ids = set(self.canon['style']['reference_asset_ids']) | set(source_ids)
        scene = self.scenes.get(scene_id)
        versions = {key: self.characters[key] for key in character_ids if key in self.characters}
        if scene:
            versions[scene.id] = scene
        for version in versions.values():
            asset_ids.update(version.content.get('reference_asset_ids', []))
            voice = version.content.get('voice', {}).get('reference_audio_asset_id')
            if voice:
                asset_ids.add(voice)
        for key in sorted(asset_ids - self.images.keys()):
            self.images[key] = self.db.get(Asset, key).sha256
        return versions, {key: self.images[key] for key in sorted(asset_ids)}

    def check_states(self, states, roster, edge, issue):
        rows = {row['character_version_id']: row for row in states}
        if set(rows) != roster or len(rows) != len(states):
            issue('shot_state_roster', f'{edge}需为镜头内每个角色登记一份状态',
                  evidence={'expected': sorted(roster), 'observed': list(rows)})
        for key, row in rows.items():
            character = self.characters.get(key)
            identity = character.content.get('identity') if character else None
            if identity and row['wardrobe_id'] not in identity['wardrobes']:
                issue('wardrobe_not_in_canon', f'{edge}服装未登记在角色锁定版本',
                      evidence={'character_version_id': key, 'observed': row['wardrobe_id'],
                                'allowed': list(identity['wardrobes'])})
            for hand in ('left_hand', 'right_hand'):
                prop = row[hand]
                if prop and prop not in self.canon['props']:
                    issue('prop_not_in_canon', f'{edge}手持道具未登记在正史',
                          evidence={'character_version_id': key, 'field': hand, 'observed': prop})
            if not row['action'].strip() or not row['position'].strip():
                issue('shot_action_position_missing', f'{edge}需要记录角色动作及位置',
                      evidence={'character_version_id': key})
        return rows

    def check_transition(self, opening, scene, episode, note, issue):
        if not self.previous:
            return
        before_episode, before_shot, before_scene, closing = self.previous
        for key in sorted(closing.keys() & opening.keys()):
            differences = {name: {'expected': closing[key][name], 'observed': opening[key][name]}
                           for name in STATE_FIELDS if closing[key][name] != opening[key][name]}
            if before_scene != scene:
                differences['scene_version_id'] = {'expected': before_scene, 'observed': scene}
            if differences:
                issue('cross_episode_state_change' if before_episode != episode else 'shot_state_change',
                      '角色状态存在跳变，需要核对衔接', severity='warning' if note.strip() else 'error',
                      evidence={'previous_episode': before_episode, 'previous_shot': before_shot,
                                'character_version_id': key, 'fields': differences, 'transition_note': note})

    def visual_references(self, shot, versions, hashes):
        groups = [('character', versions[key]) for key in shot['character_version_ids'] if key in versions]
        if scene := versions.get(shot.get('scene_version_id')):
            groups.append(('scene', scene))
        references = []
        for role, version in groups:
            for key in dict.fromkeys(version.content.get('reference_asset_ids', [])):
                references.append({'asset_id':key,'sha256':hashes[key],'role':role,'title':version.title,
                                   'version_id':version.id,'version_number':version.number})
        for key in dict.fromkeys(self.canon['style']['reference_asset_ids']):
            references.append({'asset_id':key,'sha256':hashes[key],'role':'style','title':'风格参考',
                               'version_id':None,'version_number':None})
        return [{'index':index,**reference} for index,reference in enumerate(references)]

    def visual_review_items(self, shot, opening, closing):
        items = [{'key':'composition','label':'画面与构图','expected':shot['contract']['visual']},
                 {'key':'style','label':'美术风格','expected':self.canon['style']['description']}]
        if scene := self.scenes.get(shot.get('scene_version_id')):
            details = [f'{scene.title} v{scene.number}',scene.content.get('location'),scene.content.get('time_of_day')]
            items.append({'key':'scene','label':'场景','expected':' · '.join(item for item in details if item)})
        for key in shot['character_version_ids']:
            character = self.characters.get(key)
            identity = character.content.get('identity') if character else None
            if not (identity and key in opening and key in closing):
                continue
            subject = f'{character.title} v{character.number}'
            items.append({'key':f'identity:{key}','label':f'{subject} · 角色身份','expected':identity['traits']})
            states = [('开场',opening[key]),('收尾',closing[key])]
            wardrobes = [f"{edge} · {identity['wardrobes'].get(state['wardrobe_id'],state['wardrobe_id'])}"
                         for edge,state in states]
            items.append({'key':f'wardrobe:{key}','label':f'{subject} · 服装','expected':'\n'.join(wardrobes)})
            if any(state['left_hand'] or state['right_hand'] for _,state in states):
                props = [f"{edge} · 左手 {self.canon['props'].get(state['left_hand'],'空手')}，"
                         f"右手 {self.canon['props'].get(state['right_hand'],'空手')}" for edge,state in states]
                items.append({'key':f'props:{key}','label':f'{subject} · 手持道具','expected':'\n'.join(props)})
        return items

    def check_shot(self, shot, shot_id, episode, start_ms, bridge_note, *, include_references=False):
        def issue(code, detail, severity='error', evidence=None):
            self.issue(code, episode, detail, severity, shot_id, start_ms, evidence)

        contract = shot.get('contract')
        if not shot.get('shot_id') or not contract:
            issue('shot_contract_missing', '镜头需稳定 ID 和生产约束')
            self.previous = None
            return None
        roster, scene = set(shot['character_version_ids']), shot.get('scene_version_id')
        self.check_roster(shot['character_version_ids'], [scene] if scene else [], issue)
        if not scene:
            issue('shot_scene_missing', '镜头需固定场景')
        if len(roster) != len(shot['character_version_ids']):
            issue('shot_character_duplicate', '镜头角色版本重复')
        has_dialogue = bool(shot.get('dialogue', '').strip())
        if has_dialogue:
            speaker = self.characters.get(shot.get('speaker_version_id'))
            if not speaker or not shot.get('dialogue_ms'):
                issue('shot_dialogue_incomplete', '对白需固定说话者并登记时长')
            elif not (speaker.content.get('identity') or {}).get('local_voice'):
                issue('shot_voice_missing', '说话者需固定本机音色')
        for key, value in contract['facts'].items():
            expected = self.canon['facts'].get(key)
            if value != expected:
                issue('canon_fact_conflict', f'剧情事实 {key} 与正史不一致',
                      evidence={'fact': key, 'expected': expected, 'observed': value})
        if shot.get('strategy') == 'still_motion' and not contract['source_image_asset_ids']:
            issue('shot_source_image_missing', '静图运镜需事先固定源图')
        opening = self.check_states(contract['opening'], roster, '开场', issue)
        closing = self.check_states(contract['closing'], roster, '收尾', issue)
        note = contract['continuity_note'] or bridge_note
        self.check_transition(opening, scene, episode, note, issue)
        self.previous = (episode, shot_id, scene, closing)

        versions, asset_hashes = self.approved_sources(roster, scene, contract['source_image_asset_ids'])
        props = {row[hand] for row in [*opening.values(),*closing.values()]
                 for hand in ('left_hand','right_hand') if row[hand]}
        payload = {'rule_version': RULE_VERSION, 'shot': {key:value for key,value in shot.items() if key!='number'},
                   'style': self.canon['style'], 'props': {key:self.canon['props'].get(key) for key in props},
                   'version_hashes': {key: row.content_hash for key, row in versions.items()},
                   'asset_hashes': asset_hashes}
        if self.production_spec:
            payload['production_spec'] = self.production_spec
        self.contracts[shot_id] = fingerprint(payload)
        checklist = contract.get('visual_checklist')
        return {'contract_sha256': self.contracts[shot_id], 'visual':contract['visual'], 'has_dialogue':has_dialogue,
                **({'production_spec':self.production_spec} if self.production_spec else {}),
                'source_images': {key: asset_hashes[key] for key in contract['source_image_asset_ids']},
                **({'visual_references':self.visual_references(shot,versions,asset_hashes)} if include_references else {}),
                **({'visual_checklist':True} if checklist else {}),
                **({'review_items':self.visual_review_items(shot,opening,closing)} if checklist and include_references else {}),
                **({'screen_text':contract['screen_text']} if contract.get('screen_text') else {})}


def require_active_plan(db, version):
    """Guarded writes hold the project lock shared by series approval."""
    latest = latest_approved(db, version.entity_id)
    if latest and latest.id != version.id and (latest.content.get('guardian') or version.content.get('guardian')):
        raise HTTPException(409, '此 Guardian 计划已有新版获批。请选择当前批准版本。')


def latest_approved(db, entity_id):
    return db.scalar(select(StoryVersion).where(StoryVersion.entity_id == entity_id,
                       StoryVersion.provenance['series_approved'].as_boolean().is_(True))
                       .order_by(StoryVersion.number.desc()).limit(1))


def candidate_matches(asset, plan, shot):
    metadata = asset.media_info
    contract = shot.get('guardian')
    if not contract:
        return metadata.get('story_version_id') == plan.id
    return (metadata.get('guardian_series_id') == plan.entity_id
            and metadata.get('guardian_contract_sha256') == contract['contract_sha256']
            and metadata.get('shot_id') == shot['shot_id'])


def require_reviewed_timeline(db, plan, episode, timeline):
    if not plan.content.get('guardian'):
        return
    tracks = [track for track in timeline['tracks'] if track['enabled'] and track['clips']]
    main = [clip for track in tracks if track['role']=='main' for clip in track['clips']]
    main.sort(key=lambda clip: clip['at'])
    shots = episode['shots']
    if not main or any(track['role']=='overlay' for track in tracks) or len(main)!=len(shots):
        raise HTTPException(422,f"第 {episode['number']} 集需逐镜头使用已审核主画面")
    for shot,clip in zip(shots,main):
        start = round(shot['start_ms']*24/1000)
        stop = round((shot['start_ms']+shot['duration_ms'])*24/1000)
        asset = db.get(Asset,clip['asset_id'])
        if (not asset or not candidate_matches(asset,plan,shot) or asset.media_info.get('guardian_aspect')!=timeline['profile']
                or clip['at']!=start or clip['frames']!=stop-start
                or clip['source_in'] or clip['fade_in'] or clip['fade_out']):
            raise HTTPException(422,f"镜头 {shot['shot_id']} 的候选审核或剪辑范围与批准合同不符")
    if timeline['frames']!=main[-1]['at']+main[-1]['frames']:
        raise HTTPException(422,'Guardian 时间轴须完整覆盖固定镜头范围')
    if any((shot.get('guardian') or {}).get('has_dialogue') for shot in shots):
        assets = []
        for role in ('dialogue','caption'):
            clips = [clip for track in tracks if track['role']==role for clip in track['clips']]
            if len(clips)!=1:
                raise HTTPException(422,'有锁定对白的分集须使用同一批准分镜的完整配音与字幕')
            clip = clips[0]
            asset = db.get(Asset,clip['asset_id'])
            if (not asset or asset.media_info.get('guardian_series_id')!=plan.entity_id
                or asset.media_info.get('story_version_id')!=episode['storyboard_version_id']
                or clip['at'] or clip['source_in'] or clip['frames']!=timeline['frames']):
                raise HTTPException(422,'配音或字幕与批准分镜及时间轴范围不符')
            assets.append(asset)
        voice_task_id = assets[0].media_info.get('task_id')
        if not voice_task_id or assets[1].media_info.get('task_id')!=voice_task_id:
            raise HTTPException(422,'对白音轨与字幕须从同一次已采纳的配音任务生成')
        return assets
