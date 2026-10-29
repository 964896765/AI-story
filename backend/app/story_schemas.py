from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,model_validator

Kind=Literal['novel','script','character','scene','relationship','episode','storyboard','generation_plan']

class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',allow_inf_nan=False)

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
    description: str=Field(min_length=1,max_length=10000)
    dialogue: str=Field(default='',max_length=10000)
    planned_duration: float=Field(default=3,ge=0.2,le=120)
    scene_version_id: str | None=None
    character_version_ids: list[str]=Field(default_factory=list,max_length=50)

class Storyboard(Strict):
    source_version_id: str
    shots: list[Shot]=Field(min_length=1,max_length=200)
    @model_validator(mode='after')
    def unique(self):
        numbers=[s.number for s in self.shots]
        if len(numbers)!=len(set(numbers)):raise ValueError('镜头编号不能重复')
        return self

class GenerationPlan(Strict):
    capability: Literal['text','speech','image','video']
    prompt: str=Field(min_length=1,max_length=100000)
    input_version_ids: list[str]=Field(default_factory=list,max_length=100)

CONTENT_MODELS={'novel':Novel,'script':Script,'character':Character,'scene':Scene,'relationship':Relationships,'episode':Episode,'storyboard':Storyboard,'generation_plan':GenerationPlan}

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
