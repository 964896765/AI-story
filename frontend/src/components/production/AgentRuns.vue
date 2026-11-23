<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { api, post } from '../../services/api'
import type { VersionRef } from '../../types/workbench'
import SpecPicker from './SpecPicker.vue'
import SpecReference from './SpecReference.vue'

type Flow='story'|'preflight'
interface Role {id:string;label:string;input:string;output:string;permission:string}
interface Step extends Role {task_id?:string; status?:string; progress?:number; attempt?:number; elapsed_seconds?:number; error?:string|null;
  result?:{result:Record<string,unknown>;result_sha256:string;previous_result_sha256:string|null}|null}
interface Run {id:string;workflow:Flow;goal:string;status:string;production_spec_version_id:string;
  input_sha256:string;output_sha256:string|null;approval?:{note:string};review?:{note:string};
  inputs?:{source?:{title:string;version:number};series?:{title:string;version:number};timeline?:{title:string;version:number}};
  steps?:Step[]}
const props=defineProps<{projectId:string}>()
const root=`/projects/${props.projectId}/agents`
const director=`/director/projects/${props.projectId}`
const labels:Record<Flow,string>={story:'原稿筹备',preflight:'生产预检'}
const status:Record<string,string>={awaiting_approval:'待审批',queued:'已排队',running:'执行中',awaiting_review:'待审核',
  accepted:'审核通过',rejected:'已退回',succeeded:'已完成',failed:'失败',cancelled:'已取消',cancelling:'取消中'}
const flow=ref<Flow>('story'), goal=ref(''), specId=ref<string|null>(null), source=ref(''), series=ref(''), timeline=ref('')
const sourceVersions=ref<VersionRef[]>([]), seriesVersions=ref<VersionRef[]>([]), timelines=ref<VersionRef[]>([])
const capabilities=ref<{workflows:Record<Flow,string[]>;roles:Role[]}|null>(null)
const runs=ref<Run[]>([]), active=ref<Run|null>(null), runId=ref(''), note=ref(''), error=ref(''), busy=ref(false)
const proposedRoles=computed(()=>capabilities.value?.workflows[flow.value].map(id=>capabilities.value!.roles.find(role=>role.id===id)! ) || [])
let timer:ReturnType<typeof setInterval>|undefined
let closed=false, refreshInProgress=false
let selectionRevision=0
let lastDraft={signature:'',key:''}
const ready=computed(()=>!!(specId.value && goal.value.trim() && (flow.value==='story' ? source.value : series.value && timeline.value)))
const canCancel=computed(()=>active.value && ['awaiting_approval','queued','running','failed'].includes(active.value.status))
const title=(item:VersionRef)=>item.title+' · v'+item.version
const resultTitle=(item:Step)=> item.status ? status[item.status] || item.status : '待审批'
const keyFor=(body:object)=> {
  const signature=JSON.stringify(body)
  if(lastDraft.signature!==signature) lastDraft={signature,key:crypto.randomUUID()}
  return lastDraft.key
}
async function refresh() {
  if(refreshInProgress || closed)return
  refreshInProgress=true
  try {
    const selected=runId.value
    const revision=selectionRevision
    const [items,record]=await Promise.all([api<Run[]>(root+'/runs'),
      selected ? api<Run>(root+'/runs/'+selected) : Promise.resolve(null)])
    if(!closed) {
      runs.value=items
      if(runId.value===selected && selectionRevision===revision)active.value=record
    }
  } finally {refreshInProgress=false}
}
async function run(action:()=>Promise<void>) {
  busy.value=true;error.value=''
  try {await action()}
  catch (failure) {error.value=String(failure)}
  finally {busy.value=false}
}
function select(record:Run) {
  selectionRevision++
  runId.value=record.id;active.value=record;note.value=''
}
async function open(id:string) {
  select(await api<Run>(root+'/runs/'+id))
}
async function save() {
  const body={workflow:flow.value,goal:goal.value,production_spec_version_id:specId.value,
    external_budget_cents:0,...(flow.value==='story' ? {source_version_id:source.value} :
      {series_version_id:series.value,timeline_version_id:timeline.value})}
  const record=await post<Run>(root+'/runs',{...body,idempotency_key:keyFor(body)})
  select(record)
  await refresh()
}
async function action(name:'approve'|'review'|'retry'|'cancel',decision?:'accepted'|'rejected') {
  const record=active.value
  if(!record)return
  const payload=name==='approve' ? {expected_input_sha256:record.input_sha256,note:note.value}
    : name==='review' ? {expected_output_sha256:record.output_sha256,decision,note:note.value} : {}
  select(await post<Run>(root+'/runs/'+record.id+'/'+name,payload))
  await refresh()
}
watch(series,async(id,_,onCleanup)=>{
  timeline.value='';timelines.value=[]
  if(!id)return
  const request=new AbortController()
  onCleanup(()=>request.abort())
  try {timelines.value=(await api<{timelines:VersionRef[]}>(director+'/batch-options/'+id,{signal:request.signal})).timelines}
  catch(failure) {if(!request.signal.aborted)error.value=String(failure)}
})
onMounted(()=>{
  void run(async()=>{
    const listSource=(kind:string)=>api<{items:VersionRef[]}>(`/projects/${props.projectId}/story/entities?kind=${kind}&limit=100`)
    const [catalog,novels,scripts,episodes,plans]=await Promise.all([
      api<{workflows:Record<Flow,string[]>;roles:Role[]}>(root+'/capabilities'),
      listSource('novel'),listSource('script'),listSource('episode'),
      api<VersionRef[]>(director+'/batch-options'),
    ])
    capabilities.value=catalog
    sourceVersions.value=[...novels.items,...scripts.items,...episodes.items]
    seriesVersions.value=plans
    await refresh()
    if(runs.value.length) await open(runs.value[0].id)
  })
  timer=setInterval(()=>{
    if(!busy.value && !document.hidden)void refresh().catch(failure=>{error.value=String(failure)})
  },2500)
})
onUnmounted(()=>{closed=true;clearInterval(timer)})
</script>

<template>
  <div class="agent-workspace">
    <p class="hint">本机规则执行 · 外部费用 ¥0 · 运行前审批，结果完成后单独审核。</p>
    <p v-if="error" role="alert" class="error">{{error}}</p>
    <div class="agent-columns">
      <form @submit.prevent="run(save)">
        <h3>准备运行</h3>
        <label>Agent 工作流<select v-model="flow">
          <option value="story">原稿筹备 · 结构统计与分集草案</option><option value="preflight">生产预检 · 参考、合同与时间轴</option>
        </select></label>
        <SpecPicker v-model="specId" :project-id="projectId" :disabled="busy" />
        <p v-if="!specId" class="hint"><RouterLink :to="{name:'wizard',query:{project:projectId,step:1}}">打开项目制作规格</RouterLink></p>
        <label v-if="flow==='story'">固定原稿<select v-model="source"><option value="">选择原稿版本</option>
          <option v-for="item in sourceVersions" :key="item.version_id" :value="item.version_id">{{title(item)}}</option>
        </select></label>
        <template v-else>
          <label>固定批准计划<select v-model="series"><option value="">选择故事圣经</option>
            <option v-for="item in seriesVersions" :key="item.version_id" :value="item.version_id">{{title(item)}}</option>
          </select></label>
          <label>固定预检时间轴<select v-model="timeline"><option value="">选择时间轴</option>
            <option v-for="item in timelines" :key="item.version_id" :value="item.version_id">{{title(item)}}</option>
          </select></label>
        </template>
        <details v-if="flow==='story'">
          <summary>按历史 ID 引用原稿</summary>
          <label>原稿版本 ID<input v-model.trim="source" maxlength="36"></label>
        </details>
        <label>Agent 制作目标<textarea v-model="goal" required maxlength="2000"></textarea></label>
        <p class="hint">{{proposedRoles.map(role=>role.label).join(' → ')}}</p>
        <button type="submit" class="primary" :disabled="busy || !ready">保存 Agent 运行草稿</button>
      </form>
      <div>
        <h3>执行记录</h3>
        <label v-if="runs.length">查看 Agent 运行<select :value="runId" :disabled="busy" @change="run(()=>open(($event.target as HTMLSelectElement).value))">
          <option v-for="item in runs" :key="item.id" :value="item.id">{{labels[item.workflow]}} · {{status[item.status]}} · {{item.goal.slice(0,32)}}</option>
        </select></label>
        <p v-if="!active" class="hint">从固定输入准备一次运行。</p>
        <template v-else>
          <p role="status"><strong>{{status[active.status]}}</strong> · {{active.goal}}</p>
          <SpecReference :project-id="projectId" :version-id="active.production_spec_version_id" />
          <p v-for="item in [active.inputs?.source,active.inputs?.series,active.inputs?.timeline].filter(Boolean)" :key="item!.title" class="hint">{{item!.title}} · v{{item!.version}}</p>
          <ol class="agent-steps">
            <li v-for="item in active.steps" :key="item.id">
              <div class="agent-step"><strong>{{item.label}}</strong><span>{{resultTitle(item)}}<template v-if="item.attempt"> · {{item.progress}}% · {{item.elapsed_seconds?.toFixed(1)}} 秒 · 尝试 {{item.attempt}}</template></span></div>
              <p class="hint">{{item.input}} → {{item.output}} · {{item.permission}}</p>
              <p v-if="item.error" class="error">{{item.error}}</p>
              <details v-if="item.result">
                <summary>查看 {{item.label}} 结果</summary>
                <pre>{{JSON.stringify(item.result.result,null,2)}}</pre>
              </details>
            </li>
          </ol>
          <p v-if="active.approval" class="hint">审批意见 · {{active.approval.note}}</p>
          <p v-if="active.review" class="hint">审核意见 · {{active.review.note}}</p>
          <details>
            <summary>查看固定输入与输出哈希</summary>
            <dl class="agent-hashes"><dt>输入 SHA-256</dt><dd>{{active.input_sha256}}</dd>
              <template v-if="active.output_sha256"><dt>输出 SHA-256</dt><dd>{{active.output_sha256}}</dd></template>
            </dl>
          </details>
          <p v-if="active.status==='awaiting_review' && !active.output_sha256" role="alert" class="error">角色输出完整性校验失败，无法审核。</p>
          <label v-if="active.status==='awaiting_approval' || active.status==='awaiting_review'">Agent 审批或审核意见<textarea v-model="note" maxlength="2000"></textarea></label>
          <div class="actions">
            <button v-if="active.status==='awaiting_approval'" class="primary" type="button" :disabled="busy || !note.trim()" @click="run(()=>action('approve'))">批准并排队</button>
            <template v-if="active.status==='awaiting_review'">
              <button class="primary" type="button" :disabled="busy || !note.trim() || !active.output_sha256" @click="run(()=>action('review','accepted'))">确认 Agent 输出</button>
              <button type="button" :disabled="busy || !note.trim() || !active.output_sha256" @click="run(()=>action('review','rejected'))">退回 Agent 输出</button>
            </template>
            <button v-if="active.status==='failed'" type="button" :disabled="busy" @click="run(()=>action('retry'))">重试失败步骤</button>
            <button v-if="canCancel" type="button" :disabled="busy" @click="run(()=>action('cancel'))">取消 Agent 运行</button>
          </div>
        </template>
      </div>
    </div>
  </div>
</template>

<style scoped>
.agent-workspace > p {margin:0 0 12px}
.agent-columns {display:grid;grid-template-columns:minmax(0,.85fr) minmax(0,1.15fr);gap:18px}
.agent-columns > * {min-width:0}
.agent-columns form > label,.agent-columns form > details {margin:10px 0}
.agent-steps {padding-inline-start:24px}
.agent-steps li {padding:8px 0;border-bottom:1px solid var(--line)}
.agent-steps p {margin:3px 0}
.agent-step {display:flex;justify-content:space-between;gap:8px}
.agent-step span {color:var(--ink-muted);font-size:12px}
.agent-steps pre {white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}
.agent-hashes dd {margin:0 0 6px;overflow-wrap:anywhere;font-family:monospace}
@media(max-width:740px) {.agent-columns {grid-template-columns:minmax(0,1fr)}}
</style>
