"""OpenAI-compatible HTTP transport. Never retries or enables network implicitly."""
import ipaddress
import json
import os
import re
import socket
from urllib.parse import urlsplit
import httpx
from .model_adapters import ModelRequest,ModelResult
from .text_schemas import AdaptedDraft

class CallFailure(RuntimeError):
    def __init__(self,code,unknown=False):
        self.code,self.unknown=code,unknown
        super().__init__(code)

def live_gate():
    return os.getenv('AI_STORY_ENABLE_PAID_TEXT')=='1' and os.getenv('AI_STORY_BUDGET_GUARD_APPROVED')=='1' and bool(os.getenv('AI_STORY_LIVE_AUTHORIZATION_ID'))

def configured_key(settings):
    return os.getenv(settings.get('secret_env',''),'')

def approved_endpoint(settings):
    # Authorization binds the destination and credential reference in local configuration.
    return bool(settings['base_url'] and settings['secret_env']) and (
        settings['base_url'] == os.getenv('AI_STORY_LIVE_BASE_URL')
        and settings['secret_env'] == os.getenv('AI_STORY_LIVE_SECRET_ENV')
    )

def redact(value,secret):
    return value.replace(secret,'[REDACTED]') if secret else value

class MockTextAdapter:
    def __init__(self,settings):self.settings=settings
    def estimate(self,request):return {'simulated':True,'estimated_cost_minor':None}
    def invoke(self,request:ModelRequest):
        scenario=self.settings.get('mock_scenario','success')
        if scenario=='rate_limit':raise CallFailure('RATE_LIMIT_REJECTED',False)
        if scenario=='server_error':raise CallFailure('SERVER_ERROR_OUTCOME_UNKNOWN',True)
        if scenario=='timeout':raise CallFailure('TIMEOUT_OUTCOME_UNKNOWN',True)
        draft={'title':'模拟改编草稿（非AI生成）','synopsis':'仅用于预算与人工审核流程验收，不代表模型创作质量。','body':'【模拟结果，非真实AI创作】\n'+request.parameters.get('source_text','')[:4000],'episodes':[{'number':1,'title':'模拟第一集','synopsis':'展示待审核分集结构。'}],'dialogues':[{'speaker':'模拟角色','text':'这是模拟对白，请人工修订。'}]}
        if request.parameters.get('director_advice'):
            draft={'choice':1,'rationale':'离线模拟按提交顺序选择第一个方案，供验证审核流程。',
                   'checks':['核对固定输入版本','查看执行计划与授权条件','由制作人员单独批准执行']}
        content=json.dumps(draft,ensure_ascii=False)
        if scenario=='invalid_output':content='not valid JSON'
        usage={'prompt_tokens':min(100,self.settings['input_token_limit']),'completion_tokens':min(80,request.parameters['max_output_tokens']),'total_tokens':0}
        usage['total_tokens']=usage['prompt_tokens']+usage['completion_tokens']
        if scenario=='missing_usage':usage=None
        if scenario=='overrun':usage={'prompt_tokens':self.settings['input_token_limit']*10,'completion_tokens':request.parameters['max_output_tokens']*10}
        return ModelResult('mock-'+request.idempotency_key,{'text':content},None,None,usage,'stop','mock-request')

class OpenAICompatibleAdapter:
    def __init__(self,settings,transport=None):
        self.settings,self.transport=settings,transport
    def estimate(self,request):return {'available':False,'estimated_cost_minor':None,'reason':'使用治理层的已核验费率和最坏用量上限报价'}
    def invoke(self,request:ModelRequest):
        # Defense in depth: even direct adapter use cannot bypass the local live switch.
        if not live_gate():raise CallFailure('LIVE_CALLS_NOT_AUTHORIZED')
        secret=configured_key(self.settings)
        if not secret:raise CallFailure('API_KEY_NOT_CONFIGURED')
        hostname=urlsplit(self.settings['base_url']).hostname
        if self.transport is None:
            if not approved_endpoint(self.settings):raise CallFailure('PROVIDER_ENDPOINT_NOT_AUTHORIZED')
            try:
                addresses=socket.getaddrinfo(hostname,443,type=socket.SOCK_STREAM)
                if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):raise CallFailure('NONPUBLIC_PROVIDER_ADDRESS')
            except socket.gaierror:raise CallFailure('PROVIDER_DNS_UNAVAILABLE') from None
        schema=AdaptedDraft.model_json_schema()
        fmt={'type':'json_schema','json_schema':{'name':'drama_adaptation','strict':True,'schema':schema}} if self.settings['response_format']=='json_schema' else {'type':'json_object'}
        payload={'model':self.settings['model'],'messages':[{'role':'system','content':request.parameters['system_prompt']},{'role':'user','content':request.prompt}],'response_format':fmt,'stream':False,'n':1,'store':False,self.settings['token_parameter']:request.parameters['max_output_tokens']}
        # HTTPX has no automatic application retry. No SDK retry layer is used.
        try:
            with httpx.Client(transport=self.transport,timeout=httpx.Timeout(self.settings['timeout_seconds'],connect=5),follow_redirects=False,trust_env=False) as client:
                with client.stream('POST',self.settings['base_url'].rstrip('/')+'/chat/completions',headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json','X-Client-Request-Id':request.idempotency_key},json=payload) as response:
                    status=response.status_code
                    if status>=300:
                        known=status in (400,401,403,404,422,429) and self.settings['rejection_is_nonbillable']
                        code='RATE_LIMIT_REJECTED' if status==429 and known else f'HTTP_{status}_REJECTED' if known else f'HTTP_{status}_OUTCOME_UNKNOWN'
                        raise CallFailure(code,not known)
                    chunks=[];size=0
                    for chunk in response.iter_bytes():
                        size+=len(chunk)
                        if size>2*1024**2:raise CallFailure('RESPONSE_TOO_LARGE_OUTCOME_UNKNOWN',True)
                        chunks.append(chunk)
                    data=json.loads(b''.join(chunks))
                    choice=data.get('choices',[{}])[0]
                    message=choice.get('message',{})
                    reason='refusal' if message.get('refusal') else choice.get('finish_reason')
                    content=message.get('content')
                    content=redact(content,secret) if isinstance(content,str) else ''
                    reason=redact(reason,secret) if isinstance(reason,str) else None
                    request_id=redact(response.headers.get('x-request-id',''),secret)
                    if not re.fullmatch(r'[a-zA-Z0-9_.:-]{0,200}',request_id):request_id=''
                    call_id=data.get('id')
                    if not isinstance(call_id,str) or len(call_id)>200:call_id='unavailable'
                    else:call_id=redact(call_id,secret)
                    return ModelResult(call_id,{'text':content},None,None,data.get('usage'),reason,request_id)
        except CallFailure:raise
        except (httpx.TimeoutException,httpx.TransportError):raise CallFailure('TRANSPORT_OUTCOME_UNKNOWN',True) from None
        except (ValueError,KeyError,IndexError,TypeError):raise CallFailure('MALFORMED_RESPONSE_OUTCOME_UNKNOWN',True) from None

def build_adapter(kind,settings):
    if kind=='mock':return MockTextAdapter(settings)
    if kind=='openai_compatible':return OpenAICompatibleAdapter(settings)
    raise CallFailure('UNREGISTERED_TEXT_ADAPTER')
