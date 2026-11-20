<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import AttemptHistory from '../../AttemptHistory.vue'
import OutputPreview from '../ui/OutputPreview.vue'
import { api, post } from '../../services/api'
import { useWorkbench } from '../../stores/workbench'
import type { Task } from '../../types/workbench'

const props = defineProps<{ rendersOnly?: boolean }>()
const workbench = useWorkbench()
const tasks = ref<Task[]>([]), offset = ref(0), error = ref(''), busy = ref(false)
const preview = ref(''), selectedLog = ref('')
const events = ref<{ id: number; created_at: string; attempt: number; message: string }[]>([])
const pageSize = 50
const labels: Record<string, string> = { queued:'排队中', running:'执行中', succeeded:'已完成', failed:'失败', cancelled:'已取消' }
const kinds: Record<string, string> = { probe:'读取媒体信息', analyze:'媒体解析', render:'视频剪辑', adapt:'剧情改编', still_motion:'运镜候选', local_voice:'本机配音', timeline_render:'多轨渲染', qc_review:'技术质检', delivery:'整剧交付', promotion:'推广包' }
const stages: Record<string, string> = { queued:'等待领取', recovered:'中断恢复', inspecting:'检查输入', encoding:'FFmpeg 编码', validating:'验证成片', publishing:'发布输出', succeeded:'完成', failed:'失败', cancelled:'已取消', retry_wait:'等待自动重试', checkpoint:'核验检查点', resuming_checkpoint:'复用编码检查点', awaiting_review:'待人工审核', approved:'人工已通过', rejected:'人工已拒绝', settlement_recovery:'恢复用量核算', dispatching:'模型调用处理中', received:'响应已保存，核算中' }
let timer: ReturnType<typeof setInterval> | undefined
let pending: AbortController | undefined
const isRender = (task: Task) => ['render', 'timeline_render'].includes(task.kind)
const finished = (task: Task) => isRender(task) && task.status === 'succeeded'
const shown = computed(() => props.rendersOnly ? tasks.value.filter(finished) : tasks.value)
const title = (task: Task) => workbench.assets.find(asset => asset.id === task.asset_id)?.name || kinds[task.kind] || task.kind

async function refresh() {
  if (!workbench.projectId) return
  pending?.abort()
  const controller = new AbortController()
  pending = controller
  try {
    const list = await api<Task[]>(`/projects/${workbench.projectId}/tasks?offset=${offset.value}&limit=${pageSize}`, { signal: controller.signal })
    if (!controller.signal.aborted) tasks.value = list
  } catch (failure) { if (!controller.signal.aborted) error.value = String(failure) }
  finally { if (pending === controller) pending = undefined }
}

function page(direction: number) {
  offset.value = Math.max(0, offset.value + pageSize * direction)
  selectedLog.value = ''
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
  void refresh()
  timer = setInterval(() => { if (!pending && document.visibilityState !== 'hidden') void refresh() }, 3000)
})
onUnmounted(() => { clearInterval(timer); pending?.abort() })
watch(() => workbench.refreshCount, () => { void refresh() })
</script>

<template>
  <h2>{{ rendersOnly ? '已验证成片' : '持久化任务队列' }}</h2>
  <p v-if="error" class="error" role="alert">{{ error }} <button @click="error = ''">关闭</button></p>
  <p v-if="!workbench.projectId" class="empty">请先选择项目。</p>
  <p v-else-if="!shown.length" class="empty">{{ rendersOnly ? '当前任务页暂无已验证成片。' : '当前项目暂无任务。' }}</p>
  <div v-if="offset || tasks.length === pageSize" class="actions">
    <button :disabled="!offset" @click="page(-1)">上一页任务</button><button :disabled="tasks.length < pageSize" @click="page(1)">下一页任务</button>
    <span class="hint">任务第 {{ Math.floor(offset / pageSize) + 1 }} 页</span>
  </div>
  <article v-for="task in shown" :key="task.id" class="task">
    <div><strong>{{ title(task) }}</strong>
      <template v-if="rendersOnly"><p>{{ task.output.width }} × {{ task.output.height }} · {{ task.output.duration?.toFixed(2) }} 秒 · {{ ((task.output.size_bytes || 0) / 1024 ** 2).toFixed(2) }} MB · {{ task.output.has_audio ? '有音轨' : '无音轨' }}</p></template>
      <template v-else>
        <p class="mono">{{ kinds[task.kind] || task.kind }} · {{ task.id }}</p>
        <p v-if="task.batch_id" class="mono">批次 {{ task.batch_id }}</p>
        <p v-if="task.story_version_id" class="mono">创作版本 {{ task.story_version_id }}</p>
        <p v-if="task.stage === 'retry_wait'" class="hint">{{ task.error_code }} · 计划重试 {{ new Date(task.next_run_at).toLocaleString('zh-CN') }}</p>
        <p>{{ stages[task.stage] || task.stage }} · 本次耗时 {{ task.elapsed_seconds.toFixed(1) }} 秒 · 尝试 {{ task.attempt }}</p>
        <progress v-if="isRender(task) && task.status === 'running'" :value="task.progress" max="100" aria-label="编码进度"></progress>
        <span v-if="isRender(task)" class="hint">{{ task.progress.toFixed(1) }}%</span>
        <details v-if="isRender(task)"><summary>已保存处理参数</summary><pre>{{ JSON.stringify(task.parameters, null, 2) }}</pre></details>
        <p v-if="task.error" class="error">{{ task.error }}</p>
      </template>
    </div>
    <template v-if="!rendersOnly">
      <span :class="['status', task.status]">{{ task.cancel_requested && task.status === 'running' ? '取消中' : labels[task.status] || task.status }}</span>
      <button @click="logs(task.id)">日志</button>
      <button v-if="['queued', 'running'].includes(task.status)" :disabled="busy || task.cancel_requested" @click="control(task, 'cancel')">取消</button>
      <button v-if="task.kind !== 'adapt' && ['failed', 'cancelled'].includes(task.status)" :disabled="busy" @click="control(task, 'retry')">安全重试</button>
    </template>
    <button v-if="finished(task)" @click="preview = task.id">预览成片</button>
    <a v-if="finished(task)" :href="`/api/tasks/${task.id}/output?download=true`">{{ rendersOnly ? '下载' : '下载成片' }}</a>
  </article>
  <section v-if="selectedLog">
    <AttemptHistory :task-id="selectedLog" /><h2>事件日志</h2><p class="mono">{{ selectedLog }}</p>
    <p v-for="event in events" :key="event.id" class="log">{{ new Date(event.created_at).toLocaleString('zh-CN') }} · 尝试 {{ event.attempt }} · {{ event.message }}</p>
    <button @click="logs(selectedLog)">刷新日志</button>
  </section>
  <OutputPreview v-model="preview" />
</template>
