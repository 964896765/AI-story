<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowDownToLine, Film, ListFilter, Play, RefreshCw } from 'lucide-vue-next'
import AttemptHistory from '../../AttemptHistory.vue'
import OutputPreview from '../ui/OutputPreview.vue'
import { api, post } from '../../services/api'
import { useWorkbench } from '../../stores/workbench'
import type { Task } from '../../types/workbench'

const props = defineProps<{ rendersOnly?: boolean }>()
const workbench = useWorkbench()
const tasks = ref<Task[]>([]), offset = ref(0), error = ref(''), busy = ref(false)
const preview = ref(''), selectedLog = ref('')
const loading = ref(false)
const filters = [{ id:'all', label:'全部任务' }, { id:'active', label:'排队与运行' },
  { id:'issues', label:'失败与取消' }, { id:'completed', label:'已完成' }] as const
const filter = ref<typeof filters[number]['id']>('all')
const events = ref<{ id: number; created_at: string; attempt: number; message: string }[]>([])
const pageSize = 50
const labels: Record<string, string> = { queued:'排队中', running:'执行中', succeeded:'已完成', failed:'失败', cancelled:'已取消' }
const kinds: Record<string, string> = { probe:'读取媒体信息', analyze:'媒体解析', render:'视频剪辑', adapt:'剧情改编', image_candidate:'图片候选', still_motion:'运镜候选', local_voice:'本机配音', timeline_render:'多轨渲染', qc_review:'技术质检', delivery:'整剧交付', promotion:'推广包' }
const stages: Record<string, string> = { queued:'等待领取', recovered:'中断恢复', inspecting:'检查输入', encoding:'FFmpeg 编码', validating:'验证成片', publishing:'发布输出', succeeded:'完成', failed:'失败', cancelled:'已取消', retry_wait:'等待自动重试', checkpoint:'核验检查点', resuming_checkpoint:'复用编码检查点', awaiting_review:'待人工审核', approved:'人工已通过', rejected:'人工已拒绝', settlement_recovery:'恢复用量核算', dispatching:'模型调用处理中', received:'响应已保存，核算中' }
Object.assign(stages,{image_verify_inputs:'核对固定图片输入',image_simulate:'离线模拟',image_dispatch:'等待图片接口响应',image_decode:'解码核对',image_publish:'保存候选'})
let timer: ReturnType<typeof setInterval> | undefined
let pending: AbortController | undefined
const isRender = (task: Task) => ['render', 'timeline_render'].includes(task.kind)
const finished = (task: Task) => isRender(task) && task.status === 'succeeded'
const canRetry = (task: Task) => ['failed','cancelled'].includes(task.status) && task.kind!=='adapt'
  && (task.kind!=='image_candidate' || task.parameters.mode==='mock')
const shown = computed(() => tasks.value.slice(0,pageSize))
const hasNext = computed(() => tasks.value.length > pageSize)
const title = (task: Task) => task.kind==='adapt' && task.parameters.purpose==='director_advice' ? '总导演规划建议'
  : workbench.assets.find(asset => asset.id === task.asset_id)?.name || kinds[task.kind] || task.kind

async function refresh() {
  if (!workbench.projectId) return
  pending?.abort()
  const controller = new AbortController()
  pending = controller
  try {
    const view = props.rendersOnly ? 'renders' : filter.value
    const list = await api<Task[]>(`/projects/${workbench.projectId}/tasks?offset=${offset.value}&limit=${pageSize+1}&view=${view}`, { signal: controller.signal })
    if (!controller.signal.aborted) { tasks.value = list; loading.value = false }
  } catch (failure) { if (!controller.signal.aborted) error.value = String(failure) }
  finally { if (pending === controller) { pending = undefined; loading.value = false } }
}

function page(direction: number) {
  offset.value = Math.max(0, offset.value + pageSize * direction)
  selectedLog.value = ''
  loading.value = true
  void refresh()
}

function selectFilter(value: typeof filter.value) {
  if (value === filter.value) return
  filter.value = value
  tasks.value = []
  error.value = ''
  offset.value = 0
  selectedLog.value = ''
  loading.value = true
  void refresh()
}

async function control(task: Task, command: 'retry' | 'cancel') {
  busy.value = true
  error.value = ''
  try { await post(`/tasks/${task.id}/${command}`); await refresh() }
  catch (failure) { error.value = String(failure) } finally { busy.value = false }
}

async function logs(id: string) {
  selectedLog.value = id
  events.value = []
  try {
    const list = await api<typeof events.value>(`/tasks/${id}/events`)
    if (selectedLog.value === id) events.value = list
  } catch (failure) { if (selectedLog.value === id) error.value = String(failure) }
}

onMounted(() => {
  loading.value = !!workbench.projectId
  void refresh()
  timer = setInterval(() => { if (!pending && document.visibilityState !== 'hidden') void refresh() }, 3000)
})
onUnmounted(() => { clearInterval(timer); pending?.abort() })
watch(() => workbench.refreshCount, () => { void refresh() })
</script>

<template>
 <section class="task-workspace">
  <header class="task-heading">
    <div><h2>{{ rendersOnly ? '已验证成片' : '持久化任务队列' }}</h2>
      <p class="hint">{{ rendersOnly ? '可预览技术验证通过的本地输出，并下载原始成片。' : '队列直接读取 Worker 状态，保留执行尝试和事件日志。' }}</p></div>
    <button type="button" class="icon-button" aria-label="刷新任务" title="刷新任务" :disabled="!workbench.projectId || loading" @click="refresh">
      <RefreshCw :size="16" aria-hidden="true" />
    </button>
  </header>
  <p v-if="error" class="error" role="alert">{{ error }} <button @click="error = ''">关闭</button></p>
  <div v-if="!rendersOnly && workbench.projectId" class="task-filters" aria-label="按状态筛选任务">
    <ListFilter :size="16" aria-hidden="true" />
    <button v-for="item in filters" :key="item.id" type="button" :aria-pressed="filter===item.id" @click="selectFilter(item.id)">{{item.label}}</button>
  </div>
  <p v-if="!workbench.projectId" class="empty">请先选择项目。</p>
  <p v-else-if="loading" class="empty" role="status">正在加载任务…</p>
  <p v-else-if="!shown.length" class="empty">{{ rendersOnly ? '当前项目暂无已验证成片。' : '没有符合当前条件的任务。' }}</p>
  <div v-if="offset || hasNext" class="actions task-pages">
    <button :disabled="!offset || loading" @click="page(-1)">上一页任务</button><button :disabled="!hasNext || loading" @click="page(1)">下一页任务</button>
    <span class="hint">任务第 {{ Math.floor(offset / pageSize) + 1 }} 页</span>
  </div>
  <div v-if="rendersOnly && !loading" class="render-gallery">
    <article v-for="(task,index) in shown" :key="task.id" class="render-item">
      <button v-if="index<8" class="render-thumb" type="button" :aria-label="'预览 '+title(task)" @click="preview = task.id">
        <video :src="`/api/tasks/${task.id}/output#t=0.1`" muted playsinline preload="metadata"></video>
        <Play :size="18" aria-hidden="true" />
      </button>
      <div v-else class="render-icon"><Film :size="23" aria-hidden="true" /></div>
      <div class="render-summary">
        <div class="actions"><strong>{{title(task)}}</strong><span class="status succeeded">已验证</span></div>
        <p class="hint">{{ task.output.width }} × {{ task.output.height }} · {{ task.output.duration?.toFixed(2) }} 秒 · {{ ((task.output.size_bytes || 0) / 1024 ** 2).toFixed(2) }} MiB · {{ task.output.has_audio ? '有音轨' : '无音轨' }}</p>
        <div class="actions">
          <button @click="preview = task.id"><Play :size="14" aria-hidden="true" />预览成片</button>
          <a :href="`/api/tasks/${task.id}/output?download=true`"><ArrowDownToLine :size="14" aria-hidden="true" />下载</a>
        </div>
      </div>
    </article>
  </div>
  <div v-else-if="!rendersOnly && !loading" class="task-rows">
   <article v-for="task in shown" :key="task.id" class="task task-record">
    <div><div class="actions"><strong>{{ title(task) }}</strong><span :class="['status', task.status]">{{ task.cancel_requested && task.status === 'running' ? '取消中' : labels[task.status] || task.status }}</span></div>
        <p class="mono">{{ kinds[task.kind] || task.kind }} · {{ task.id }}</p>
        <p v-if="task.stage === 'retry_wait'" class="hint">{{ task.error_code }} · 计划重试 {{ new Date(task.next_run_at).toLocaleString('zh-CN') }}</p>
        <p>{{ stages[task.stage] || task.stage }} · 本次耗时 {{ task.elapsed_seconds.toFixed(1) }} 秒 · 尝试 {{ task.attempt }}</p>
        <progress v-if="isRender(task) && task.status === 'running'" :value="task.progress" max="100" aria-label="编码进度"></progress>
        <span v-if="isRender(task)" class="hint">{{ task.progress.toFixed(1) }}%</span>
        <details v-if="isRender(task) || task.batch_id || task.story_version_id"><summary>{{isRender(task) ? '已保存处理参数' : '任务引用'}}</summary>
          <p v-if="task.batch_id" class="mono">批次 {{ task.batch_id }}</p>
          <p v-if="task.story_version_id" class="mono">创作版本 {{ task.story_version_id }}</p>
          <pre v-if="isRender(task)">{{ JSON.stringify(task.parameters, null, 2) }}</pre>
        </details>
        <p v-if="task.error" class="error">{{ task.error }}</p>
    </div>
    <div class="actions record-buttons">
      <button @click="logs(task.id)">日志</button>
      <button v-if="['queued', 'running'].includes(task.status)" :disabled="busy || task.cancel_requested" @click="control(task, 'cancel')">取消</button>
      <button v-if="canRetry(task)" :disabled="busy" @click="control(task, 'retry')">安全重试</button>
      <RouterLink v-if="task.kind==='image_candidate'" :to="{name:'generation',query:{project:workbench.projectId,imageTask:task.id},hash:'#image-candidates'}">打开图片审核</RouterLink>
      <button v-if="finished(task)" @click="preview = task.id">预览成片</button>
      <a v-if="finished(task)" :href="`/api/tasks/${task.id}/output?download=true`">下载成片</a>
    </div>
   </article>
  </div>
  <section v-if="selectedLog">
    <AttemptHistory :task-id="selectedLog" /><h2>事件日志</h2><p class="mono">{{ selectedLog }}</p>
    <p v-for="event in events" :key="event.id" class="log">{{ new Date(event.created_at).toLocaleString('zh-CN') }} · 尝试 {{ event.attempt }} · {{ event.message }}</p>
    <button @click="logs(selectedLog)">刷新日志</button>
  </section>
  <OutputPreview v-model="preview" />
 </section>
</template>

<style scoped>
.task-heading { display:flex; align-items:start; justify-content:space-between; gap:12px }
.task-heading h2 { margin-bottom:4px }
.task-heading p { margin-bottom:12px }
.task-filters { display:flex; gap:7px; align-items:center; flex-wrap:wrap; color:var(--accent); margin-bottom:9px }
.task-filters button[aria-pressed=true] { color:var(--accent); border-color:var(--accent); background:var(--accent-surface) }
.task-pages { margin-bottom:10px }
.task-record { border:0; border-top:1px solid var(--line-soft); border-radius:0; margin:0; padding:11px 0; align-items:start; justify-content:space-between }
.task-record > .record-buttons { flex:0 1 auto; min-width:0 }
.task-record details { background:var(--surface-raised); padding:8px; font-size:12px }
.task-record details pre { margin-bottom:0 }
.task-record strong { overflow-wrap:anywhere }
.render-gallery { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(310px,100%),1fr)); gap:12px }
.render-item { display:flex; gap:12px; border:1px solid var(--line-soft); padding:13px; min-width:0; background:var(--surface-raised); border-radius:9px }
.render-icon { flex:0 0 42px; height:46px; border-radius:8px; display:grid; place-items:center; background:var(--accent-surface); color:var(--accent) }
.render-thumb { position:relative; flex:0 0 clamp(75px,10vw,132px); align-self:center; overflow:hidden; padding:0!important; border-radius:7px!important; aspect-ratio:16/9 }
.render-thumb video { display:block; width:100%; height:100%; object-fit:cover }
.render-thumb svg { position:absolute; bottom:5px; left:5px; color:white; background:#121c278c; border-radius:50%; padding:2px; }
.render-summary { min-width:0; overflow-wrap:anywhere }
.render-summary p { margin:6px 0 }
.render-summary button,.render-summary a { display:inline-flex; gap:6px; align-items:center }
</style>
