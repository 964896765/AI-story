<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import TextProviderConfig from './TextProviderConfig.vue'
import { toMicros } from './money'

interface Version { version_id: string; title: string; version: number }
interface Provider {
  id: string; label: string; kind: 'mock' | 'openai_compatible'; enabled: boolean
  settings: { currency: string; output_token_limit: number }
}
interface Budget {
  id: string; mode: string; currency: string; limit_micros: number
  reserved_micros: number; spent_micros: number; halted: boolean
}
interface Draft {
  title: string; synopsis: string; body: string
  episodes: { number: number; title: string; synopsis: string }[]
  dialogues: { speaker: string; text: string }[]
}
interface Call {
  id: string; project_id: string; simulated: boolean; status: string; budget_status: string
  source_version_id: string; accepted_version_id: string | null; draft_revision: number
  provider_snapshot: { label: string; currency: string }
  created_at: string; reserved_micros: number; calculated_cost_micros: number | null
  actual_cost_micros: number | null; draft: Draft | null; error_code: string | null
}
interface LedgerEntry { id: number; call_id: string | null; mode: string; currency: string; kind: string; amount_micros: number }
const props = defineProps<{ projectId: string; source: Version | null; initialCall?: string; settingsOnly?: boolean }>()
const emit = defineEmits<{ sourcePicker: []; production: [version: Version] }>()

const providers = ref<Provider[]>([]), budgets = ref<Budget[]>([]), calls = ref<Call[]>([])
const ledger = ref<LedgerEntry[]>([]), selected = ref<Call | null>(null), draft = ref<Draft | null>(null)
const providerId = ref(''), providerName = ref(''), scenario = ref('success'), limit = ref('1')
const error = ref(''), notice = ref(''), diff = ref<string | null>(null), reviewNote = ref('')
const evidence = ref(''), invoice = ref(''), billKind = ref<'charge' | 'refund'>('charge')
const retryConsent = ref(false), history = ref<{number:number;origin:string;created_at:string}[]>([])
const busy = ref(false), authorization = ref(false)
const savedDraft = ref('')
const quote = ref<{ upper_bound_micros: number | null; currency: string; simulated: boolean } | null>(null)
const form = reactive({ goal: '', style: '', audience: '', length: '', constraints: '', max_output_tokens: 1024 })
const provider = computed(() => providers.value.find(item => item.id === providerId.value))
const states: Record<string, string> = {
  queued: '已排队', dispatching: '调用处理中', received: '响应已保存，待核算', awaiting_review: '待人工审核',
  accepted: '已采纳', rejected: '已拒稿', cancelled: '已取消', failed: '失败',
  unknown: '调用结果未知', cost_unknown: '费用未知', invalid_output: '响应结构错误', budget_overrun: '超额已冻结',
}
const events: Record<string, string> = {limit:'设置额度',reserve:'预留',settle:'用量核算',release:'释放',reconcile_note:'对账',charge:'实付',refund:'退款'}
const projectPath = `/text/projects/${props.projectId}`
const callPath = (id: string) => `/text/calls/${id}`
const amount = (micros: number | null, currency: string) => micros === null ? '未知' :
  new Intl.NumberFormat('zh-CN', { style: 'currency', currency, maximumFractionDigits: 6 }).format(micros / 1_000_000)
const monitoring = computed(() => selected.value && ['queued', 'dispatching', 'received'].includes(selected.value.status))
let timer: ReturnType<typeof setInterval> | undefined
let refreshing = false

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, options)
  const body = await response.json()
  if (!response.ok) throw new Error(typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail))
  return body
}
async function requestKey(path: string, body: object) {
  const bytes = new TextEncoder().encode(path + JSON.stringify(body))
  const hash = new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))
  return 'ai-story:request:' + Array.from(hash, value => value.toString(16).padStart(2, '0')).join('')
}
async function post<T>(path: string, body: object = {}, idempotent = false, retainKey = false) {
  let key = ''
  if (idempotent) {
    key = await requestKey(path, body)
  }
  const payload = key ? { ...body, idempotency_key: sessionStorage.getItem(key) || crypto.randomUUID() } : body
  if (key && 'idempotency_key' in payload) sessionStorage.setItem(key, String(payload.idempotency_key))
  const result = await request<T>(path, {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
  })
  if (key && !retainKey) sessionStorage.removeItem(key)
  return result
}
function show(call: Call) {
  selected.value = call
  draft.value = call.draft
  savedDraft.value = JSON.stringify(call.draft)
  diff.value = null
}
async function refresh() {
  if (!props.projectId || refreshing) return
  refreshing = true
  try {
    const [status, catalog, limits, records, entries] = await Promise.all([
      request<{live_authorized: boolean}>('/text/status'), request<Provider[]>('/text/providers'),
      request<Budget[]>(`${projectPath}/budgets`), request<Call[]>(`${projectPath}/calls`),
      request<LedgerEntry[]>(`${projectPath}/ledger`),
    ])
    authorization.value = status.live_authorized
    providers.value = catalog
    budgets.value = limits
    calls.value = records
    ledger.value = entries
    if (!providerId.value) providerId.value = catalog.find(item => item.enabled && item.kind === 'mock')?.id || ''
    if (monitoring.value && selected.value) {
      const id = selected.value.id
      const current = await request<Call>(callPath(id))
      if (selected.value?.id === id && monitoring.value) {
        show(current)
        if (current.draft_revision) history.value = await request(`${callPath(id)}/drafts`)
      }
    }
  } finally {
    refreshing = false
  }
}
async function run(action: () => Promise<void>) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await action() } catch (failure) { error.value = String(failure) } finally { busy.value = false }
}
async function createProvider() {
  await run(async () => {
    const configured = await post<Provider>('/text/providers', {
      label: providerName.value, kind: 'mock', enabled: true,
      settings: { model: 'offline-adaptation-fixture', mock_scenario: scenario.value,
        input_per_million: '1', output_per_million: '2', input_token_limit: 65536 },
    })
    providerId.value = configured.id
    providerName.value = ''
    quote.value = null
    await refresh()
  })
}
async function setLimit() {
  await run(async () => {
    await post(`${projectPath}/budgets`, { mode: 'mock', currency: 'CNY', limit_micros: toMicros(limit.value) }, true)
    await refresh()
  })
}
async function getQuote() {
  await run(async () => {
    quote.value = await request(`/text/providers/${providerId.value}/quote?max_output_tokens=${form.max_output_tokens}`)
  })
}
function submission() { return { ...form, source_version_id: props.source?.version_id, provider_id: providerId.value } }
async function newSubmission() {
  await run(async () => {
    sessionStorage.removeItem(await requestKey(`${projectPath}/calls`, submission()))
    notice.value = '相同参数的下一次提交将创建新调用并重新预留额度。'
  })
}
async function submit() {
  if (!props.source) return
  await run(async () => {
    const result = await post<Call>(`${projectPath}/calls`, submission(), true, true)
    reviewNote.value = ''
    show(result)
    await refresh()
  })
}
async function openCall(id: string) {
  await run(async () => {
    const call = await request<Call>(callPath(encodeURIComponent(id)))
    if (call.project_id !== props.projectId) throw new Error('链接中的改编调用不属于当前项目。')
    show(call)
    reviewNote.value = ''
    evidence.value = ''
    invoice.value = ''
    retryConsent.value = false
    history.value = await request(`${callPath(id)}/drafts`)
  })
}
async function saveDraft() {
  if (!selected.value || !draft.value) return
  const {id, draft_revision} = selected.value
  await run(async () => {
    show(await post<Call>(`${callPath(id)}/draft`, { expected_revision: draft_revision, draft: draft.value }, true))
    notice.value = '草稿版本已保存'
    history.value = await request(`${callPath(id)}/drafts`)
  })
}
async function restoreDraft(number: number) {
  if (!selected.value) return
  const id = selected.value.id
  await run(async () => {
    const revision = await request<{payload:Draft}>(`${callPath(id)}/drafts/${number}`)
    draft.value = revision.payload
    notice.value = `已加载草稿 v${number}。保存草稿修订将追加版本，历史保持不变。`
  })
}
async function retryCall() {
  if (!selected.value || !retryConsent.value) return
  const id = selected.value.id
  await run(async () => {
    show(await post<Call>(`${callPath(id)}/retry`, {acknowledge_new_charge:true}, true, true))
    retryConsent.value = false
    await refresh()
  })
}
async function settleCall() {
  if (!selected.value) return
  const id = selected.value.id
  await run(async () => {show(await post<Call>(`${callPath(id)}/settle`)); await refresh()})
}
const canReview = computed(() => selected.value?.status === 'awaiting_review' && !!draft.value)
const dirty = computed(() => JSON.stringify(draft.value) !== savedDraft.value)
async function review(action: 'accept' | 'reject') {
  if (!selected.value || dirty.value) return
  const {id, draft_revision} = selected.value
  await run(async () => {
    show(await post<Call>(`${callPath(id)}/review`, { action, draft_revision, note: reviewNote.value }))
    await refresh()
  })
}
async function compare() {
  const id = selected.value?.id
  if (!id) return
  await run(async () => {
    const result = await request<{diff: string; truncated: boolean}>(`${callPath(id)}/compare`)
    diff.value = (result.truncated ? '差异超出显示上限\n' : '') + (result.diff || '正文相同')
  })
}
async function handoff() {
  const id = selected.value?.accepted_version_id
  if (id) await run(async () => emit('production', await request<Version>(`/story/versions/${id}`)))
}
async function resolveBilling(notCharged = false) {
  const id = selected.value?.id
  if (!id) return
  await run(async () => {
    const path = callPath(id)
    const result = notCharged
      ? await post<Call>(`${path}/reconcile`, { resolution: 'not_charged', evidence: evidence.value })
      : await post<Call>(`${path}/billing`, { kind: billKind.value, amount_micros: toMicros(invoice.value), evidence: evidence.value }, true)
    show(result)
    evidence.value = ''
    invoice.value = ''
    await refresh()
  })
}
async function cancelCall() {
  const id = selected.value?.id
  if (!id) return
  await run(async () => {
    show(await post<Call>(`${callPath(id)}/cancel`))
    notice.value = '取消请求已记录。若已发出调用，费用按最终结果对账。'
    await refresh()
  })
}
onMounted(() => {
  void run(refresh).then(() => { if (props.projectId && props.initialCall) void openCall(props.initialCall) })
  timer = setInterval(() => {
    if (!busy.value) void refresh().catch(failure => { error.value = String(failure) })
  }, 3000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <p v-if="!projectId" class="empty">选择项目以查看剧情改编和预算。</p>
  <div v-else class="text-workspace">
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="workspace">
      <section v-if="!settingsOnly">
        <h2>剧情改编</h2>
        <p v-if="source">固定原稿 {{ source.title }} · v{{ source.version }}</p>
        <p v-else class="hint">从小说与剧本选择已保存的小说、剧本或分集版本。</p>
        <button @click="emit('sourcePicker')">选择原稿版本</button>
        <form class="create" @submit.prevent="submit">
          <label>文本模型
            <select v-model="providerId" required @change="quote = null">
              <option value="">选择已启用的配置</option>
              <option v-for="item in providers.filter(p => p.enabled)" :key="item.id" :value="item.id" :disabled="item.kind !== 'mock' && !authorization">
                {{ item.label }} · {{ item.kind === 'mock' ? '离线模拟' : '真实接口' }}
              </option>
            </select>
          </label>
          <label>改编目标<textarea v-model="form.goal" required maxlength="4000"></textarea></label>
          <details>
            <summary>改编参数</summary>
            <label>风格<input v-model="form.style" maxlength="2000"></label>
            <label>观众<input v-model="form.audience" maxlength="1000"></label>
            <label>篇幅<input v-model="form.length" maxlength="1000"></label>
            <label>约束<textarea v-model="form.constraints" maxlength="4000"></textarea></label>
          </details>
          <label>输出 Token 上限<input v-model.number="form.max_output_tokens" type="number" min="128" :max="provider?.settings.output_token_limit || 32768" @input="quote = null"></label>
          <div class="actions">
            <button type="button" :disabled="busy || !provider" @click="getQuote">查看预留上限</button>
            <button class="primary" :disabled="busy || !source || !provider || !form.goal.trim()">提交改编</button>
          </div>
          <p v-if="quote" class="hint">{{ quote.simulated ? '模拟预留上限' : '真实预留上限' }} {{ amount(quote.upper_bound_micros, quote.currency) }}</p>
          <p class="hint">相同参数重复提交会返回原调用。主动重新生成前，先选择下方按钮。</p>
          <button type="button" :disabled="busy" @click="newSubmission">开始新改编请求</button>
        </form>
      </section>
      <section>
        <h2>模型供应商与项目预算</h2>
        <p class="hint">{{ authorization ? '本机已设置真实调用授权开关。' : '真实调用已关闭，默认预算 ¥0。' }} 模拟余额与实际账单独立记录。</p>
        <TextProviderConfig @saved="run(refresh)" />
        <table v-if="providers.length" class="providers-table"><thead><tr><th scope="col">供应商配置</th><th scope="col">能力</th><th scope="col">状态</th></tr></thead>
          <tbody><tr v-for="item in providers" :key="item.id"><td>{{item.label}}</td><td>{{item.kind==='mock'?'离线模拟':'兼容文本接口'}}</td><td>{{item.enabled?'已启用':'已禁用'}}</td></tr></tbody>
        </table>
        <form class="create" @submit.prevent="createProvider">
          <label>模拟配置名称<input v-model="providerName" required maxlength="120"></label>
          <label>模拟响应<select v-model="scenario">
            <option value="success">结构有效</option><option value="timeout">超时，结果未知</option>
            <option value="rate_limit">限流拒绝</option><option value="server_error">服务异常</option>
            <option value="invalid_output">结构不合法</option><option value="missing_usage">缺失用量</option>
            <option value="overrun">费用超出预留</option>
          </select></label>
          <button :disabled="busy">添加离线模拟配置</button>
          <p class="hint">模拟单价：输入 1、输出 2 元/百万 Token，仅为测试数值，不代表市场价格。</p>
        </form>
        <form class="create" @submit.prevent="setLimit">
          <label>项目模拟额度（元）<input v-model="limit" required inputmode="decimal" pattern="[0-9]+(\.[0-9]{1,6})?"></label>
          <button :disabled="busy">保存模拟额度</button>
        </form>
        <p v-for="budget in budgets" :key="budget.id">
          {{ budget.mode === 'mock' ? '模拟' : '真实' }} · {{ amount(budget.limit_micros,budget.currency) }} 额度 ·
          {{ amount(budget.reserved_micros,budget.currency) }} 占用 · {{ amount(budget.spent_micros,budget.currency) }} 核算或已付
          <span v-if="budget.halted"> · 已冻结</span>
        </p>
        <details v-if="ledger.length" class="ledger">
          <summary>近期费用流水</summary>
          <ul><li v-for="entry in ledger" :key="entry.id">
            {{ entry.mode === 'mock' ? '模拟' : '真实' }} · {{ events[entry.kind] || entry.kind }} · {{ amount(entry.amount_micros,entry.currency) }}
            <button v-if="entry.call_id" @click="openCall(entry.call_id)">查看调用</button>
          </li></ul>
        </details>
      </section>
      <section v-if="settingsOnly">
        <h2>系统偏好与安全</h2>
        <dl class="inspector-facts"><div><dt>运行范围</dt><dd>本机工作台</dd></div><div><dt>真实 API 调用</dt><dd>{{authorization?'已授权':'关闭'}}</dd></div><div><dt>供应商配置</dt><dd>{{providers.length}} 项</dd></div></dl>
        <RouterLink :to="{name:'system',query:{project:projectId}}">打开运行诊断</RouterLink>
      </section>
    </div>
    <section>
      <h2>改编记录</h2>
      <p v-if="!calls.length" class="hint">项目暂无改编记录。</p>
      <div class="version-list">
        <button v-for="call in calls" :key="call.id" :aria-pressed="selected?.id === call.id" @click="openCall(call.id)">
          {{ call.simulated ? '模拟' : '真实' }} · {{ states[call.status] || call.status }} · {{ new Date(call.created_at).toLocaleString('zh-CN') }}
        </button>
      </div>
      <template v-if="selected">
        <h3>{{ selected.provider_snapshot.label }} · {{ states[selected.status] || selected.status }}</h3>
        <p class="mono">原稿 {{ selected.source_version_id }}</p>
        <p class="hint">{{ selected.simulated ? '此为离线模拟，非AI创作质量验收。' : '真实生成仍须人工审阅。' }} 未审核草稿不能作为生产版本。</p>
        <p>{{ selected.simulated ? '离线模拟' : '真实接口' }} · 初始预留 {{ amount(selected.reserved_micros,selected.provider_snapshot.currency) }}
          · 用量核算 {{ amount(selected.calculated_cost_micros,selected.provider_snapshot.currency) }}
          · {{ selected.simulated ? '实际费用不适用' : '凭证净实付 '+amount(selected.actual_cost_micros,selected.provider_snapshot.currency) }}</p>
        <p v-if="selected.error_code" class="hint">{{ selected.error_code }}</p>
        <div class="actions">
          <button v-if="monitoring" :disabled="busy" @click="cancelCall">请求取消</button>
          <button v-if="selected.status === 'received'" :disabled="busy" @click="settleCall">恢复本地核算（不重发）</button>
          <button v-if="draft" :disabled="busy" @click="compare">对比已保存草稿与原稿</button>
          <button v-if="selected.accepted_version_id" class="primary" :disabled="busy" @click="handoff">引用已审核剧本创建剪辑批次</button>
        </div>
        <pre v-if="diff !== null" class="log-tail">{{ diff }}</pre>
        <details><summary>调用参数、用量与版本信息</summary><pre>{{ JSON.stringify(selected,null,2) }}</pre></details>
        <div v-if="['failed','invalid_output','cancelled'].includes(selected.status) && ['released','settled'].includes(selected.budget_status)" class="create">
          <label><input v-model="retryConsent" type="checkbox">确认创建新调用，重新占用额度；真实调用可能再次收费</label>
          <button :disabled="busy || !retryConsent" @click="retryCall">受控重试</button>
        </div>
        <details v-if="canReview && history.length"><summary>草稿历史（恢复时追加修订）</summary>
          <p v-for="item in history" :key="item.number">v{{ item.number }} · {{ item.origin }} · {{ new Date(item.created_at).toLocaleString('zh-CN') }} <button :disabled="busy" @click="restoreDraft(item.number)">加载历史草稿</button></p>
        </details>
        <p v-if="selected.accepted_version_id" class="hint">正式剧本的历史对比与追加回滚在“漫剧定制”中操作。</p>
        <form v-if="canReview && draft" class="create" @submit.prevent="saveDraft">
          <h3>待审核草稿 v{{ selected.draft_revision }}</h3>
          <label>草稿标题<input v-model="draft.title" required maxlength="200"></label>
          <label>剧情摘要<textarea v-model="draft.synopsis" required maxlength="20000"></textarea></label>
          <label>改编正文<textarea v-model="draft.body" required maxlength="100000" rows="10"></textarea></label>
          <details>
            <summary>分集和对白</summary>
            <fieldset v-for="(episode,index) in draft.episodes" :key="index">
              <legend>第 {{ index + 1 }} 集</legend>
              <label>分集标题<input v-model="episode.title" required maxlength="200"></label>
              <label>分集梗概<textarea v-model="episode.synopsis" required maxlength="5000"></textarea></label>
              <button v-if="draft.episodes.length > 1" type="button" @click="draft.episodes.splice(index,1); draft.episodes.forEach((item,i) => item.number = i+1)">删除本集</button>
            </fieldset>
            <button type="button" :disabled="draft.episodes.length >= 50" @click="draft.episodes.push({number:draft.episodes.length+1,title:'',synopsis:''})">添加分集</button>
            <fieldset v-for="(line,index) in draft.dialogues" :key="index">
              <legend>对白 {{ index + 1 }}</legend><label>说话人<input v-model="line.speaker" required maxlength="100"></label>
              <label>台词<textarea v-model="line.text" required maxlength="5000"></textarea></label>
              <button type="button" @click="draft.dialogues.splice(index,1)">删除此句</button>
            </fieldset>
            <button type="button" :disabled="draft.dialogues.length >= 200" @click="draft.dialogues.push({speaker:'',text:''})">添加对白</button>
          </details>
          <button :disabled="busy || !dirty">保存草稿修订</button>
        </form>
        <div v-if="canReview" class="create">
          <label>审核意见<textarea v-model="reviewNote" maxlength="4000"></textarea></label>
          <div class="actions">
            <button class="primary" :disabled="busy || dirty || !reviewNote.trim()" @click="review('accept')">批准并保存为新剧本</button>
            <button :disabled="busy || dirty || !reviewNote.trim()" @click="review('reject')">拒绝草稿</button>
          </div>
        </div>
        <details v-if="!monitoring" class="ledger">
          <summary>账单对账与退款</summary>
          <form class="create" @submit.prevent="resolveBilling()">
            <label>账单凭证说明<textarea v-model="evidence" required minlength="20" maxlength="4000"></textarea></label>
            <label>记录类型<select v-model="billKind"><option value="charge">实付</option><option value="refund">退款</option></select></label>
            <label>凭证金额（{{ selected.provider_snapshot.currency }}）<input v-model="invoice" required inputmode="decimal" pattern="[0-9]+(\.[0-9]{1,6})?"></label>
            <div class="actions">
              <button :disabled="busy || evidence.trim().length < 20">登记凭证</button>
              <button v-if="selected.budget_status === 'unknown'" type="button" :disabled="busy || evidence.trim().length < 20" @click="resolveBilling(true)">确认供应商未计费</button>
            </div>
          </form>
        </details>
      </template>
    </section>
  </div>
</template>

<style scoped>
.providers-table { width:100%;border-collapse:collapse;margin:10px 0;font-size:12px;text-align:left }
.providers-table th,.providers-table td { border-bottom:1px solid var(--line);padding:8px;overflow-wrap:anywhere }
.providers-table th { color:var(--ink-muted);background:var(--surface-raised) }
.text-workspace { display:grid; gap:24px }
.text-workspace form { max-width:unset }
.text-workspace details { margin:0 }
.ledger { margin-top:18px !important }
.ledger li { margin:8px 0 }
.version-list button[aria-pressed="true"] { border-color:var(--accent) }
</style>
