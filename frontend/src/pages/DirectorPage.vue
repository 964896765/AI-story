<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowRight, Check, ClipboardCheck } from 'lucide-vue-next'
import WorkspacePanel from '../components/ui/WorkspacePanel.vue'
import DirectorBatchFields, { type BatchOperation, type RunOption } from '../components/production/DirectorBatchFields.vue'
import DirectorAdvice from '../components/production/DirectorAdvice.vue'
import SpecReference from '../components/production/SpecReference.vue'
import { useWorkspace } from '../router/workspace'
import type { Destination } from '../router/navigation'
import { api, post } from '../services/api'
import type { Task, VersionRef } from '../types/workbench'

const { workbench, link, go } = useWorkspace()
const workflows = {
  revision:{label:'剧情与版本审核',page:'adaptation',steps:['选择小说或剧本的固定版本','核对改编目标和预算','审核候选改编稿并保存新版本']},
  repair:{label:'镜头质检与返工',page:'guardian',steps:['检查已批准的故事圣经和镜头合同','定位证据，比较受影响的镜头','重新审批变更后处理候选']},
  render:{label:'固定时间轴渲染',page:'timeline',steps:['核对固定时间轴版本和素材','批准后提交本机 Worker 合成','预览或下载已验证成片']},
  batch:{label:'整剧生产与分集返工',page:'production',steps:['核对各集时间轴与复用结果','批准渲染和技术质检','在生产调度查看复核、返工和交付']},
  release:{label:'授权与交付',page:'library',steps:['核对已通过质检的整剧批次','检查素材授权、平台和地域','批准后创建并校验交付包']},
} as const satisfies Record<string,{label:string;page:Destination;steps:readonly string[]}>
type Workflow = keyof typeof workflows
interface Plan { intent:Workflow; instruction:string; confirmed:boolean }
interface BatchPreview extends VersionRef { number:number; mode:'render'|'reuse'|'recheck' }
interface BatchResult {
  id:string;status:string;passed:number;episode_count:number
  episodes:{number:number;status:string;render_status:string;qc_status:string;issue_count:number}[]
}
type SavedPlan = {
  id:string
  instruction:string
  run_id:string|null
  run:BatchResult|null
  preview:BatchPreview[]|null
  created_at:string
  approved_at:string|null
  input_hash:string
  production_spec_version_id?:string|null
  external_cost_cents:number
  task:Pick<Task,'id'|'status'|'stage'|'progress'|'elapsed_seconds'|'error'>|null
} & ({ action:'render';parameters:{version_id:string} }
  | { action:'release';parameters:{run_id:string;title:string;platform:string;region:string} }
  | { action:'batch';parameters:Omit<BatchOperation,'action'> })
interface TimelineEntity extends VersionRef { id:string }
const states:Record<string,string> = {queued:'排队中',running:'处理中',succeeded:'处理成功',failed:'处理失败',cancelled:'已取消'}
const batchStates:Record<string,string> = {processing:'批次执行中',passed:'质检通过',needs_review:'待人工复核',needs_rework:'需返工',cancelled:'已停止'}
const episodeModes = {render:'渲染并质检',reuse:'复用成片和质检',recheck:'复用成片并复检'}
const stages:Record<string,string> = {queued:'等待领取',recovered:'中断恢复',inspecting:'检查输入',
  encoding:'编码',validating:'验证产物',publishing:'保存产物',retry_wait:'等待自动重试',
  succeeded:'完成',failed:'失败',cancelled:'已取消'}
const storageKey = `ai-story:director:${workbench.projectId}`

function readPlan(): Plan|null {
  try {
    const value=JSON.parse(localStorage.getItem(storageKey) || 'null')
    return value && Object.hasOwn(workflows,value.intent) && typeof value.instruction==='string' ? value : null
  } catch { return null }
}
const plan=ref<Plan|null>(readPlan())
const instruction=ref(plan.value?.instruction || ''), target=ref<Workflow>(plan.value?.intent || 'repair')
const status=ref('')
const error=ref('')
const connectionError=ref('')
const saved=ref<SavedPlan[]>([])
const selectedId=ref('')
const active=computed(()=>saved.value.find(item=>item.id===selectedId.value))
const adviceOptions=computed(()=>saved.value.filter(item=>!item.approved_at).map(item=>({
  id:item.id,title:workflows[item.action].label,instruction:item.instruction,
})))
const planHeading=ref<HTMLElement|null>(null)
const timelines=ref<TimelineEntity[]>([])
const versions=ref<VersionRef[]>([])
const runs=ref<RunOption[]>([])
const releaseRuns=computed(()=>runs.value.filter(item=>item.status==='passed'))
const batchOperation=ref<BatchOperation|null>(null)
const timelineId=ref(''), versionId=ref(''), runId=ref('')
const packageTitle=ref(''), platform=ref(''), region=ref('CN')
const loading=ref(false), busy=ref(false)
const executable=computed(()=>['render','release','batch'].includes(target.value))
const root=computed(()=>`/director/projects/${workbench.projectId}/plans`)
const abort = new AbortController()
let request = { signature:'', key:'' }
const focus=computed(()=>plan.value ? workflows[plan.value.intent] : null)
const batch=computed(()=>workbench.overview?.latest_run)
const routeParams=computed(()=>plan.value?.intent==='release' && batch.value?.status==='passed' ? {run:batch.value.id} : {})
const unchanged=computed(()=>plan.value?.instruction===instruction.value.trim() && plan.value?.intent===target.value)

function persist(value: Plan) {
  plan.value=value
  try { localStorage.setItem(storageKey,JSON.stringify(value)); status.value=value.confirmed?'已在本机保存确认记录。':'已在本机保存执行计划。' }
  catch { status.value='浏览器存储不可用，本次计划保存在当前页面。' }
}
function prepare() {
  const text=instruction.value.trim()
  if (!text || !workbench.projectId) return
  persist({intent:target.value,instruction:text,confirmed:false})
}
async function handoff() {
  if (!plan.value || !focus.value || !unchanged.value) return
  persist({...plan.value,confirmed:true})
  await go(focus.value.page,routeParams.value)
}

function record(value: SavedPlan) {
  const index = saved.value.findIndex(item=>item.id===value.id)
  if (index < 0) saved.value.unshift(value)
  else saved.value[index] = value
}

async function inspectAdvicePlan(id:string) {
  error.value=''
  try {
    const item=await api<SavedPlan>(`${root.value}/${id}`,{signal:abort.signal})
    if (abort.signal.aborted) return
    record(item)
    selectedId.value=id
    await nextTick()
    planHeading.value?.focus()
  } catch (failure) { if (!abort.signal.aborted) error.value=String(failure) }
}

watch(() => workbench.projectId, async (project, _, onCleanup) => {
  const controller = new AbortController()
  onCleanup(()=>controller.abort())
  if (!project) return
  loading.value=true
  connectionError.value=''
  const options={signal:controller.signal}
  const result=await Promise.allSettled([
    api<SavedPlan[]>(root.value, options),
    api<{items:TimelineEntity[]}>(`/projects/${project}/story/entities?kind=timeline`, options),
    api<RunOption[]>(`/production/projects/${project}/runs`, options),
  ])
  if (controller.signal.aborted) return
  const [history, edit, production]=result
  if (history.status==='fulfilled') {
    saved.value=history.value
    if (history.value.length) selectedId.value=history.value[0]!.id
  }
  if (edit.status==='fulfilled') timelines.value=edit.value.items
  if (production.status==='fulfilled') runs.value=production.value
  connectionError.value=result.filter(item=>item.status==='rejected').map(item=>String(item.reason)).join('；')
  loading.value=false
}, { immediate:true })

watch(timelineId, async (id, _, onCleanup) => {
  versions.value=[]
  versionId.value=''
  if (!id) return
  const controller = new AbortController()
  onCleanup(()=>controller.abort())
  try {
    const history=await api<VersionRef[]>(`/story/entities/${id}/versions`, {signal:controller.signal})
    if (controller.signal.aborted) return
    versions.value=history
    versionId.value=history[0]?.version_id || ''
  } catch (failure) {
    if (!controller.signal.aborted) error.value=String(failure)
  }
})

const executionState=computed(()=>active.value?.run?.status || active.value?.task?.status)
const runNeedsDetails=computed(()=>Boolean(active.value?.run_id && !active.value.run))
const inProgress=(state:string|undefined)=>['queued','running','processing'].includes(state || '')
watch([selectedId, executionState, runNeedsDetails], ([id, state, loadRun], _, onCleanup) => {
  if (!id || (!loadRun && !inProgress(state))) return
  const path=`${root.value}/${id}`
  const controller=new AbortController()
  let timer:ReturnType<typeof setTimeout>
  onCleanup(()=>{controller.abort();clearTimeout(timer)})
  async function poll() {
    try {
      const result=await api<SavedPlan>(path,{signal:controller.signal})
      if (!controller.signal.aborted) { record(result); connectionError.value='' }
    } catch (failure) {
      if (!controller.signal.aborted) connectionError.value=String(failure)
    }
    if (!controller.signal.aborted && (runNeedsDetails.value || inProgress(executionState.value))) timer=setTimeout(poll,1500)
  }
  timer=setTimeout(poll,loadRun ? 0 : 1500)
})

watch(target, async (value, _, onCleanup) => {
  if (!workbench.projectId || !['batch','release'].includes(value)) return
  const controller=new AbortController()
  onCleanup(()=>controller.abort())
  try {
    const result=await api<RunOption[]>(`/production/projects/${workbench.projectId}/runs`,{signal:controller.signal})
    if (!controller.signal.aborted) runs.value=result
  } catch (failure) {
    if (!controller.signal.aborted) connectionError.value=String(failure)
  }
})

async function submit() {
  error.value=''
  if (!executable.value) { selectedId.value=''; prepare(); return }
  const operation=target.value==='render'
    ? {action:'render',version_id:versionId.value}
    : target.value==='batch' ? batchOperation.value
      : {action:'release',run_id:runId.value,title:packageTitle.value.trim(),platform:platform.value.trim(),region:region.value.trim().toUpperCase()}
  if (!operation) return
  const body={instruction:instruction.value.trim(),operation}
  const signature=JSON.stringify(body)
  if (request.signature!==signature) request={signature,key:crypto.randomUUID()}
  busy.value=true
  try {
    const result=await post<SavedPlan>(root.value,{...body,idempotency_key:request.key})
    if (abort.signal.aborted) return
    record(result)
    selectedId.value=result.id
    status.value=''
    request={signature:'',key:''}
  } catch (failure) { error.value=String(failure) }
  finally { busy.value=false }
}

async function execute(item:SavedPlan) {
  busy.value=true
  error.value=''
  try {
    const result=await post<SavedPlan>(`${root.value}/${item.id}/execute`)
    if (!abort.signal.aborted) record(result)
  } catch (failure) { error.value=String(failure) }
  finally { busy.value=false }
}
onBeforeUnmount(()=>abort.abort())
</script>

<template>
  <section v-if="!workbench.projectId">
    <h2>先建立制作项目</h2>
    <p>在项目说明写入原创创意或改编目标。进入项目后可把它带入制作指令。</p>
    <RouterLink :to="link('assets',{create:'1',flow:1})">新建制作项目</RouterLink>
  </section>
  <div v-else class="director-grid">
    <WorkspacePanel title="导演对话">
      <div v-if="plan && !active" class="dialogue"><div><strong>制作指令</strong><p>{{plan.instruction}}</p></div><div><strong>执行计划已准备</strong><p>{{focus?.label}} · {{plan.confirmed?'已确认交接':'待确认'}}</p></div></div>
      <p v-else class="hint">先选工作流，再填写目标、集数、画幅和审核要求。本机按所选工作流整理步骤，生产须经人工确认。</p>
      <form class="director-form" @submit.prevent="submit">
        <fieldset class="director-form" :disabled="busy">
        <label>制作指令<textarea v-model="instruction" required maxlength="4000" placeholder="例如先试制第 1 集，90 秒、竖屏，角色形象需先确认"></textarea></label>
        <button v-if="workbench.project?.description && !instruction.trim()" type="button" @click="instruction=workbench.project.description.slice(0,4000)">引用项目说明</button>
        <label>工作流<select v-model="target"><option v-for="(item,key) in workflows" :key="key" :value="key">{{item.label}}</option></select></label>
        <template v-if="target==='render'">
          <label>时间轴<select v-model="timelineId" required><option value="" disabled>{{ loading?'读取中…':timelines.length?'选择时间轴':'暂无时间轴' }}</option><option v-for="item in timelines" :key="item.id" :value="item.id">{{item.title}}</option></select></label>
          <label>固定时间轴版本<select v-model="versionId" required><option v-for="item in versions" :key="item.version_id" :value="item.version_id">v{{item.version}} · {{item.title}}</option></select></label>
        </template>
        <template v-if="target==='release'">
          <label>已通过质检的批次<select v-model="runId" required><option value="" disabled>{{ loading?'读取中…':releaseRuns.length?'选择批次':'暂无通过批次' }}</option><option v-for="item in releaseRuns" :key="item.id" :value="item.id">{{ new Date(item.created_at).toLocaleString() }} · {{item.episode_count}} 集 · {{item.id.slice(0,8)}}</option></select></label>
          <label>交付包标题<input v-model="packageTitle" required maxlength="180"></label>
          <label>目标平台标识<input v-model="platform" required pattern="[a-z0-9_\-]+" maxlength="40"></label>
          <label>目标地域<input v-model="region" required maxlength="5"></label>
        </template>
        <DirectorBatchFields v-if="target==='batch'" v-model="batchOperation" :project-id="workbench.projectId" :runs="runs" />
        <button type="submit" class="primary" :disabled="!instruction.trim() || (target==='render' && !versionId) || (target==='release' && !runId) || (target==='batch' && !batchOperation)">生成执行计划</button>
        </fieldset>
      </form>
      <label v-if="saved.length" class="director-history">项目计划记录<select v-model="selectedId"><option value="">选择计划</option><option v-for="item in saved" :key="item.id" :value="item.id">{{workflows[item.action].label}} · {{new Date(item.created_at).toLocaleString()}} · {{item.id.slice(0,8)}}</option></select></label>
    </WorkspacePanel>
    <WorkspacePanel title="执行计划">
      <template v-if="active">
        <div ref="planHeading" tabindex="-1" class="director-note"><ClipboardCheck :size="17" aria-hidden="true" /><strong>{{workflows[active.action].label}}</strong><span data-testid="director-plan-status">{{active.run ? batchStates[active.run.status] : active.task ? states[active.task.status] : active.approved_at ? '正在读取批次' : '待批准'}}</span></div>
        <p class="director-instruction">{{active.instruction}}</p>
        <SpecReference :project-id="workbench.projectId" :version-id="active.production_spec_version_id" />
        <dl class="director-facts">
          <div v-if="active.action==='render'"><dt>时间轴版本</dt><dd><RouterLink :to="link('timeline',{timeline:active.parameters.version_id})">{{active.parameters.version_id}}</RouterLink></dd></div>
          <template v-else-if="active.action==='release'">
            <div><dt>整剧批次</dt><dd><RouterLink :to="link('production',{run:active.parameters.run_id})">{{active.parameters.run_id}}</RouterLink></dd></div>
            <div><dt>交付包</dt><dd>{{active.parameters.title}}</dd></div>
            <div><dt>授权范围</dt><dd>{{active.parameters.platform}} · {{active.parameters.region}}</dd></div>
          </template>
          <template v-else>
            <div><dt>批准的制作计划</dt><dd><RouterLink :to="link('bible',{version:active.parameters.plan_version_id})">{{active.parameters.plan_version_id}}</RouterLink></dd></div>
            <div v-if="active.parameters.previous_run_id"><dt>原批次</dt><dd><RouterLink :to="link('production',{run:active.parameters.previous_run_id})">{{active.parameters.previous_run_id}}</RouterLink></dd></div>
            <div><dt>质检要求</dt><dd>{{active.parameters.policy.require_audio?'必须有音轨':'检查已有音轨'}} · {{active.parameters.policy.require_subtitles?'必须有字幕':'检查已有字幕'}}</dd></div>
            <div v-if="active.parameters.policy.dialogue_asr_language"><dt>对白听写</dt><dd>{{active.parameters.policy.dialogue_asr_language}}</dd></div>
          </template>
          <div><dt>外部模型费用</dt><dd>¥{{(active.external_cost_cents/100).toFixed(2)}}</dd></div>
          <div v-if="active.approved_at"><dt>批准时间</dt><dd>{{new Date(active.approved_at).toLocaleString()}}</dd></div>
          <div v-if="active.task"><dt>阶段 / 耗时</dt><dd>{{stages[active.task.stage] || active.task.stage}} · {{active.task.elapsed_seconds.toFixed(1)}} 秒</dd></div>
        </dl>
        <ul v-if="active.preview" class="director-episodes" aria-label="分集执行清单">
          <li v-for="episode in active.preview" :key="episode.number">
            <div><strong>第 {{episode.number}} 集</strong> <RouterLink :to="link('timeline',{timeline:episode.version_id})">{{episode.title}} · v{{episode.version}}</RouterLink></div>
            <span>{{episodeModes[episode.mode]}}</span>
          </li>
        </ul>
        <details class="hint"><summary>审核输入指纹</summary><code class="director-fingerprint">{{active.input_hash}}</code></details>
        <ol class="director-steps"><li v-for="step in workflows[active.action].steps" :key="step">{{step}}</li></ol>
        <button v-if="!active.approved_at" class="primary director-cta" type="button" :disabled="busy" @click="execute(active)"><Check :size="15" aria-hidden="true" />批准并执行</button>
        <template v-else-if="active.task">
          <progress :value="active.task.progress" max="100" aria-label="任务进度">{{active.task.progress}}%</progress>
          <p v-if="active.task.error" class="error" role="alert">{{active.task.error}}</p>
          <div v-if="active.task.status==='succeeded'" class="director-output">
            <template v-if="active.action==='render'">
              <video :key="active.task.id" :src="`/api/tasks/${active.task.id}/output`" controls preload="metadata" aria-label="总导演成片预览"></video>
              <a :href="`/api/tasks/${active.task.id}/output?download=true`">下载成片</a>
            </template>
            <a v-else :href="`/api/delivery/packages/${active.task.id}/file`">下载交付包</a>
          </div>
          <RouterLink v-if="active.action==='release'" :to="link('library',{run:active.parameters.run_id})">查看交付工作区</RouterLink>
          <RouterLink v-else :to="link('production')">查看生产队列</RouterLink>
        </template>
        <template v-else-if="active.run">
          <p role="status">已通过 {{active.run.passed}} / {{active.run.episode_count}} 集</p>
          <ul class="director-episodes" aria-label="分集执行状态">
            <li v-for="item in active.run.episodes" :key="item.number">
              <RouterLink :to="link('production',{run:active.run.id,episode:String(item.number)})">第 {{item.number}} 集</RouterLink>
              <span>{{batchStates[item.status]}}<template v-if="item.status==='processing'"> · 渲染 {{states[item.render_status]}} · 质检 {{states[item.qc_status]}}</template><template v-if="item.issue_count"> · {{item.issue_count}} 项发现</template></span>
            </li>
          </ul>
          <div class="actions">
            <RouterLink :to="link('production',{run:active.run.id})">查看生产批次</RouterLink>
            <RouterLink v-if="active.run.status==='passed'" :to="link('library',{run:active.run.id})">打开授权交付</RouterLink>
          </div>
        </template>
      </template>
      <template v-else-if="plan && focus">
        <div class="director-note"><ClipboardCheck :size="17" aria-hidden="true" /><strong>{{focus.label}}</strong><span>{{ plan.confirmed?'已确认':'待确认' }}</span></div>
        <ol class="director-steps"><li v-for="step in focus.steps" :key="step">{{step}}</li></ol>
        <p class="hint" v-if="!unchanged">指令已有修改，请先更新执行计划。</p>
        <div class="actions">
          <RouterLink v-if="plan.intent==='repair'" :to="link('guardian')">查看影响分析</RouterLink>
          <button class="primary director-cta" type="button" :disabled="!unchanged" @click="handoff"><Check :size="15" aria-hidden="true" />确认并打开工作区 <ArrowRight :size="14" aria-hidden="true" /></button>
        </div>
      </template>
      <p v-else class="empty">提交制作指令后可核对执行步骤。</p>
      <p v-if="status" class="hint" role="status">{{status}}</p>
      <p v-if="error || connectionError" class="error" role="alert">{{error || connectionError}}</p>
    </WorkspacePanel>
    <WorkspacePanel title="项目约束与预算">
      <dl class="director-facts">
        <div><dt>当前项目</dt><dd>{{workbench.project?.name}}</dd></div>
        <div><dt>故事圣经</dt><dd>{{workbench.overview ? (workbench.overview.story_counts.story_bible || 0) : '待读取'}}</dd></div>
        <div><dt>最近批次</dt><dd>{{batch?`${batch.passed} / ${batch.episode_count} 集通过`:'暂无'}}</dd></div>
        <div><dt>付费调用授权</dt><dd>{{workbench.overview ? (workbench.overview.live_authorized?'已授权':'关闭'):'待读取'}}</dd></div>
      </dl>
      <RouterLink :to="link('models',{flow:3})">配置 Codex、模型与预算</RouterLink>
      <a class="advice-anchor" href="#director-model-planning">打开模型规划</a>
      <p class="director-note director-mode">渲染和交付由本机 Worker 执行。剧情改编与镜头返工在对应工作区审核。</p>
    </WorkspacePanel>
    <WorkspacePanel id="director-model-planning" class="director-advice" title="模型规划（离线模拟）">
      <DirectorAdvice :key="workbench.projectId" :project-id="workbench.projectId" :options="adviceOptions" @inspect="inspectAdvicePlan" />
    </WorkspacePanel>
  </div>
</template>

<style scoped>
.director-grid { display:grid;grid-template-columns:minmax(210px,.95fr) minmax(260px,1.28fr) minmax(185px,.85fr);gap:14px;align-items:start }
.director-advice { grid-column:1/-1;scroll-margin-top:75px }
.advice-anchor { display:block;margin-top:7px }
.dialogue,.director-form { display:grid;gap:10px }
.director-form fieldset { border:0;padding:0;margin:0;min-width:0 }
.director-history,.director-output { display:grid;gap:8px;margin-top:14px }
.director-output video,.director-grid progress { width:100% }
.director-output video { max-height:260px;background:#10121a }
.director-instruction { white-space:pre-wrap;overflow-wrap:anywhere }
.director-fingerprint { overflow-wrap:anywhere }
.director-episodes { list-style:none;padding:0;margin:10px 0 14px }
.director-episodes li { display:flex;justify-content:space-between;gap:10px;padding:8px 0;border-bottom:1px solid var(--line);font-size:12px }
.director-episodes li div { overflow-wrap:anywhere }
.director-episodes li span { text-align:right;color:var(--ink-muted) }
.dialogue { margin-bottom:13px }
.dialogue>div,.director-note { background:var(--surface-raised);border:1px solid var(--line);border-radius:11px;padding:12px;font-size:12px }
.dialogue>div:first-child { background:var(--accent-surface);margin-left:16px }
.dialogue p { margin:4px 0 0;white-space:pre-wrap }
.director-note { display:flex;align-items:center;gap:7px;background:var(--accent-surface);color:var(--ink) }
.director-note span { margin-left:auto;color:var(--accent);font-size:11px }
.director-mode { margin:11px 0 0 }
.director-steps { padding-left:22px;margin:9px 0 14px }
.director-steps li { padding:11px 0;border-bottom:1px solid var(--line);font-size:12px }
.director-cta { display:inline-flex;gap:6px;align-items:center }
.director-facts { margin:0 0 12px }
.director-facts div { display:grid;grid-template-columns:.85fr 1fr;gap:8px;padding:8px 0;border-bottom:1px solid var(--line);font-size:12px }
.director-facts dt { color:var(--ink-muted) }
.director-facts dd { margin:0;text-align:right;overflow-wrap:anywhere }
@media(max-width:1100px) { .director-grid { grid-template-columns:repeat(2,minmax(0,1fr)) } }
@media(max-width:700px) { .director-grid { grid-template-columns:minmax(0,1fr) } }
</style>
