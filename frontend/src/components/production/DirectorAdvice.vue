<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { api, post } from '../../services/api'
import { useWorkspace } from '../../router/workspace'

interface Option { id:string; title:string; instruction:string }
interface Provider { id:string; label:string; kind:string; enabled:boolean; settings:{model:string;currency:string} }
interface Budget { mode:string; currency:string; available_micros:number; halted:boolean }
interface Advice {
  id:string; status:string; budget_status:string; simulated:boolean; created_at:string; draft_revision:number
  error_code:string|null; calculated_cost_micros:number|null; provider_snapshot:{label:string;model:string;currency:string}
  request:{goal:string;plan_ids:string[]}
  draft:{choice:number;rationale:string;checks:string[]}|null
  review:{plan_id:string|null;request:{note:string}}|null
}

const props=defineProps<{projectId:string;options:Option[]}>()
const emit=defineEmits<{inspect:[id:string]}>()
const { link }=useWorkspace()
const providers=ref<Provider[]>([]), budgets=ref<Budget[]>([]), calls=ref<Advice[]>([])
const selected=ref(''), providerId=ref(''), goal=ref(''), note=ref('')
const candidates=ref<string[]>([])
const busy=ref(false), loading=ref(true), error=ref(''), pollError=ref('')
const root=`/director/projects/${props.projectId}/advice`
const budgetUrl=`/text/projects/${props.projectId}/budgets`
const active=computed(()=>calls.value.find(item=>item.id===selected.value))
const provider=computed(()=>providers.value.find(item=>item.id===providerId.value))
const budget=computed(()=>budgets.value.find(item=>item.mode==='mock' && item.currency===provider.value?.settings.currency))
const recommendedId=computed(()=>active.value?.draft ? active.value.request.plan_ids[active.value.draft.choice-1] : undefined)
const chosen=computed(()=>props.options.find(item=>item.id===recommendedId.value))
const pending=(status?:string)=>status==='queued'||status==='dispatching'||status==='received'
const labels:Record<string,string>={queued:'等待 Worker',dispatching:'运行模拟适配器',received:'核算和校验',awaiting_review:'待审核',
  accepted:'已采纳建议',rejected:'已退回',failed:'失败',invalid_output:'输出结构不符',cancelled:'已取消',
  unknown:'结果未知',cost_unknown:'用量未知',budget_overrun:'模拟预算已冻结'}
const retryable=computed(()=>active.value && ['failed','cancelled','invalid_output'].includes(active.value.status)
  && ['released','settled'].includes(active.value.budget_status))
const releasable=computed(()=>active.value?.simulated && ['unknown','cost_unknown'].includes(active.value.status))
const amount=(value:number,currency:string)=>`${(value/1_000_000).toFixed(6)} ${currency}`
const lifetime=new AbortController()
let submitKey={signature:'',id:''}
let retryKey={call:'',id:''}

function record(call:Advice) {
  const index=calls.value.findIndex(item=>item.id===call.id)
  if (index<0) calls.value.unshift(call)
  else calls.value[index]=call
}
async function refreshBudget() {
  const result=await api<Budget[]>(budgetUrl,{signal:lifetime.signal})
  if (!lifetime.signal.aborted) budgets.value=result
}
onMounted(async()=>{
  const signal=lifetime.signal
  const result=await Promise.allSettled([api<Advice[]>(root,{signal}),api<Provider[]>('/text/providers',{signal}),refreshBudget()])
  if (signal.aborted) return
  const [history,catalog]=result
  if (history.status==='fulfilled') {
    calls.value=history.value
    selected.value=history.value[0]?.id || ''
  }
  if (catalog.status==='fulfilled') {
    providers.value=catalog.value.filter(item=>item.kind==='mock' && item.enabled)
    providerId.value=providers.value[0]?.id || ''
  }
  error.value=result.filter(item=>item.status==='rejected').map(item=>String(item.reason)).join('；')
  loading.value=false
})
onBeforeUnmount(()=>lifetime.abort())
watch(selected,()=>{note.value='';pollError.value=''})
watch(()=>props.options,rows=>{candidates.value=candidates.value.filter(id=>rows.some(row=>row.id===id))})

watch([selected,()=>active.value?.status],([id,status],_,onCleanup)=>{
  if (!id || !pending(status)) return
  const control=new AbortController()
  let timer:ReturnType<typeof setTimeout>
  onCleanup(()=>{control.abort();clearTimeout(timer)})
  async function poll() {
    try {
      const result=await api<Advice>(`${root}/${id}`,{signal:control.signal})
      if (control.signal.aborted) return
      record(result)
      pollError.value=''
      if (!pending(result.status)) {
        await refreshBudget()
        return
      }
    } catch (failure) {
      if (!control.signal.aborted) pollError.value=String(failure)
    }
    if (!control.signal.aborted && pending(active.value?.status)) timer=setTimeout(poll,1500)
  }
  timer=setTimeout(poll,800)
})

async function act(action:()=>Promise<void>) {
  if (busy.value) return
  busy.value=true; error.value=''
  try { await action() }
  catch (failure) { if (!lifetime.signal.aborted) error.value=String(failure) }
  finally { busy.value=false }
}
function submit() {
  void act(async()=>{
    if (!goal.value.trim() || !providerId.value || !candidates.value.length) return
    const body={goal:goal.value.trim(),provider_id:providerId.value,plan_ids:candidates.value}
    const signature=JSON.stringify(body)
    if (submitKey.signature!==signature) submitKey={signature,id:crypto.randomUUID()}
    const call=await post<Advice>(root,{...body,idempotency_key:submitKey.id})
    record(call);selected.value=call.id
    submitKey={signature:'',id:''}
    await refreshBudget()
  })
}
function control(item:Advice,command:'cancel'|'retry'|'reconcile') {
  void act(async()=>{
    let body
    if (command==='retry') {
      if (retryKey.call!==item.id) retryKey={call:item.id,id:crypto.randomUUID()}
      body={idempotency_key:retryKey.id,acknowledge_new_charge:true}
    }
    if (command==='reconcile') {
      body={resolution:'not_charged',evidence:'操作员确认本次离线模拟在本机执行且无外部实付，释放独立模拟额度。'}
    }
    const call=await post<Advice>(`${root}/${item.id}/${command}`,body)
    record(call);selected.value=call.id
    if (command==='retry') retryKey={call:'',id:''}
    await refreshBudget()
  })
}
function review(item:Advice,action:'accept'|'reject') {
  void act(async()=>{
    const call=await post<Advice>(`${root}/${item.id}/review`,{action,draft_revision:item.draft_revision,note:note.value.trim()})
    record(call)
    if (call.review?.plan_id) emit('inspect',call.review.plan_id)
  })
}
</script>

<template>
  <div class="advice-grid">
    <form class="advice-form" @submit.prevent="submit">
      <p class="hint">勾选最多四个待审批方案。离线模拟用于验证建议与审核流程。</p>
      <label>模拟供应商<select v-model="providerId" required>
        <option value="" disabled>{{loading?'读取中…':'暂无启用的模拟供应商'}}</option>
        <option v-for="item in providers" :key="item.id" :value="item.id">{{item.label}} · {{item.settings.model}}</option>
      </select></label>
      <p v-if="budget" class="hint">模拟可用额 {{amount(budget.available_micros,budget.currency)}}<template v-if="budget.halted"> · 已冻结</template></p>
      <RouterLink v-else :to="link('models')">配置模拟供应商与预算</RouterLink>
      <label>规划目标<textarea v-model="goal" rows="2" maxlength="1000" required></textarea></label>
      <fieldset class="advice-options">
        <legend>可选执行计划</legend>
        <p v-if="!options.length" class="hint">先保存一个渲染、整剧生产或授权交付计划。</p>
        <label v-for="item in options" :key="item.id">
          <input v-model="candidates" type="checkbox" :value="item.id" :disabled="busy || (candidates.length>=4 && !candidates.includes(item.id))">
          <span>{{item.title}} · {{item.instruction.slice(0,120)}}</span>
        </label>
      </fieldset>
      <button type="submit" class="primary" :disabled="busy || !providerId || !goal.trim() || !candidates.length">生成模拟规划建议</button>
    </form>
    <section aria-label="规划建议审核" class="advice-form">
      <label v-if="calls.length">规划建议记录<select v-model="selected" :disabled="busy">
        <option v-for="item in calls" :key="item.id" :value="item.id">{{new Date(item.created_at).toLocaleString()}} · {{labels[item.status] || item.status}} · {{item.request.goal.slice(0,28)}}</option>
      </select></label>
      <template v-if="active">
        <p role="status" data-testid="director-advice-status">{{labels[active.status] || active.status}} · 离线模拟</p>
        <p class="advice-text"><strong>规划目标</strong> · {{active.request.goal}}</p>
        <p class="hint">{{active.provider_snapshot.label}} · {{active.provider_snapshot.model}}<template v-if="active.calculated_cost_micros!==null"> · 模拟核算 {{amount(active.calculated_cost_micros,active.provider_snapshot.currency)}}</template></p>
        <template v-if="active.draft">
          <p><strong>方案 {{active.draft.choice}}</strong><template v-if="chosen"> · {{chosen.title}} · {{chosen.instruction}}</template></p>
          <p class="advice-text">{{active.draft.rationale}}</p>
          <ul><li v-for="(item,index) in active.draft.checks" :key="index">{{item}}</li></ul>
        </template>
        <p v-if="active.error_code" class="error" role="alert">{{active.error_code}}</p>
        <div v-if="active.status==='awaiting_review'" class="advice-form">
          <label>建议审核说明<textarea v-model="note" required maxlength="1000" rows="2"></textarea></label>
          <div class="actions">
            <button type="button" class="primary" :disabled="busy || !note.trim()" @click="review(active,'accept')">采纳建议并查看计划</button>
            <button type="button" :disabled="busy || !note.trim()" @click="review(active,'reject')">退回建议</button>
          </div>
        </div>
        <p v-if="active.review" class="hint">{{active.review.request.note}}</p>
        <button v-if="active.review?.plan_id" type="button" @click="emit('inspect',active.review.plan_id)">查看关联执行计划</button>
        <button v-if="active.status==='queued'" type="button" :disabled="busy" @click="control(active,'cancel')">取消建议任务</button>
        <button v-if="retryable" type="button" :disabled="busy" @click="control(active,'retry')">再次模拟（新调用）</button>
        <button v-if="releasable" type="button" :disabled="busy" @click="control(active,'reconcile')">确认无实付并释放模拟额度</button>
      </template>
      <p v-else class="empty">{{loading?'正在读取规划记录…':'暂无规划建议。'}}</p>
      <p v-if="error || pollError" class="error" role="alert">{{error || pollError}}</p>
    </section>
  </div>
</template>

<style scoped>
.advice-grid { display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:22px }
.advice-form,.advice-options { display:grid;gap:9px;align-content:start;min-width:0 }
.advice-form p,.advice-form ul { margin:0;overflow-wrap:anywhere }
.advice-options { max-height:200px;overflow:auto }
.advice-options label { display:flex;align-items:start;gap:8px;padding:3px 0 }
.advice-options input { width:auto;flex:none }
.advice-text { white-space:pre-wrap }
@media(max-width:700px) { .advice-grid { grid-template-columns:minmax(0,1fr) } }
</style>
