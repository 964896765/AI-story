<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { request, statusLabels } from './analysisApi'

interface Channel {id:string;label:string;platform:string;region:string;verified:boolean;rule_version:number}
interface Delivery {id:string;status:string;parameters:{run_id:string;title:string;platform:string;region:string}}
interface Publication {
  id:string;title:string;channel:Channel;status:string;events:{status:string;evidence:string;created_at:string}[]
}
interface Promo {id:string;title:string;episode:number;status:string;sha256:string|null;error:string|null}
interface Settlement {id:string;channel:string;external_id:string;currency:string;kind:string;status:string;amount_micros:string|null}
interface Total {currency:string;recorded_cash_difference_micros:string;unknown_entries:number;estimate_entries:number;
  unknown_model_charges:number;amounts_micros:Record<string,string>}
const props=defineProps<{projectId:string;initialPackage?:string}>()
const emit=defineEmits<{backToDelivery:[run:string]}>()
const channels=ref<Channel[]>([]), deliveries=ref<Delivery[]>([]), publications=ref<Publication[]>([]), promos=ref<Promo[]>([])
const ledger=ref<Settlement[]>([]), totals=ref<Total[]>([])
const error=ref(''), notice=ref(''), busy=ref(false)
const channelForm=ref({label:'',organization:'',account_label:'',platform:'',region:'CN',rules_url:'',verification_note:'',verified:false})
const publication=ref({title:'',channel_id:'',delivery_task_id:'',planned_for:''})
const linkedPackage=ref<Delivery|null>(null), linkError=ref('')
const publicationPanel=ref<HTMLElement|null>(null)
const availablePackages=computed(()=>linkedPackage.value && !deliveries.value.some(item=>item.id===linkedPackage.value?.id)
  ? [linkedPackage.value,...deliveries.value] : deliveries.value)
const selectedPackage=computed(()=>availablePackages.value.find(item=>item.id===publication.value.delivery_task_id))
const publicationChannels=computed(()=>selectedPackage.value ? channels.value.filter(item=>
  item.platform===selectedPackage.value!.parameters.platform && item.region===selectedPackage.value!.parameters.region) : channels.value)
watch(publicationChannels, channels => {
  if (publication.value.channel_id && !channels.some(item=>item.id===publication.value.channel_id)) publication.value.channel_id=''
})
const promo=ref({delivery_task_id:'',title:'',description:'',episode:1,start_seconds:0,duration_seconds:1})
const current=ref(''), eventStatus=ref(''), eventProof=ref(''), ledgerChannel=ref(''), csv=ref('')
const keys=new Map<string,string>()
const base=`/distribution/projects/${props.projectId}`
const finance=`/finance/projects/${props.projectId}`
const transitions:Record<string,string[]>={draft:['planned','cancelled'],planned:['submitted','cancelled'],
  submitted:['published','rejected','cancelled'],published:['withdrawn'],rejected:['planned','cancelled']}
const statuses:Record<string,string>={draft:'草稿',planned:'已计划',submitted:'人工已提交',published:'人工登记已发布',
  rejected:'人工登记退回',cancelled:'已取消',withdrawn:'人工登记已撤回'}
const ledgerKinds:Record<string,string>={cash:'现金',ad_credit:'广告金',expense:'费用',cash_refund:'现金退回',booked_api:'已记账 API 费用'}
const ledgerStates:Record<string,string>={confirmed:'凭证已确认',estimate:'估算',unknown:'未知'}
const columns='external_id,currency,kind,status,amount,period_start,period_end,evidence'
let timer:ReturnType<typeof setInterval>|undefined
function key(body:object){const value=JSON.stringify(body);if(!keys.has(value))keys.set(value,crypto.randomUUID());return keys.get(value)!}
function money(micros:string|null,currency:string){
  if(micros===null)return '未知'
  const amount=BigInt(micros), absolute=amount<0n?-amount:amount
  const fraction=(absolute%1_000_000n).toString().padStart(6,'0').replace(/0+$/,'').padEnd(2,'0')
  return `${amount<0n?'-':''}${currency} ${absolute/1_000_000n}.${fraction}`
}
async function execute(action:()=>Promise<void>){
  busy.value=true;error.value='';notice.value=''
  try{await action()}catch(failure){error.value=String(failure)}finally{busy.value=false}
}
async function refresh(){
  if(!props.projectId)return
  const [a,b,c,d,e,f]=await Promise.all([
    request<Channel[]>(base+'/channels'),request<Delivery[]>(`/delivery/projects/${props.projectId}/packages`),
    request<Publication[]>(base+'/publications'),request<Promo[]>(base+'/promotions'),
    request<Settlement[]>(finance+'/settlements'),request<{by_currency:Total[]}>(finance+'/summary'),
  ])
  channels.value=a;deliveries.value=b.filter(item=>item.status==='succeeded');publications.value=c;promos.value=d
  ledger.value=e;totals.value=f.by_currency
}
async function restorePackage() {
  if (!props.projectId || !props.initialPackage) return
  try {
    const item=await request<Delivery>(`/delivery/projects/${props.projectId}/packages/${encodeURIComponent(props.initialPackage)}`)
    if (item.status!=='succeeded') throw new Error('交付任务尚未完成验证')
    linkedPackage.value=item
    publication.value.delivery_task_id=item.id
    publication.value.title=item.parameters.title
    await nextTick()
    publicationPanel.value?.scrollIntoView({block:'start'})
    publicationPanel.value?.focus({preventScroll:true})
  } catch (failure) {
    linkError.value=String(failure)
  }
}
async function saveChannel(){
  await execute(async()=>{
    const body={...channelForm.value,platform:channelForm.value.platform.trim(),region:channelForm.value.region.toUpperCase().trim()}
    const row=await request<Channel>(base+'/channels',{...body,idempotency_key:key(body)})
    await refresh();publication.value.channel_id=row.id
    notice.value='已保存渠道规则版本'
  })
}
async function createPublication(){
  await execute(async()=>{
    const body={...publication.value,planned_for:publication.value.planned_for?new Date(publication.value.planned_for).toISOString():null}
    const row=await request<Publication>(base+'/publications',{...body,idempotency_key:key(body)})
    await refresh();current.value=row.id
    notice.value='人工发行草稿已保存'
  })
}
async function record(item:Publication){
  await execute(async()=>{
    const body={expected_status:item.status,status:eventStatus.value,evidence:eventProof.value}
    await request('/distribution/publications/'+item.id+'/events',{...body,idempotency_key:key({...body,id:item.id})})
    await refresh();eventProof.value='';eventStatus.value=''
    notice.value='已登记人工发行状态'
  })
}
async function queuePromo(){
  await execute(async()=>{
    const body=promo.value
    await request(base+'/promotions',{...body,idempotency_key:key(body)})
    await refresh();notice.value='本机推广包已排队'
  })
}
async function csvFile(event:Event){
  const input=event.target as HTMLInputElement
  const file=input.files?.[0]
  if(!file)return
  await execute(async()=>{if(file.size>512000)throw new Error('CSV 超过 512 KB');csv.value=await file.text()})
  input.value=''
}
async function importLedger(){
  await execute(async()=>{
    const counts=await request<{inserted:number;duplicates:number}>(finance+'/settlements/import',{channel_id:ledgerChannel.value,csv:csv.value})
    await refresh()
    notice.value=`新增 ${counts.inserted} 条结算，跳过 ${counts.duplicates} 条重复记录`
  })
}
onMounted(()=>{
  void execute(async()=>{await Promise.all([refresh(),restorePackage()])})
  timer=setInterval(()=>{if(!busy.value && promos.value.some(item=>['queued','running'].includes(item.status)))void refresh().catch(failure=>{error.value=String(failure)})},4000)
})
onUnmounted(()=>clearInterval(timer))
</script>

<template>
  <p v-if="!projectId" class="empty">选择项目以登记发行和结算。</p>
  <div v-else class="operations">
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="linkError" role="alert" class="error">{{ linkError }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="workspace">
      <section>
        <h2>剧场与发行渠道</h2>
        <p class="hint">记录实际运营主体、账号显示名及规则来源。状态由人工登记。</p>
        <article v-for="channel in channels" :key="channel.id" class="track">
          {{ channel.label }} · {{ channel.platform }} / {{ channel.region }} · 规则 v{{ channel.rule_version }} · {{ channel.verified ? '人工已核验' : '待核验' }}
        </article>
        <details>
          <summary>登记渠道及规则</summary>
          <form class="form-grid" @submit.prevent="saveChannel">
            <label>剧场或渠道名称<input v-model="channelForm.label" required maxlength="180"></label>
            <label>运营主体<input v-model="channelForm.organization" required maxlength="300"></label>
            <label>账号显示名<input v-model="channelForm.account_label" required maxlength="120"></label>
            <div class="editor-grid">
              <label>平台标识<input v-model="channelForm.platform" required maxlength="40" placeholder="例如 wechat_channels"></label>
              <label>投放地域<input v-model="channelForm.region" required maxlength="5"></label>
            </div>
            <label>规则出处（HTTPS）<input v-model="channelForm.rules_url" type="url" maxlength="700"></label>
            <label>人工核验依据<textarea v-model="channelForm.verification_note" maxlength="4000"></textarea></label>
            <label class="check"><input v-model="channelForm.verified" type="checkbox">我已核验该渠道适用的平台规则</label>
            <button :disabled="busy">保存渠道</button>
          </form>
        </details>
      </section>
      <section ref="publicationPanel" class="publication-panel" tabindex="-1">
        <h2>人工发行记录</h2>
        <div v-if="linkedPackage" class="operations-handoff actions">
          <span>{{linkedPackage.parameters.title}} · {{linkedPackage.parameters.platform}} / {{linkedPackage.parameters.region}}</span>
          <button type="button" @click="emit('backToDelivery',linkedPackage.parameters.run_id)">回到交付批次</button>
        </div>
        <form class="form-grid" @submit.prevent="createPublication">
          <label>发行渠道<select v-model="publication.channel_id" required><option value="">选择渠道</option>
            <option v-for="item in publicationChannels" :key="item.id" :value="item.id">{{ item.label }} · v{{ item.rule_version }}</option></select></label>
          <label>授权交付包<select v-model="publication.delivery_task_id" required><option value="">选择完成交付包</option>
            <option v-for="item in availablePackages" :key="item.id" :value="item.id">{{ item.parameters.title }} · {{ item.parameters.platform }} / {{ item.parameters.region }}</option></select></label>
          <p v-if="selectedPackage && !publicationChannels.length" class="hint">请先登记匹配 {{selectedPackage.parameters.platform}} / {{selectedPackage.parameters.region}} 的渠道。</p>
          <label>发行标题<input v-model="publication.title" required maxlength="180"></label>
          <label>计划时间<input v-model="publication.planned_for" type="datetime-local"></label>
          <button :disabled="busy || !publication.channel_id || !publication.delivery_task_id">保存发行草稿</button>
        </form>
        <article v-for="item in publications" :key="item.id" class="track">
          <button :aria-pressed="current===item.id" @click="current=item.id;eventStatus='';eventProof=''">{{ item.title }} · {{ statuses[item.status] }}</button>
          <div v-if="current===item.id">
            <p class="hint">{{ item.channel.label }} · 仅本机人工记录</p>
            <p v-for="(event,index) in item.events" :key="index">{{ statuses[event.status] }} · {{ event.evidence }}</p>
            <form v-if="transitions[item.status]?.length" class="form-grid" @submit.prevent="record(item)">
              <label>更新状态<select v-model="eventStatus" required><option value="">选择人工状态</option>
                <option v-for="state in transitions[item.status]" :key="state" :value="state">{{ statuses[state] }}</option></select></label>
              <label>实际状态凭证<textarea v-model="eventProof" required minlength="6" maxlength="4000"></textarea></label>
              <button :disabled="busy">登记人工结果</button>
            </form>
          </div>
        </article>
      </section>
    </div>
    <section>
      <h2>推广素材</h2>
      <form class="form-grid" @submit.prevent="queuePromo">
        <label>推广来源交付包<select v-model="promo.delivery_task_id" required><option value="">选择完成交付包</option>
          <option v-for="item in availablePackages" :key="item.id" :value="item.id">{{ item.parameters.title }}</option></select></label>
        <div class="editor-grid">
          <label>推广标题<input v-model="promo.title" required maxlength="180"></label>
          <label>推广分集<input v-model.number="promo.episode" required type="number" min="1" max="60"></label>
          <label>开始秒数<input v-model.number="promo.start_seconds" required type="number" min="0" step="0.001"></label>
          <label>推广片段秒数<input v-model.number="promo.duration_seconds" required type="number" min="0.2" max="30" step="0.001"></label>
        </div>
        <label>简介<textarea v-model="promo.description" required maxlength="2000"></textarea></label>
        <button :disabled="busy || !promo.delivery_task_id">生成待审推广包</button>
      </form>
      <article v-for="item in promos" :key="item.id" class="track">{{ item.title }} · {{ statusLabels[item.status] || item.status }}
        <a v-if="item.status==='succeeded'" :href="`/api/distribution/promotions/${item.id}/file`">下载片段、封面和清单</a>
        <p v-if="item.error" class="error">{{ item.error }}</p>
      </article>
    </section>
    <section>
      <h2>结算与经营记录</h2>
      <p class="hint">按币种显示已记录现金、广告金及费用。现金差额依据已确认记录计算，估算和未知有独立计数。</p>
      <div v-for="total in totals" :key="total.currency" class="track">
        <strong>{{ total.currency }} · 已记账现金差额 {{ money(total.recorded_cash_difference_micros,total.currency) }}</strong>
        <p>{{ Object.entries(total.amounts_micros).map(([kind,amount])=>ledgerKinds[kind]+' '+money(amount,total.currency)).join(' · ') }}</p>
        <p>估算 {{ total.estimate_entries }} · 未知账单 {{ total.unknown_entries }} · 未知 API 费用 {{ total.unknown_model_charges }}</p>
      </div>
      <form class="form-grid" @submit.prevent="importLedger">
        <label>结算渠道<select v-model="ledgerChannel" required><option value="">选择渠道</option>
          <option v-for="item in channels" :key="item.id" :value="item.id">{{ item.label }} · v{{ item.rule_version }}</option></select></label>
        <label>导入 UTF-8 CSV<input type="file" accept=".csv,text/csv" @change="csvFile"></label>
        <label>结算 CSV<textarea v-model="csv" required maxlength="512000" placeholder="粘贴已核对的结算数据"></textarea></label>
        <p class="hint mono">{{ columns }}。类型 cash / ad_credit / expense / cash_refund。状态 confirmed / estimate / unknown。</p>
        <button :disabled="busy || !ledgerChannel">导入结算记录</button>
      </form>
      <article v-for="row in ledger" :key="row.id" class="track">{{ row.channel }} · {{ row.external_id }} · {{ ledgerKinds[row.kind] }} · {{ ledgerStates[row.status] }} · {{ money(row.amount_micros,row.currency) }}</article>
    </section>
  </div>
</template>
<style scoped>
.publication-panel { scroll-margin-top:calc(var(--topbar-height) + 12px) }
.operations-handoff { padding:10px; background:#122730; border:1px solid #36615e; border-radius:8px; overflow-wrap:anywhere }
.operations,.form-grid { display:grid;gap:14px }
.operations section { min-width:0 }
.operations details,.form-grid { margin:12px 0 }
.track { padding:12px 0;border-top:1px solid #334050;overflow-wrap:anywhere }
.track a { margin-left:12px }
</style>
