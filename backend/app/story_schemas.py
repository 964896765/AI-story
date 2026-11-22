from typing import Annotated, Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

Kind=Literal['novel','script','character','scene','relationship','episode','storyboard','generation_plan','story_bible','timeline']

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)

VersionId = Annotated[str, Field(min_length=1,max_length=36)]
RuleKey = Annotated[str, Field(pattern=r'^[a-z][a-z0-9_-]{0,47}$')]
RuleText = Annotated[str, Field(min_length=1,max_length=1000,pattern=r'\S')]

class IdentityLock(Strict):
    traits: RuleText
    wardrobes: dict[RuleKey,RuleText] = Field(min_length=1,max_length=24)
    local_voice: str | None = Field(default=None,min_length=1,max_length=100,pattern=r'\S')

class ShotActorState(Strict):
    character_version_id: VersionId
    wardrobe_id: RuleKey
    left_hand: RuleKey | None = None
    right_hand: RuleKey | None = None
    action: str = Field(default='',max_length=200)
    position: str = Field(default='',max_length=200)

class ShotContract(Strict):
    visual: RuleText
    facts: dict[RuleKey,RuleText] = Field(default_factory=dict,max_length=32)
    source_image_asset_ids: list[VersionId] = Field(default_factory=list,max_length=12)
    opening: list[ShotActorState] = Field(default_factory=list,max_length=16)
    closing: list[ShotActorState] = Field(default_factory=list,max_length=16)
    continuity_note: str = Field(default='',max_length=1000)

class StyleLock(Strict):
    description: RuleText
    reference_asset_ids: list[VersionId] = Field(default_factory=list,max_length=12)

class GuardianCanon(Strict):
    facts: dict[RuleKey,RuleText] = Field(min_length=1,max_length=100)
    props: dict[RuleKey,RuleText] = Field(default_factory=dict,max_length=100)
    character_version_ids: list[VersionId] = Field(default_factory=list,max_length=100)
    scene_version_ids: list[VersionId] = Field(min_length=1,max_length=100)
    style: StyleLock

class Novel(Strict):
    text: str=Field(min_length=1,max_length=1_000_000,pattern=r'.*\S.*')
    authorization: str=Field(min_length=1,max_length=10000,pattern=r'.*\S.*')
    source_asset_id: str | None=None

class Voice(Strict):
    description: str=Field(default='',max_length=10000)
    reference_audio_asset_id: str | None=None
    provider: Literal['disabled']='disabled'
    voice_id: str=Field(default='',max_length=200)

class Character(Strict):
    description: str=Field(default='',max_length=20000)
    appearance: str=Field(default='',max_length=20000)
    personality: str=Field(default='',max_length=20000)
    voice: Voice=Field(default_factory=Voice)
    reference_asset_ids: list[str]=Field(default_factory=list,max_length=20)
    identity: IdentityLock | None=None

class Scene(Strict):
    description: str=Field(default='',max_length=20000)
    location: str=Field(default='',max_length=1000)
    time_of_day: str=Field(default='',max_length=200)
    reference_asset_ids: list[str]=Field(default_factory=list,max_length=20)

class Script(Strict):
    summary: str=Field(default='',max_length=20000)
    body: str=Field(min_length=1,max_length=1_000_000,pattern=r'.*\S.*')
    source_version_id: str | None=None
    character_version_ids: list[str]=Field(default_factory=list,max_length=100)
    scene_version_ids: list[str]=Field(default_factory=list,max_length=100)

class Episode(Script):
    number: int=Field(ge=1,le=1000)

class Relation(Strict):
    from_character_version_id: str
    to_character_version_id: str
    description: str=Field(min_length=1,max_length=2000)
    @model_validator(mode='after')
    def different(self):
        if self.from_character_version_id==self.to_character_version_id:raise ValueError('人物关系两端不能相同')
        return self

class Relationships(Strict):
    relationships: list[Relation]=Field(min_length=1,max_length=200)

class Shot(Strict):
    number: int=Field(ge=1,le=1000)
    shot_id: str | None=Field(default=None,pattern=r'^[a-zA-Z0-9_-]{1,48}$')
    description: str=Field(min_length=1,max_length=10000)
    dialogue: str=Field(default='',max_length=10000)
    planned_duration: float=Field(default=3,ge=0.2,le=120)
    scene_version_id: str | None=None
    character_version_ids: list[str]=Field(default_factory=list,max_length=50)
    framing: Literal['wide','medium','close','detail'] | None=None
    angle: str=Field(default='',max_length=200)
    movement: str=Field(default='',max_length=300)
    lighting: str=Field(default='',max_length=300)
    composition: str=Field(default='',max_length=500)
    wardrobe_and_props: str=Field(default='',max_length=800)
    speaker_version_id: str | None=None
    dialogue_ms: int | None=Field(default=None,ge=0,le=120000)
    emotion: str=Field(default='',max_length=200)
    sound_cue: str=Field(default='',max_length=300)
    transition: str=Field(default='',max_length=200)
    strategy: Literal['manual','still_motion','reference_video','generated_video']='manual'
    contract: ShotContract | None=None

    @model_validator(mode='after')
    def dialogue_fits(self):
        if self.speaker_version_id and self.speaker_version_id not in self.character_version_ids:
            raise ValueError('对白说话者必须在该镜头角色列表内')
        if self.dialogue_ms is not None and self.dialogue_ms>round(self.planned_duration*1000):
            raise ValueError('对白时长超过镜头计划时长')
        return self

class Storyboard(Strict):
    source_version_id: str
    shots: list[Shot]=Field(min_length=1,max_length=200)
    @model_validator(mode='after')
    def unique(self):
        numbers=[s.number for s in self.shots]
        if len(numbers)!=len(set(numbers)):raise ValueError('镜头编号不能重复')
        shot_ids=[s.shot_id for s in self.shots if s.shot_id]
        if len(shot_ids)!=len(set(shot_ids)):raise ValueError('镜头稳定 ID 不能重复')
        return self

class GenerationPlan(Strict):
    capability: Literal['text','speech','image','video']
    prompt: str=Field(min_length=1,max_length=100000)
    input_version_ids: list[str]=Field(default_factory=list,max_length=100)

class BoundaryState(Strict):
    character_version_id: str=Field(min_length=1,max_length=36)
    scene_version_id: str | None=Field(default=None,min_length=1,max_length=36)
    wardrobe: str=Field(default='',max_length=200)
    prop_state: str=Field(default='',max_length=300)
    condition: str=Field(default='',max_length=300)

class SeriesEpisode(Strict):
    episode_version_id: str=Field(min_length=1,max_length=36)
    storyboard_version_id: str=Field(min_length=1,max_length=36)
    target_duration_ms: int=Field(ge=200,le=86_400_000)
    opener: list[BoundaryState]=Field(default_factory=list,max_length=16)
    closer: list[BoundaryState]=Field(default_factory=list,max_length=16)
    bridge_note: str=Field(default='',max_length=1200)

class StoryThread(Strict):
    label: str=Field(min_length=1,max_length=200,pattern=r'.*\S.*')
    setup_episode: int=Field(ge=1,le=1000)
    payoff_episode: int | None=Field(default=None,ge=1,le=1000)

class StoryBible(Strict):
    script_version_id: str=Field(min_length=1,max_length=36)
    theme: str=Field(min_length=1,max_length=2000,pattern=r'.*\S.*')
    world: str=Field(min_length=1,max_length=8000,pattern=r'.*\S.*')
    rules: str=Field(default='',max_length=8000)
    timeline: str=Field(default='',max_length=8000)
    episodes: list[SeriesEpisode]=Field(min_length=1,max_length=60)
    threads: list[StoryThread]=Field(default_factory=list,max_length=100)
    guardian: GuardianCanon | None=None

class TimelineClip(Strict):
    id: str=Field(pattern=r'^[a-zA-Z0-9_-]{1,48}$')
    asset_id: str=Field(min_length=1,max_length=36)
    at: int=Field(ge=0,lt=14400)
    source_in: int=Field(default=0,ge=0,le=2_073_600)
    frames: int=Field(ge=1,le=14400)
    still_motion: Literal['none','push_in']='none'
    fade_in: int=Field(default=0,ge=0,le=240)
    fade_out: int=Field(default=0,ge=0,le=240)

    @model_validator(mode='after')
    def fades_fit(self):
        if self.fade_in+self.fade_out>self.frames:raise ValueError('淡入淡出合计不能超过片段时长')
        return self

class TimelineTrack(Strict):
    id: str=Field(pattern=r'^[a-zA-Z0-9_-]{1,48}$')
    role: Literal['main','overlay','dialogue','music','sfx','caption']
    enabled: bool=True
    locked: bool=False
    volume: float=Field(default=1,ge=0,le=4)
    clips: list[TimelineClip]=Field(default_factory=list,max_length=40)

class Timeline(Strict):
    source_version_id: str | None=Field(default=None,min_length=1,max_length=36)
    frame_rate: Literal[24]=24
    profile: Literal['portrait','landscape','square']='portrait'
    frames: int=Field(ge=12,le=14400)
    tracks: list[TimelineTrack]=Field(min_length=1,max_length=10)

    @model_validator(mode='after')
    def structure(self):
        if len({track.id for track in self.tracks})!=len(self.tracks):raise ValueError('轨道 ID 不能重复')
        if sum(track.role=='main' for track in self.tracks)!=1:raise ValueError('需要一条主画面轨道')
        if sum(track.role=='caption' for track in self.tracks)>1:raise ValueError('最多一条字幕轨道')
        clips=[clip for track in self.tracks for clip in track.clips]
        if len(clips)>50 or len({clip.id for clip in clips})!=len(clips):
            raise ValueError('时间轴最多 50 个片段，且片段 ID 必须唯一')
        for track in self.tracks:
            end=0
            for clip in sorted(track.clips,key=lambda item:item.at):
                if clip.at<end or clip.at+clip.frames>self.frames:
                    raise ValueError('同轨片段不可重叠或超出时间轴')
                end=clip.at+clip.frames
        return self

CONTENT_MODELS={'novel':Novel,'script':Script,'character':Character,'scene':Scene,'relationship':Relationships,'episode':Episode,'storyboard':Storyboard,'generation_plan':GenerationPlan,'story_bible':StoryBible,'timeline':Timeline}

class EntityInput(Strict):
    kind: Kind
    title: str=Field(min_length=1,max_length=200,pattern=r'.*\S.*')
    content: dict
    idempotency_key: str=Field(min_length=1,max_length=100)
    note: str=Field(default='',max_length=10000)

class VersionInput(Strict):
    expected_version: int=Field(ge=1)
    title: str=Field(min_length=1,max_length=200,pattern=r'.*\S.*')
    content: dict
    idempotency_key: str=Field(min_length=1,max_length=100)
    note: str=Field(default='',max_length=10000)

class RestoreInput(Strict):
    expected_version: int=Field(ge=1)
    version: int=Field(ge=1)
    idempotency_key: str=Field(min_length=1,max_length=100)

class DeriveInput(Strict):
    source_version_id: str
    operation: Literal['structure_script','split_episodes','split_shots']
    unit_chars: int=Field(default=800,ge=100,le=10000)
    idempotency_key: str=Field(min_length=1,max_length=100)
