import ipaddress
import re
from decimal import Decimal
from typing import Literal
from urllib.parse import urlsplit
from pydantic import Field,field_validator,model_validator
from .story_schemas import Strict

class ProviderSettings(Strict):
    base_url: str=Field(default='',max_length=500)
    model: str=Field(min_length=1,max_length=160,pattern=r'^[a-zA-Z0-9_.:/-]+$')
    secret_env: str=Field(default='',max_length=128)
    currency: Literal['CNY','USD']='CNY'
    input_per_million: Decimal | None=Field(default=None,ge=0,le=100000,decimal_places=8)
    output_per_million: Decimal | None=Field(default=None,ge=0,le=100000,decimal_places=8)
    input_token_limit: int=Field(default=8192,ge=256,le=2_000_000)
    output_token_limit: int=Field(default=2048,ge=128,le=32768)
    billing_verified: bool=False
    price_source: str=Field(default='',max_length=1000)
    token_parameter: Literal['max_completion_tokens','max_tokens']='max_completion_tokens'
    response_format: Literal['json_schema','json_object']='json_schema'
    timeout_seconds: int=Field(default=60,ge=1,le=120)
    rejection_is_nonbillable: bool=False
    mock_scenario: Literal['success','rate_limit','server_error','timeout','invalid_output','missing_usage','overrun']='success'

    @field_validator('base_url')
    @classmethod
    def safe_url(cls,value):
        if not value:return value
        parsed=urlsplit(value)
        if parsed.scheme!='https' or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError('Base URL必须为无凭据、无查询参数的HTTPS地址')
        if parsed.hostname.lower() in ('localhost','localhost.localdomain') or parsed.hostname.lower().endswith(('.localhost','.local')):
            raise ValueError('真实供应商不得指向本机地址；模拟不使用网络')
        try:
            address=ipaddress.ip_address(parsed.hostname)
            if not address.is_global:raise ValueError('供应商地址必须为公网地址')
        except ValueError as exc:
            if str(exc)=='供应商地址必须为公网地址':raise
        return value.rstrip('/')

    @field_validator('secret_env')
    @classmethod
    def env_name(cls,value):
        if value and not re.fullmatch(r'[A-Z][A-Z0-9_]*_API_KEY',value):raise ValueError('只允许配置以_API_KEY结尾的环境变量名称，不接受密钥值')
        return value

class ProviderInput(Strict):
    label: str=Field(min_length=1,max_length=120)
    kind: Literal['mock','openai_compatible']
    enabled: bool=False
    settings: ProviderSettings
    @model_validator(mode='after')
    def configured(self):
        if self.kind=='openai_compatible' and (not self.settings.base_url or not self.settings.secret_env):raise ValueError('真实供应商须指定Base URL和密钥环境变量名称')
        if self.kind=='openai_compatible' and self.settings.mock_scenario!='success':raise ValueError('真实适配器不接受模拟场景')
        return self

class BudgetInput(Strict):
    mode: Literal['mock','live']
    currency: Literal['CNY','USD']='CNY'
    limit_micros: int=Field(ge=0,le=10**12)
    authorization_id: str=Field(default='',max_length=200)
    note: str=Field(default='',max_length=2000)
    idempotency_key: str=Field(min_length=1,max_length=100)

class AdaptInput(Strict):
    source_version_id: str
    provider_id: str
    goal: str=Field(min_length=1,max_length=4000,pattern=r'.*\S.*')
    style: str=Field(default='',max_length=2000)
    audience: str=Field(default='',max_length=1000)
    length: str=Field(default='',max_length=1000)
    constraints: str=Field(default='',max_length=4000)
    max_output_tokens: int=Field(default=1024,ge=128,le=32768)
    idempotency_key: str=Field(min_length=1,max_length=100)

class OutlineEpisode(Strict):
    number: int=Field(ge=1,le=1000)
    title: str=Field(min_length=1,max_length=200)
    synopsis: str=Field(min_length=1,max_length=5000)

class Dialogue(Strict):
    speaker: str=Field(min_length=1,max_length=100)
    text: str=Field(min_length=1,max_length=5000)

class AdaptedDraft(Strict):
    title: str=Field(min_length=1,max_length=200)
    synopsis: str=Field(min_length=1,max_length=20000)
    body: str=Field(min_length=1,max_length=100000)
    episodes: list[OutlineEpisode]=Field(min_length=1,max_length=50)
    dialogues: list[Dialogue]=Field(max_length=200)
    @model_validator(mode='after')
    def sequence(self):
        if [e.number for e in self.episodes]!=list(range(1,len(self.episodes)+1)):raise ValueError('分集编号必须从1连续递增')
        return self

class ReviewInput(Strict):
    action: Literal['accept','reject']
    draft_revision: int=Field(ge=1)
    save_mode: Literal['new_script','source_new_version']='new_script'
    expected_source_version: int | None=Field(default=None,ge=1)
    note: str=Field(min_length=1,max_length=4000)

class DraftEditInput(Strict):
    expected_revision: int=Field(ge=1)
    draft: AdaptedDraft
    idempotency_key: str=Field(min_length=1,max_length=100)

class ReconcileInput(Strict):
    resolution: Literal['not_charged','receipt']
    evidence: str=Field(min_length=20,max_length=4000)
    receipt: dict | None=None

class RetryInput(Strict):
    idempotency_key: str=Field(min_length=1,max_length=100)
    acknowledge_new_charge: bool=False

class BillingInput(Strict):
    kind: Literal['charge','refund']
    amount_micros: int=Field(ge=0,le=10**15)
    evidence: str=Field(min_length=20,max_length=4000)
    idempotency_key: str=Field(min_length=1,max_length=100)

    @model_validator(mode='after')
    def nonzero_refund(self):
        if self.kind=='refund' and not self.amount_micros:
            raise ValueError('退款金额必须大于0')
        return self
