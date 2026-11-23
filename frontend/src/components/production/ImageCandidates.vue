<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { api, post } from '../../services/api'
import type { VersionRef } from '../../types/workbench'
import type { ProductionSpecRef } from '../../types/productionSpec'
import SpecPicker from './SpecPicker.vue'
import SpecReference from './SpecReference.vue'
import WorkspacePanel from '../ui/WorkspacePanel.vue'

interface Reference {id:string; name:string; sha256:string}
interface ImageRun {
  id:string; mode:'mock'|'openai'; model:string|null; status:string; progress:number; error_code:string|null
  source: {id:string; title:string; version:number}; shot_id:string|null; references:Reference[]
  production_spec:ProductionSpecRef; checks:string[]; input_sha256:string; actual_cost_micros:number|null
  billing:{state?:string; currency?:string; reserved_micros?:number}
  output:{width?:number; height?:number; sha256?:string; review?:{request:{decision:'approved'|'rejected'; note:string};reference:Reference|null};
    adoption?:{asset_id:string; title:string}}
}
interface Capability {live_available:boolean; reason:string|null; quote:{model:string; currency:string; upper_bound_micros:number}|null}
const props=defineProps<{projectId:string; initialPlan?:string; initialShot?:string; initialTask?:string}>()
const emit=defineEmits<{assetsChanged:[]}>()
const root=`/generation/projects/${props.projectId}/images`
const statuses:Record<string,string>={queued:'已排队',running:'处理中',succeeded:'技术检查通过',failed:'失败',cancelled:'已取消'}
const checkLabels:Record<string,string>={identity:'角色身份符合固定设定',wardrobe:'服装符合固定设定',style:'画风符合制作规格',
  scene:'场景符合固定设定',shot:'内容符合镜头合同'}
const anchor=ref(props.initialPlan && props.initialShot ? 'shot' : 'asset')
const source=ref(anchor.value==='shot' ? props.initialPlan || '' : ''), shot=ref(props.initialShot || '')
const specId=ref<string|null>(null), prompt=ref(''), mode=ref<'mock'|'openai'>('mock'), consent=ref(false)
const characters=ref<VersionRef[]>([]), scenes=ref<VersionRef[]>([]), plans=ref<VersionRef[]>([])
const capabilities=ref<Capability|null>(null), runs=ref<ImageRun[]>([]), selected=ref('')
const current=computed(()=>runs.value.find(run=>run.id===selected.value))
const reference=ref(''), confirmed=ref<string[]>([]), note=ref(''), title=ref('')
const decision=ref<'approved'|'rejected'>('approved'), busy=ref(false), error=ref('')
const invoiceAmount=ref<number|null>(null), invoiceEvidence=ref('')
const quote=computed(()=>capabilities.value?.quote)
const selectedRef=computed(()=>current.value?.references.find(item=>item.id===reference.value))
const sourceOptions=computed(()=>anchor.value==='shot' ? plans.value : [...characters.value,...scenes.value])
const terminal=(run:ImageRun)=>!['queued','running'].includes(run.status)
const hasCurrentOutput=computed(()=>current.value?.status==='succeeded' && current.value.output.sha256)
const canSubmit=computed(()=>specId.value && source.value && prompt.value.trim() && (anchor.value!=='shot' || shot.value.trim())
  && (mode.value==='mock' || (quote.value && consent.value)))
const canReview=computed(()=>note.value.trim() && (decision.value==='rejected' || (!!current.value
  && confirmed.value.length===current.value.checks.length && (!current.value.references.length || reference.value))))
const displayCost=(value:number, currency:string)=>`${(value/1_000_000).toFixed(6).replace(/\.?0+$/,'')} ${currency}`
let timer:ReturnType<typeof setInterval>|undefined, reading=false, disposed=false
let last={signature:'',key:''}
let revision=0

function open(run:ImageRun) {
  selected.value=run.id; reference.value=run.output.review?.reference?.id || run.references[0]?.id || ''; confirmed.value=[]
  decision.value='approved';note.value='';title.value=run.mode==='mock' ? `模拟验收 · ${run.source.title}` : run.source.title
  invoiceEvidence.value='';invoiceAmount.value=null
}

async function refresh() {
  if (reading || disposed) return
  reading=true
  const priorRevision=revision
  try {
    const items=await api<ImageRun[]>(root)
    if (props.initialTask && !items.some(run=>run.id===props.initialTask)) {
      items.unshift(await api<ImageRun>(root+'/'+encodeURIComponent(props.initialTask)))
    }
    if(disposed || priorRevision!==revision)return
    runs.value=items
    if(!selected.value && items.length)open(items.find(run=>run.id===props.initialTask) || items[0])
  } finally {reading=false}
}

async function action(work:()=>Promise<void>) {
  busy.value=true;error.value=''
  try {await work()} catch(failure) {error.value=String(failure)} finally {busy.value=false}
}

function store(run:ImageRun) {
  revision++
  const index=runs.value.findIndex(item=>item.id===run.id)
  if(index===-1)runs.value=[run,...runs.value]
  else runs.value.splice(index,1,run)
}

async function queue() {
  const payload={mode:mode.value,spec_version_id:specId.value,source_version_id:source.value,
    shot_id:anchor.value==='shot'?shot.value.trim():null,prompt:prompt.value.trim(),confirm_external_text:mode.value==='openai'&&consent.value}
  const signature=JSON.stringify(payload)
  if(last.signature!==signature)last={signature,key:crypto.randomUUID()}
  const run=await post<ImageRun>(root,{...payload,idempotency_key:last.key})
  store(run);open(run)
}

async function review() {
  const run=current.value!
  store(await post<ImageRun>(root+'/'+run.id+'/review',{decision:decision.value,note:note.value,
    expected_sha256:run.output.sha256,reference_asset_id:reference.value || null,checks:confirmed.value}))
}

async function adopt() {
  const run=current.value!
  store(await post<ImageRun>(root+'/'+run.id+'/adopt',{title:title.value,expected_sha256:run.output.sha256}))
  emit('assetsChanged')
}

async function reconcile() {
  const run=current.value!
  store(await post<ImageRun>(root+'/'+run.id+'/invoice',{actual_cost_micros:invoiceAmount.value,evidence:invoiceEvidence.value}))
}

onMounted(()=>{
  void action(async()=>{
    const list=(kind:string)=>api<{items:VersionRef[]}>(`/projects/${props.projectId}/story/entities?kind=${kind}&limit=100`)
    const [status,people,locations,approved]=await Promise.all([
      api<Capability>(root+'/capabilities'),list('character'),list('scene'),api<VersionRef[]>(`/director/projects/${props.projectId}/batch-options`),
    ])
    capabilities.value=status;characters.value=people.items;scenes.value=locations.items;plans.value=approved
    await refresh()
  })
  timer=setInterval(()=>{
    if(!busy.value && !document.hidden && runs.value.some(item=>!terminal(item)))void refresh().catch(failure=>{error.value=String(failure)})
  },1500)
})
onUnmounted(()=>{disposed=true;clearInterval(timer)})
</script>

<template>
  <WorkspacePanel title="图片候选与内容审核" id="image-candidates">
    <p v-if="error" role="alert" class="error">{{error}}</p>
    <div class="image-workspace">
      <form class="create" @submit.prevent="action(queue)">
        <h3>制作图片候选</h3>
        <label>候选用途<select v-model="anchor" @change="source=''"><option value="asset">人物定妆或场景</option><option value="shot">批准镜头关键帧</option></select></label>
        <SpecPicker v-model="specId" :project-id="projectId" :disabled="busy" />
        <p v-if="!specId" class="hint"><RouterLink :to="{name:'wizard',query:{project:projectId,step:1}}">打开项目制作规格</RouterLink></p>
        <label>图片固定来源<select :value="source" @change="source=($event.target as HTMLSelectElement).value">
          <option value="">选择固定来源版本</option>
          <option v-if="source && !sourceOptions.some(item=>item.version_id===source)" :value="source">历史版本 {{source}}</option>
          <option v-for="item in sourceOptions" :key="item.version_id" :value="item.version_id">{{item.title}} · v{{item.version}}</option>
        </select></label>
        <details><summary>按版本 ID 选择</summary><label>来源版本 ID<input v-model.trim="source" maxlength="36"></label></details>
        <label v-if="anchor==='shot'">图片镜头 ID<input v-model.trim="shot" required maxlength="48"></label>
        <label>图片提示词<textarea v-model="prompt" maxlength="2000" required placeholder="描述画面、人物和动作"></textarea></label>
        <label>图片执行方式<select v-model="mode"><option value="mock">离线模拟 · ¥0</option>
          <option value="openai" :disabled="!capabilities?.live_available">OpenAI 图片</option></select></label>
        <p v-if="mode==='mock'" class="hint">模拟会生成固定色块，用于验证候选流程。</p>
        <p v-if="!capabilities?.live_available" class="hint">{{capabilities?.reason || '正在读取图片授权'}} · 实际费用未知</p>
        <template v-if="mode==='openai' && quote">
          <p class="hint">{{quote.model}} · 最高预留 {{displayCost(quote.upper_bound_micros,quote.currency)}} · 实际费用按账单登记</p>
          <label class="check"><input type="checkbox" v-model="consent">确认发送提示词、画风和制作限制。参考图留在本机。</label>
        </template>
        <button class="primary" :disabled="busy || !canSubmit">提交图片候选</button>
      </form>
      <div class="image-review">
        <h3>候选监看和审核</h3>
        <p v-if="!current" class="hint">先选规格和来源版本，再提交候选。</p>
        <template v-else>
          <label>图片候选记录<select :value="selected" @change="open(runs.find(item=>item.id===($event.target as HTMLSelectElement).value)!)">
            <option v-for="item in runs" :key="item.id" :value="item.id">{{item.source.title}} · {{item.mode==='mock'?'模拟':'OpenAI'}} · {{statuses[item.status]}}</option>
          </select></label>
          <p class="hint" role="status">{{current.mode==='mock'?'离线模拟':'OpenAI 图片'}} · {{statuses[current.status]}}
            <template v-if="!terminal(current)"> · {{current.progress}}%</template>
            · {{current.actual_cost_micros===null?'实际费用未知':displayCost(current.actual_cost_micros,current.billing.currency || 'CNY')}}</p>
          <SpecReference :project-id="projectId" :version-id="current.production_spec.id" />
          <p v-if="current.error_code" class="error">{{current.error_code}}<span v-if="current.billing.state==='awaiting_invoice'"> · 预算仍占用，请核对账单</span></p>
          <div v-if="!terminal(current)" class="actions"><button :disabled="busy" @click="action(async()=>{await post('/tasks/'+current!.id+'/cancel');await refresh()})">取消图片任务</button></div>
          <button v-if="current.mode==='mock' && ['failed','cancelled'].includes(current.status)" :disabled="busy"
             @click="action(async()=>{await post('/tasks/'+current!.id+'/retry');await refresh()})">重试模拟任务</button>
          <template v-if="hasCurrentOutput">
            <label v-if="current.references.length">对照的固定参考图<select v-model="reference" :disabled="!!current.output.review">
              <option v-for="item in current.references" :key="item.id" :value="item.id">{{item.name}}</option>
            </select></label>
            <div class="image-pair" :class="{paired:selectedRef}">
              <figure v-if="selectedRef"><img :src="`/api/assets/${selectedRef.id}/media`" alt="固定参考图"><figcaption>固定参考</figcaption></figure>
              <figure><img :src="`/api${root}/${current.id}/file`" alt="图片候选"><figcaption>{{current.mode==='mock'?'模拟验收图':'候选原图'}} · {{current.output.width}} × {{current.output.height}}</figcaption></figure>
            </div>
            <form v-if="!current.output.review" class="create" @submit.prevent="action(review)">
              <label>图片审核决定<select v-model="decision"><option value="approved">通过</option><option value="rejected">退回</option></select></label>
              <fieldset v-if="decision==='approved'"><legend>人工内容核对</legend>
                <label class="check" v-for="key in current.checks" :key="key"><input type="checkbox" :value="key" v-model="confirmed">{{checkLabels[key]}}</label>
              </fieldset>
              <label>图片审核意见<textarea v-model="note" required maxlength="2000"></textarea></label>
              <button :disabled="busy || !canReview">保存图片审核</button>
            </form>
            <p v-else role="status">{{current.output.review.request.decision==='approved'?'图片审核通过':'图片审核退回'}} · {{current.output.review.request.note}}</p>
            <form v-if="current.output.review?.request.decision==='approved' && !current.output.adoption" class="create" @submit.prevent="action(adopt)">
              <label>图片入库标题<input v-model="title" required maxlength="200"></label>
              <button class="primary" :disabled="busy || !title.trim()">采纳为图片素材</button>
            </form>
            <p v-if="current.output.adoption" role="status">已入库 · {{current.output.adoption.title}}</p>
          </template>
          <form v-if="terminal(current) && current.billing.state==='awaiting_invoice'" class="create" @submit.prevent="action(reconcile)">
            <label>图片账单实际金额（{{current.billing.currency}} micros）<input v-model.number="invoiceAmount" type="number" min="0" max="1000000000000" required></label>
            <label>图片账单凭证<textarea v-model="invoiceEvidence" maxlength="2000" required></textarea></label>
            <button :disabled="busy || !invoiceEvidence.trim()">登记图片账单</button>
          </form>
        </template>
      </div>
    </div>
  </WorkspacePanel>
</template>

<style scoped>
#image-candidates {scroll-margin-top:78px}
.image-workspace {display:grid;grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr);gap:24px}
.image-workspace > * {min-width:0}
.image-workspace h3 {margin:0 0 9px;font-size:14px}
.image-workspace .hint {margin:4px 0}
.image-review .create {margin-top:12px}
.image-pair {display:grid;gap:10px;margin:10px 0;grid-template-columns:minmax(0,1fr)}
.image-pair.paired {grid-template-columns:repeat(2,minmax(0,1fr))}
.image-pair figure {margin:0;background:var(--surface-raised);border:1px solid var(--line);border-radius:8px;overflow:hidden}
.image-pair img {display:block;width:100%;height:230px;object-fit:contain}
.image-pair figcaption {padding:6px 8px;color:var(--ink-muted);font-size:12px}
@media(max-width:830px) {.image-workspace {grid-template-columns:minmax(0,1fr);gap:18px}.image-pair img {height:160px}}
</style>
