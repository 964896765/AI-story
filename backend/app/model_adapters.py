"""No network implementations are registered. Plans are preparation, not generation."""
from dataclasses import dataclass
from typing import Protocol,Literal

Capability=Literal['text','speech','image','video']

class ModelsDisabled(RuntimeError):
    pass

@dataclass(frozen=True)
class ModelRequest:
    project_id: str
    idempotency_key: str
    capability: Capability
    prompt: str
    input_versions: tuple[str,...]

@dataclass(frozen=True)
class ModelResult:
    provider_call_id: str
    output: dict
    recorded_cost_minor: int | None
    currency: str | None

class ModelAdapter(Protocol):
    def estimate(self,request:ModelRequest) -> dict: ...
    def invoke(self,request:ModelRequest) -> ModelResult: ...

class DisabledAdapter:
    def estimate(self,request:ModelRequest) -> dict:
        return {'available':False,'estimated_cost_minor':None,'currency':None,'reason':'尚未配置且未获授权的模型调用；未知费用不记为零'}
    def invoke(self,request:ModelRequest) -> ModelResult:
        raise ModelsDisabled('模型调用未启用；没有发起网络请求或收费')

def adapter_for(provider: str='disabled') -> ModelAdapter:
    if provider!='disabled':raise ModelsDisabled('供应商未注册，禁止隐式启用模型')
    return DisabledAdapter()
