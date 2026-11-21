<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { AudioLines, Film, Link2, List, RefreshCw, ScanLine, Subtitles } from 'lucide-vue-next'
import AnalysisReview from './AnalysisReview.vue'
import AnalysisWaveform from './AnalysisWaveform.vue'
import SubtitleDraft from './SubtitleDraft.vue'
import {
  artifactUrl, clock, operationLabels, request, statusLabels,
  type Job, type Operation, type Result, type Version,
} from './analysisApi'

const props = defineProps<{
  projectId: string
  assets: { id:string; name:string; size_bytes:number; authorization:string }[]
  initialAssetId: string
  initialTaskId: string
  initialTime: string
  initialProxy: string
  reviewLink: (asset:string, task:string, time:number, proxy:string) => string
}>()
const emit = defineEmits<{ adaptation: [version: Version]; assetsChanged: []; editVideo: [source: string, subtitle: string] }>()
const supported = computed(() => props.assets.filter(asset => /\.(mp4|mov|mkv|webm|avi|wav|mp3)$/i.test(asset.name)))
const assetId = ref('')
const currentAsset = computed(() => supported.value.find(asset => asset.id === assetId.value))
const jobs = ref<Job[]>([]), results = ref<Result[]>([]), activeResult = ref<Result | null>(null)
const selectedJob = ref(''), viewSource = ref(''), playing = ref<HTMLMediaElement | null>(null), playhead = ref(0)
const playerDuration = ref(0), pendingSeek = ref<number|null>(null), playbackError = ref(false)
const linkError = ref(''), previewTask = ref(''), pendingProxy = ref(''), pendingTask = ref('')
const subtitleTrack = ref(0), subtitlePage = ref(0), draftCue = ref(0)
const taskFilter = ref<'all'|'running'|'issues'>('all')
const checked = ref<Operation[]>(['inspect'])
const operations = Object.keys(operationLabels) as Operation[]
const error = ref(''), notice = ref(''), busy = ref(false), loading = ref(false)
const logFiles = ref<{name:string;tail:string}[] | null>(null)
const capabilities = ref<{id:string;label:string;available:boolean;languages?:string[]}[]>([])
const ocrLanguages = computed(() => capabilities.value.find(item => item.id==='ocr')?.languages || [])
const pendingModels = computed(() => capabilities.value.filter(item => !item.available).map(item => item.label).join('、'))
const options = reactive({
  container:'mkv', max_edge:720, crf:20, fps:null as number|null, sample_rate:48000,
  channels:null as number|null, frame_mode:'interval', frame_interval:5, frame_time:0,
  scene_threshold:0.30, minimum_shot_seconds:0.30, silence_db:-40, silence_seconds:0.4,
  ocr_language:'', ocr_interval:2,
  hard_start:0, hard_end:'' as number | '', hard_interval:0.5, hard_region:'lower',
})
const streamsByStep = reactive<Partial<Record<Operation,number>>>({})
const audioOnly = computed(() => /\.(wav|mp3)$/i.test(currentAsset.value?.name || ''))
const queuePath = computed(() => `/analysis/projects/${props.projectId}/assets/${assetId.value}/tasks`)
const sourceUrl = computed(() => viewSource.value || `/api/assets/${assetId.value}/media`)
const keys = new Map<string,string>()
const cache = new Map<string,Result>()
let scope = 0
let timer: ReturnType<typeof setInterval> | undefined

const reviewTabs = [
  { op:'scenes', icon:Film, label:'镜头' }, { op:'frames', icon:ScanLine, label:'关键帧' },
  { op:'subtitles', icon:Subtitles, label:'字幕' }, { op:'waveform', icon:AudioLines, label:'波形' },
  { op:'hard_subtitles', icon:Subtitles, label:'硬字幕' },
  { op:'ocr', icon:ScanLine, label:'OCR' }, { op:'inspect', icon:List, label:'媒体流' },
] as const
const byOperation = computed(() => new Map(results.value.map(result => [result.operation,result])))
const reviewResults = computed(() => {
  const selected = activeResult.value
  if (!selected || byOperation.value.get(selected.operation)?.task_id === selected.task_id) return results.value
  return [...results.value.filter(result => result.operation !== selected.operation), selected]
})
const selectedRow = computed(() => jobs.value.find(job => job.id === selectedJob.value))
const scenes = computed(() => activeResult.value?.operation === 'scenes' ? activeResult.value : byOperation.value.get('scenes'))
const proxy = computed(() => activeResult.value?.operation === 'transcode' ? activeResult.value : byOperation.value.get('transcode'))
const duration = computed(() => Math.max(playerDuration.value, scenes.value?.shots?.at(-1)?.end_us || 0))
const captions = computed(() => activeResult.value?.subtitle_tracks || [])
const hardScan = computed(() => activeResult.value?.hard_subtitle_scan)
const currentTrack = computed(() => captions.value.find(track => track.stream_index === subtitleTrack.value))
const activeCue = computed(() => currentTrack.value?.cues.findIndex(cue => cue.start_us <= playhead.value && playhead.value < cue.end_us) ?? -1)
const pageSize = 50
const cuePage = computed(() => currentTrack.value?.cues.slice(subtitlePage.value * pageSize, (subtitlePage.value + 1)*pageSize) || [])
const selectedCaption = computed(() => currentTrack.value?.cues[draftCue.value])
const visibleJobs = computed(() => jobs.value.filter(job => taskFilter.value === 'all' ||
  (taskFilter.value === 'running' ? ['queued','running'].includes(job.status) : ['failed','cancelled'].includes(job.status))))
const linkHref = computed(() => props.reviewLink(assetId.value,selectedJob.value,playhead.value,previewTask.value))
const streamSelectors = computed(() => {
  const media = byOperation.value.get('inspect')?.media?.streams || []
  const types: Partial<Record<Operation,string[]>> = {
    split:['video','audio','subtitle'], subtitles:['subtitle'], waveform:['audio'],
    frames:['video'], scenes:['video'], transcode:['video'], ocr:['video'], hard_subtitles:['video'],
  }
  return checked.value.flatMap(op => {
    const streams = media.filter(stream => types[op]?.includes(stream.codec_type) && !stream.disposition?.attached_pic)
    return streams.length ? [{op,streams}] : []
  })
})

async function loadResult(taskId: string) {
  const cached = cache.get(taskId)
  if (cached) return cached
  const result = await request<Result>(`/analysis/tasks/${taskId}/result`)
  if (cache.size >= 24) cache.delete(cache.keys().next().value!)
  cache.set(taskId,result)
  return result
}
async function refresh() {
  if (!currentAsset.value || loading.value) return
  const requestScope = scope
  const path = queuePath.value
  loading.value = true
  try {
    const list = await request<Job[]>(path)
    if (requestScope !== scope) return
    const linkedTask = pendingTask.value || (selectedJob.value === props.initialTaskId ? selectedJob.value : '')
    if (linkedTask && !list.some(job => job.id === linkedTask)) {
      try {
        const linked = await request<Job>(`${path}/${encodeURIComponent(linkedTask)}`)
        if (requestScope !== scope) return
        list.push(linked)
      } catch (failure) {
        if (requestScope !== scope) return
        linkError.value = String(failure)
        pendingTask.value = ''
      }
    }
    if (pendingTask.value && list.some(job => job.id === pendingTask.value)) {
      selectedJob.value = pendingTask.value
      pendingTask.value = ''
      linkError.value = ''
    }
    jobs.value = list
    const latest = [...new Set(list.filter(job => job.status === 'succeeded').map(job => job.parameters.operation))]
      .map(op => list.find(job => job.parameters.operation === op && job.status === 'succeeded')!.id)
    const values = await Promise.all(latest.map(loadResult))
    if (requestScope !== scope) return
    results.value = values
    const selected = list.find(job => job.id === selectedJob.value)
    if (selected?.status === 'succeeded' && activeResult.value?.task_id !== selected.id) {
      const result = await loadResult(selected.id)
      if (requestScope === scope && selectedJob.value === selected.id) activeResult.value = result
    }
    if (pendingProxy.value) {
      const id = pendingProxy.value
      try {
        const job = list.find(row => row.id === id) || await request<Job>(`${path}/${encodeURIComponent(id)}`)
        if (job.parameters.operation !== 'transcode' || job.status !== 'succeeded') throw new Error('链接中的代理尚不可用')
        const linkedProxy = await loadResult(job.id)
        if (requestScope === scope && pendingProxy.value === id) previewProxy(linkedProxy)
      } catch (failure) {
        if (requestScope === scope) {
          linkError.value = String(failure)
          pendingProxy.value = ''
        }
      }
    } else if (proxy.value?.artifacts[0] && playbackError.value && !viewSource.value) {
      previewProxy()
    }
  } finally {
    if (requestScope === scope) loading.value = false
  }
}
async function run(action: () => Promise<void>) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await action() } catch (failure) { error.value = String(failure) } finally { busy.value = false }
}
function payload(operation: Operation) {
  const stream = streamsByStep[operation]
  const common = {operation, ...(stream !== undefined ? {stream} : {})}
  if (operation === 'remux') return {...common, container:options.container}
  if (operation === 'transcode') {
    const {max_edge,crf,fps,sample_rate,channels} = options
    return {...common,max_edge,crf,fps,sample_rate,channels}
  }
  if (operation === 'frames') {
    const {frame_mode,frame_interval,frame_time} = options
    return {...common,frame_mode,frame_interval,frame_time}
  }
  if (operation === 'scenes') {
    const {scene_threshold,minimum_shot_seconds} = options
    return {...common,scene_threshold,minimum_shot_seconds}
  }
  if (operation === 'waveform') {
    const {silence_db,silence_seconds} = options
    return {...common,silence_db,silence_seconds}
  }
  if (operation === 'ocr') return {...common, ocr_language:options.ocr_language, frame_interval:options.ocr_interval}
  if (operation === 'hard_subtitles') return {...common, ocr_language:options.ocr_language,
    scan_start_ms:Math.round(options.hard_start*1000), scan_end_ms:options.hard_end==='' ? null : Math.round(options.hard_end*1000),
    subtitle_interval:options.hard_interval, subtitle_region:options.hard_region}
  return common
}
async function submit() {
  await run(async () => {
    const body = {asset_id:assetId.value, steps:checked.value.filter(op => !disabled(op)).map(payload)}
    const signature = JSON.stringify(body)
    const key = keys.get(signature) || crypto.randomUUID()
    keys.set(signature,key)
    const queued = await request<Job[]>(`/analysis/projects/${props.projectId}/tasks`, {...body,idempotency_key:key})
    if (body.asset_id !== assetId.value) return
    keys.delete(signature)
    if (queued[0]) selectedJob.value = queued[0].id
    await refresh()
    notice.value = `已提交 ${queued.length} 项解析任务`
  })
}
function disabled(operation: Operation) {
  if (operation === 'ocr' || operation === 'hard_subtitles') return audioOnly.value || !ocrLanguages.value.length
  return audioOnly.value && ['frames','scenes','transcode','subtitles'].includes(operation)
}
async function openJob(job: Job) {
  selectedJob.value = job.id
  logFiles.value = null
  activeResult.value = null
  if (job.status === 'succeeded') await run(async () => {
    const result = await loadResult(job.id)
    if (selectedJob.value === job.id) activeResult.value = result
  })
}
async function showOperation(operation: Operation) {
  const result = byOperation.value.get(operation)
  const job = result && jobs.value.find(row => row.id === result.task_id)
  if (job) await openJob(job)
}
async function showLogs(job: Job) {
  await run(async () => {
    const result = await request<{files:{name:string;tail:string}[]}>(`/analysis/tasks/${job.id}/logs/${job.attempt}`)
    if (selectedJob.value === job.id) logFiles.value = result.files
  })
}
async function control(job: Job, action: 'retry'|'cancel') {
  await run(async () => {
    await request(`/tasks/${job.id}/${action}`,{})
    await refresh()
  })
}
function seek(time: number) {
  const requested = Math.max(0,Math.round(time))
  const media = playing.value
  if (!media || !Number.isFinite(media.duration)) {
    playhead.value = requested
    pendingSeek.value = requested
    return
  }
  pendingSeek.value = null
  const clamped = Math.min(media.duration,requested/1_000_000)
  media.currentTime = clamped
  playhead.value = Math.round(clamped*1_000_000)
}
function metadata(event: Event) {
  const media = event.target as HTMLMediaElement
  if (media !== playing.value) return
  playerDuration.value = Number.isFinite(media.duration) ? Math.round(media.duration*1_000_000) : 0
  if (pendingSeek.value !== null) seek(pendingSeek.value)
}
function updatePlayhead(event: Event) {
  const media = event.target as HTMLMediaElement
  if (media === playing.value && pendingSeek.value === null) playhead.value = Math.round(media.currentTime*1_000_000)
}
function changeSource(url: string, task = '') {
  if (viewSource.value === url) return
  pendingSeek.value = playhead.value
  playerDuration.value = 0
  playbackError.value = false
  previewTask.value = task
  viewSource.value = url
}
function previewProxy(result = proxy.value) {
  if (!result?.artifacts[0]) return
  pendingProxy.value = ''
  changeSource(artifactUrl(result.task_id,result.artifacts[0].id),result.task_id)
}
function mediaError() {
  if (!viewSource.value && proxy.value && !pendingProxy.value) previewProxy()
  else playbackError.value = true
}
function seekCue(index: number) {
  if (index < 0) return
  const cue = currentTrack.value?.cues[index]
  if (!cue) return
  subtitlePage.value = Math.floor(index/pageSize)
  draftCue.value = index
  seek(cue.start_us)
}
function initialPosition() {
  const raw = props.initialTime
  const us = /^\d{1,12}$/.test(raw) ? Number(raw) : 0
  return Number.isSafeInteger(us) ? us : 0
}
watch(activeResult, result => {
  subtitleTrack.value = result?.subtitle_tracks?.[0]?.stream_index ?? 0
  subtitlePage.value = 0
  draftCue.value = 0
})
watch(subtitleTrack, () => { subtitlePage.value = 0; draftCue.value = 0 })
watch(assetId, () => {
  scope++
  loading.value = false
  jobs.value = []
  results.value = []
  activeResult.value = null
  selectedJob.value = ''
  viewSource.value = ''
  previewTask.value = ''
  logFiles.value = null
  const linked = assetId.value !== '' && assetId.value === props.initialAssetId
  playhead.value = linked ? initialPosition() : 0
  pendingSeek.value = linked ? playhead.value : null
  pendingTask.value = linked ? props.initialTaskId : ''
  pendingProxy.value = linked ? props.initialProxy : ''
  playbackError.value = false
  playerDuration.value = 0
  taskFilter.value = 'all'
  for (const operation of operations) delete streamsByStep[operation]
  linkError.value = ''
  error.value = ''
  if (assetId.value) void run(refresh)
})
watch(supported, assets => {
  if (!assets.some(asset => asset.id === assetId.value)) assetId.value = assets.find(asset => asset.id === props.initialAssetId)?.id || assets[0]?.id || ''
}, {immediate:true})
onMounted(() => {
  void run(async () => {
    const status = await request<{capabilities:typeof capabilities.value}>('/analysis/capabilities')
    capabilities.value = status.capabilities
    options.ocr_language = ocrLanguages.value[0] || ''
    await refresh()
  })
  timer = setInterval(() => { if (!busy.value) void refresh().catch(failure => { error.value=String(failure) }) }, 3000)
})
onUnmounted(() => { scope++; clearInterval(timer) })
</script>

<template>
  <p v-if="!projectId" class="empty">选择项目以开始媒体解析。</p>
  <div v-else class="analysis-workspace">
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="linkError" class="error" role="alert">定位链接不可用。{{ linkError }}</p>
    <p v-if="initialAssetId && assets.length && !supported.some(asset => asset.id === initialAssetId)"
      class="error" role="alert">链接中的音视频素材在当前项目不可用。</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="!supported.length" class="empty">先在素材资产中心导入音视频。</p>
    <template v-else>
      <div class="analysis-source">
        <label>解析素材<select v-model="assetId" :disabled="busy">
          <option v-for="asset in supported" :key="asset.id" :value="asset.id">{{ asset.name }}</option>
        </select></label>
        <p v-if="currentAsset" class="hint">{{ (currentAsset.size_bytes/1024**2).toFixed(2) }} MiB · {{ currentAsset.authorization }}</p>
      </div>
      <div class="analysis-desk">
        <section class="analysis-viewer" aria-label="审片预览与时间轴">
          <div class="analysis-panel-bar">
            <h2>{{ viewSource ? '代理预览' : '原素材预览' }}</h2>
            <div class="actions source-actions">
              <button v-if="viewSource" type="button" @click="changeSource('')">返回原素材</button>
              <button v-else-if="proxy" type="button" @click="previewProxy()">切换到代理</button>
              <a class="analysis-link" :href="linkHref" target="_blank" rel="noopener">
                <Link2 :size="15" aria-hidden="true" />定位链接
              </a>
            </div>
          </div>
          <div class="analysis-monitor" :class="{ 'audio-monitor':audioOnly }">
            <audio v-if="audioOnly" :key="sourceUrl" ref="playing" :src="sourceUrl" controls preload="metadata"
              @loadedmetadata="metadata" @timeupdate="updatePlayhead" @error="mediaError"></audio>
            <video v-else :key="sourceUrl" ref="playing" :src="sourceUrl" controls preload="metadata"
              @loadedmetadata="metadata" @timeupdate="updatePlayhead" @error="mediaError"></video>
          </div>
          <p v-if="playbackError" class="hint">浏览器无法播放当前文件。可运行 MP4 转码生成代理。</p>
          <div class="time-readout">
            <output aria-label="源时间">{{ clock(playhead) }}</output>
            <span v-if="duration">{{ clock(duration) }}</span>
          </div>
          <input v-if="duration" class="source-seek" type="range" min="0" :max="duration" step="10000"
            aria-label="定位源时间" :aria-valuetext="clock(playhead)" :value="Math.min(playhead,duration)"
            @input="seek(Number(($event.target as HTMLInputElement).value))">
          <div v-if="scenes?.shots?.length" class="shot-ruler" aria-label="镜头时间轴">
            <button v-for="(shot,index) in scenes.shots" :key="shot.start_us" class="shot-marker"
              type="button" :style="{ flexGrow:shot.end_us-shot.start_us }"
              :aria-label="'镜头 '+(index+1)+' · '+clock(shot.start_us)"
              :aria-pressed="shot.start_us<=playhead && playhead<shot.end_us"
              :title="clock(shot.start_us)+' – '+clock(shot.end_us)" @click="seek(shot.start_us)">
              {{ index+1 }}
            </button>
          </div>
          <div class="analysis-tabs" aria-label="解析结果">
            <button v-for="tab in reviewTabs" :key="tab.op" type="button" :aria-pressed="activeResult?.operation===tab.op"
              :disabled="!byOperation.has(tab.op)" :title="tab.label" @click="showOperation(tab.op)">
              <component :is="tab.icon" :size="15" aria-hidden="true" />{{ tab.label }}
            </button>
          </div>
          <AnalysisWaveform v-if="activeResult?.operation === 'waveform'" :result="activeResult" :playhead="playhead" @seek="seek" />
          <p v-if="currentTrack && activeCue>=0" class="active-caption">{{ currentTrack.cues[activeCue]?.text }}</p>
        </section>
        <section class="analysis-tools" aria-label="解析设置与任务">
          <h2>本地处理</h2>
          <form class="analysis-options" @submit.prevent="submit">
            <fieldset>
              <legend>选择步骤</legend>
              <span class="analysis-choices">
                <label v-for="operation in operations" :key="operation" class="check">
                  <input v-model="checked" type="checkbox" :value="operation" :disabled="disabled(operation)">{{ operationLabels[operation] }}
                </label>
              </span>
            </fieldset>
            <details v-if="streamSelectors.length || checked.some(op => !['inspect','split','subtitles'].includes(op))">
              <summary>解析参数</summary>
              <div class="editor-grid">
                <label v-for="{op,streams} in streamSelectors" :key="op">{{ operationLabels[op] }}源流<select v-model="streamsByStep[op]">
                  <option :value="undefined">自动选择</option>
                  <option v-for="stream in streams" :key="stream.index" :value="stream.index">
                    流 {{ stream.index }} · {{ stream.codec_type }} · {{ stream.language || stream.codec_name }}
                  </option>
                </select></label>
                <label v-if="checked.includes('remux')">转封装格式<select v-model="options.container"><option value="mkv">MKV</option><option value="mp4">MP4</option></select></label>
                <template v-if="checked.includes('transcode')">
                  <label>代理最大边长<select v-model.number="options.max_edge"><option v-for="edge in [480,720,1080,1920,3840]" :key="edge">{{ edge }}</option></select></label>
                  <label>画质 CRF<input v-model.number="options.crf" type="number" min="0" max="28"></label>
                  <label>目标帧率<select v-model="options.fps"><option :value="null">沿用源帧序列</option><option v-for="fps in [24,25,30,60]" :key="fps" :value="fps">{{ fps }}</option></select></label>
                  <label>音频采样率<select v-model.number="options.sample_rate"><option>32000</option><option>44100</option><option>48000</option></select></label>
                  <label>声道<select v-model="options.channels"><option :value="null">沿用源声道</option><option :value="1">单声道</option><option :value="2">立体声</option></select></label>
                </template>
                <template v-if="checked.includes('frames')">
                  <label>抽帧方式<select v-model="options.frame_mode"><option value="interval">固定间隔</option><option value="keyframe">源关键帧</option><option value="at">指定时间</option></select></label>
                  <label v-if="options.frame_mode === 'interval'">间隔（秒）<input v-model.number="options.frame_interval" type="number" min="0.25" max="3600" step="0.01"></label>
                  <label v-if="options.frame_mode === 'at'">时间（秒）<input v-model.number="options.frame_time" type="number" min="0" max="86400" step="0.001"></label>
                </template>
                <template v-if="checked.includes('scenes')">
                  <label>切镜阈值<input v-model.number="options.scene_threshold" type="number" min="0.05" max="0.95" step="0.01"></label>
                  <label>镜头最短时长（秒）<input v-model.number="options.minimum_shot_seconds" type="number" min="0.1" max="60" step="0.01"></label>
                </template>
                <template v-if="checked.includes('waveform')">
                  <label>静音阈值（dB）<input v-model.number="options.silence_db" type="number" min="-99" max="-10"></label>
                  <label>最短静音（秒）<input v-model.number="options.silence_seconds" type="number" min="0.1" max="60" step="0.01"></label>
                </template>
                <template v-if="checked.includes('ocr') || checked.includes('hard_subtitles')">
                  <label>OCR 语言<select v-model="options.ocr_language"><option v-for="language in ocrLanguages" :key="language">{{ language }}</option></select></label>
                  <label v-if="checked.includes('ocr')">OCR 采样间隔（秒）<input v-model.number="options.ocr_interval" type="number" min="0.25" max="3600" step="0.01"></label>
                </template>
                <template v-if="checked.includes('hard_subtitles')">
                  <label>硬字幕画面区域<select v-model="options.hard_region"><option value="lower">画面底部 40%</option><option value="full">完整画面</option></select></label>
                  <label>硬字幕采样间隔（秒）<input v-model.number="options.hard_interval" type="number" min="0.25" max="2" step="0.01" required></label>
                  <label>硬字幕开始（秒）<input v-model.number="options.hard_start" type="number" min="0" max="86399.999" step="0.001" required></label>
                  <label>硬字幕结束（秒）<input v-model.number="options.hard_end" type="number" min="0.001" max="86400" step="0.001" placeholder="留空扫描到结尾"></label>
                  <p class="hint">每次最多 120 帧。长片可分段扫描。</p>
                </template>
              </div>
            </details>
            <button class="primary" :disabled="busy || !currentAsset || !checked.some(op => !disabled(op))">提交本地解析</button>
          </form>
          <details v-if="pendingModels" class="analysis-capabilities">
            <summary>感知能力</summary><p class="hint">待接入：{{ pendingModels }}</p>
          </details>
          <div class="analysis-panel-bar task-header">
            <h2>解析记录</h2>
            <button class="analysis-refresh" type="button" aria-label="刷新解析记录" title="刷新解析记录"
              :disabled="busy || loading" @click="run(refresh)"><RefreshCw :size="16" aria-hidden="true" /></button>
          </div>
          <div v-if="jobs.length" class="queue-filter" aria-label="筛选解析记录">
            <button v-for="item in [{key:'all',label:'全部'},{key:'running',label:'进行中'},{key:'issues',label:'失败与取消'}] as const"
              :key="item.key" type="button" :aria-pressed="taskFilter===item.key" @click="taskFilter=item.key">{{ item.label }}</button>
          </div>
          <p v-if="!visibleJobs.length" class="hint">{{ loading ? '正在读取解析记录…' : '没有符合当前筛选的解析记录。' }}</p>
          <div v-else class="analysis-queue">
            <div v-for="job in visibleJobs" :key="job.id" class="analysis-job">
              <button class="select-job" type="button" :aria-pressed="selectedJob===job.id" :disabled="busy"
                @click="openJob(job)">{{ operationLabels[job.parameters.operation] }}</button>
              <span :class="['status',job.status]">{{ statusLabels[job.status] || job.status }}</span>
              <p class="task-stage hint">{{ statusLabels[job.stage] || job.stage }} · {{ job.elapsed_seconds.toFixed(1) }} 秒<span v-if="job.parameters.stream != null"> · 流 {{ job.parameters.stream }}</span></p>
              <p v-if="job.error" class="error task-stage">{{ job.error }}</p>
              <div v-if="job.status !== 'succeeded' || selectedJob === job.id" class="actions">
                <button v-if="['queued','running'].includes(job.status)" type="button" :disabled="busy || job.cancel_requested" @click="control(job,'cancel')">取消</button>
                <button v-if="['failed','cancelled'].includes(job.status)" type="button" :disabled="busy" @click="control(job,'retry')">重试</button>
                <button v-if="job.attempt && selectedJob===job.id" type="button" :disabled="busy" @click="showLogs(job)">执行日志</button>
              </div>
            </div>
          </div>
          <div v-if="logFiles" class="log-tail"><p v-if="!logFiles.length">没有可读取的日志文件。</p><pre v-for="file in logFiles" :key="file.name">{{ file.name }}{{ '\n' }}{{ file.tail }}</pre></div>
        </section>
      </div>
      <section v-if="activeResult" class="analysis-result">
        <h2>{{ operationLabels[activeResult.operation] }}</h2>
        <p class="hint">{{ activeResult.algorithm }}<span v-if="selectedRow?.parameters.stream != null"> · 流 {{ selectedRow.parameters.stream }}</span><span v-if="activeResult.reused_from_task_id"> · 已核对哈希并复用历史结果</span></p>
        <p v-if="activeResult.truncated" class="hint" role="status">结果达到当前采样或镜头上限。</p>
        <div v-if="activeResult.media" class="stream-list">
          <div v-for="stream in activeResult.media.streams" :key="stream.index" class="analysis-job">
            <strong>流 {{ stream.index }} · {{ stream.codec_type }} · {{ stream.codec_name }}</strong>
            <span v-if="stream.language">{{ stream.language }}</span>
            <span v-if="stream.display_size?.length">{{ stream.display_size.join(' × ') }}</span>
            <span v-if="stream.rotation">旋转 {{ stream.rotation }}°</span>
            <span v-if="stream.time_base">时间基 {{ stream.time_base }}</span>
            <span v-if="activeResult.cadence?.[String(stream.index)]">{{ activeResult.cadence[String(stream.index)].status }}</span>
          </div>
          <details><summary>完整媒体元数据</summary><pre class="log-tail">{{ JSON.stringify(activeResult.media,null,2) }}</pre></details>
        </div>
        <div v-if="activeResult.artifacts.length && !hardScan" class="artifacts" :class="{ filmstrip:['scenes','frames','ocr'].includes(activeResult.operation) }">
          <article v-for="file in activeResult.artifacts" :key="file.id">
            <button v-if="file.media_type === 'image/jpeg'" class="frame" @click="seek(file.time_us || 0)">
              <img :src="artifactUrl(activeResult.task_id,file.id)" loading="lazy" :alt="clock(file.time_us || 0)+' 处的画面'">
              {{ clock(file.time_us || 0) }}
            </button>
            <p>{{ file.name }} · {{ (file.size_bytes / 1024).toFixed(1) }} KiB</p>
            <div class="actions"><a :href="artifactUrl(activeResult.task_id,file.id,true)">下载</a>
              <button v-if="activeResult.operation==='transcode'" type="button" @click="previewProxy(activeResult)">预览代理</button>
            </div>
          </article>
        </div>
        <p v-if="activeResult.operation==='subtitles' && !captions.length" class="hint">此素材没有软字幕流。</p>
        <div v-if="currentTrack">
          <div v-if="hardScan" class="hard-subtitle-summary">
            <strong>OCR 估算时序</strong>
            <p>{{ clock(hardScan.start_us) }} – {{ clock(hardScan.end_us) }} · {{ hardScan.region==='lower' ? '画面底部 40%' : '完整画面' }} · {{ activeResult.ocr?.frames.length }} 帧</p>
            <p class="hint">请对照画面校正起止时间。需要烧录修订字幕时，在剪辑中选择无旧字幕的画面。</p>
          </div>
          <div class="subtitle-controls">
            <label v-if="!hardScan">字幕轨<select v-model.number="subtitleTrack">
              <option v-for="track in captions" :key="track.stream_index" :value="track.stream_index">
                流 {{ track.stream_index }} · {{ track.language || '语言未标注' }}
              </option>
            </select></label>
            <button type="button" :disabled="activeCue<0" @click="seekCue(activeCue)">定位当前字幕</button>
          </div>
          <p class="hint">{{ currentTrack.cues.length }} 条<span v-if="hardScan && !currentTrack.cues.length"> · 扫描范围内未找到字幕候选</span>
            <span v-else-if="!hardScan && currentTrack.status !== 'extracted'"> · {{ currentTrack.status }}</span></p>
          <div v-if="currentTrack.cues.length" class="subtitle-workspace">
            <div class="cue-browser">
              <div class="cue-list">
                <button v-for="(cue,index) in cuePage" :key="subtitlePage*pageSize+index" type="button"
                  :aria-pressed="draftCue===subtitlePage*pageSize+index" :data-playing="activeCue===subtitlePage*pageSize+index"
                  @click="seekCue(subtitlePage*pageSize+index)">
                  <time>{{ clock(cue.start_us) }} – {{ clock(cue.end_us) }}</time><span>{{ cue.text }}</span>
                  <small v-if="cue.sample_count">{{ cue.sample_count }} 帧采样</small>
                </button>
              </div>
              <div v-if="currentTrack.cues.length>pageSize" class="actions cue-pager">
                <button type="button" :disabled="subtitlePage===0" @click="subtitlePage--">上一页</button>
                <span>{{ subtitlePage+1 }} / {{ Math.ceil(currentTrack.cues.length/pageSize) }}</span>
                <button type="button" :disabled="(subtitlePage+1)*pageSize>=currentTrack.cues.length" @click="subtitlePage++">下一页</button>
              </div>
              <figure v-if="selectedCaption?.artifact != null" class="caption-evidence">
                <img :src="artifactUrl(activeResult.task_id,selectedCaption.artifact)" alt="所选字幕的首个识别画面">
                <figcaption>首个识别画面 · {{ clock(selectedCaption.start_us) }}</figcaption>
              </figure>
            </div>
            <SubtitleDraft :key="activeResult.task_id+':'+subtitleTrack" :project-id="projectId" :asset-id="assetId"
              :task-id="activeResult.task_id" :stream="subtitleTrack" :cues="currentTrack.cues"
              :cue-index="Math.min(draftCue,currentTrack.cues.length-1)"
              @seek="seek" @assets-changed="emit('assetsChanged')" @edit-video="emit('editVideo',hardScan ? '' : assetId,$event)" />
          </div>
        </div>
        <section v-if="activeResult.ocr && !hardScan" class="ocr-result">
          <h3>画面文字 · {{ activeResult.ocr.language }}</h3>
          <p class="hint">{{ activeResult.ocr.frames.length }} 个采样帧。请到证据审核中核对画面文字。</p>
          <p v-if="!activeResult.ocr.frames.some(frame=>frame.text)">在采样帧中未识别到文字。</p>
          <div v-for="frame in activeResult.ocr.frames.filter(frame=>frame.text)" :key="frame.artifact" class="actions">
            <button @click="seek(frame.time_us)">{{ clock(frame.time_us) }}</button><span>{{ frame.text }}</span>
          </div>
        </section>
      </section>
      <AnalysisReview v-if="currentAsset" :key="assetId" :asset-id="assetId" :results="reviewResults" :playhead="playhead"
        @seek="seek" @adaptation="emit('adaptation',$event)" @assets-changed="emit('assetsChanged')" />
    </template>
  </div>
</template>

<style scoped>
.analysis-workspace,.analysis-options { display:grid; gap:14px; min-width:0 }
.analysis-source { display:flex; flex-wrap:wrap; align-items:end; gap:10px 24px }
.analysis-source label { width:min(100%,420px) }
.analysis-source select { min-width:0; width:100%; text-overflow:ellipsis }
.analysis-source p { margin:0 0 3px; overflow-wrap:anywhere }
.analysis-desk { display:grid; grid-template-columns:minmax(0,1.8fr) minmax(290px,1fr); gap:16px; align-items:start }
.analysis-desk > section { min-width:0 }
.analysis-panel-bar,.subtitle-controls { display:flex; align-items:center; justify-content:space-between; gap:9px; flex-wrap:wrap }
.analysis-panel-bar h2,.analysis-tools > h2 { margin:0 }
.analysis-link,.analysis-tabs button { display:inline-flex; align-items:center; gap:7px }
.source-actions { gap:8px }
.analysis-link { padding:6px 9px; border:1px solid var(--line); border-radius:6px; color:var(--ink-secondary); font-size:12px; text-decoration:none }
.analysis-link:hover { border-color:var(--accent) }
.analysis-monitor { background:#111216; border-radius:7px; display:grid; place-items:center; margin:12px 0; overflow:hidden }
.analysis-monitor video { display:block; border:0; aspect-ratio:16/9; max-height:59vh; width:100%; background:#111216 }
.analysis-monitor audio { display:block; width:100%; margin:10px 0 }
.audio-monitor { padding:0 10px; }
.time-readout { display:flex; justify-content:space-between; gap:10px; color:var(--ink-muted); font:12px Consolas,monospace }
.time-readout output { color:var(--ink); letter-spacing:.04em }
.source-seek { display:block; padding:0; width:100%; margin:10px 0; accent-color:var(--accent) }
.shot-ruler { display:flex; gap:3px; overflow:auto; margin-top:10px }
.shot-marker { flex-basis:0; min-width:28px; padding:4px 8px; border-radius:4px; font-size:11px; text-align:center }
.analysis-tabs,.queue-filter { display:flex; flex-wrap:wrap; gap:7px; margin:13px 0 0; }
.analysis-tabs { border-top:1px solid var(--line-soft); padding-top:12px }
.analysis-tabs button,.queue-filter button { font-size:12px; padding:6px 9px }
.active-caption { background:var(--surface-raised); border-radius:5px; white-space:pre-wrap; overflow-wrap:anywhere; margin-bottom:0; padding:8px 12px }
.analysis-options details,.analysis-options fieldset { margin:0; padding:10px; min-width:0 }
.analysis-options { margin-top:10px; gap:10px }
.analysis-options .editor-grid { grid-template-columns:repeat(auto-fit,minmax(min(100%,140px),1fr)); gap:10px }
.analysis-options .editor-grid :is(input,select) { min-width:0; width:100% }
.analysis-choices { display:grid; grid-template-columns:1fr 1fr; gap:3px 6px }
.analysis-choices label { padding:5px 0; font-size:12px; gap:6px }
.analysis-capabilities { margin:12px 0 0; padding:10px }
.task-header { margin-top:15px }
.analysis-refresh { padding:6px 8px; line-height:0 }
.analysis-queue { max-height:285px; overflow:auto; margin-top:7px }
.analysis-job { display:flex; flex-wrap:wrap; align-items:center; column-gap:8px; row-gap:5px; padding:8px 0; border-bottom:1px solid var(--line-soft) }
.task-stage,.analysis-job .actions { flex-basis:100%; margin:0 }
.select-job { text-align:left; flex:1; min-width:0; padding:6px 8px; overflow-wrap:anywhere }
.analysis-job .error { max-width:100%; padding:6px }
.artifacts { display:grid; grid-template-columns:repeat(auto-fill,minmax(min(100%,180px),1fr)); gap:10px }
.artifacts.filmstrip { display:flex; overflow:auto; padding-bottom:6px }
.artifacts.filmstrip article { flex:0 0 156px }
.artifacts article { border:1px solid var(--line); border-radius:6px; padding:10px; min-width:0; overflow-wrap:anywhere }
.artifacts article p { font-size:12px; margin:6px 0 }
.frame { width:100%; padding:5px }
.frame img { display:block; width:100%; height:84px; object-fit:contain; margin-bottom:3px; background:#111216 }
.subtitle-workspace { display:grid; grid-template-columns:minmax(0,1fr) minmax(275px,.9fr); gap:12px; align-items:start }
.cue-browser { min-width:0 }
.cue-list { display:grid; gap:5px; max-height:360px; overflow:auto; }
.cue-list button { display:flex; flex-wrap:wrap; text-align:left; gap:7px 14px; white-space:pre-wrap; overflow-wrap:anywhere }
.cue-list time { color:var(--ink-muted); font:12px Consolas,monospace; padding-top:3px }
.cue-list button[data-playing=true] time { color:var(--accent) }
.cue-pager { margin-top:9px }
.hard-subtitle-summary { padding:10px 12px; margin:12px 0; background:var(--accent-surface); border:1px solid var(--line-soft); border-radius:8px }
.hard-subtitle-summary p { margin:5px 0 0 }
.cue-list small,.caption-evidence figcaption { color:var(--ink-muted) }
.caption-evidence { margin:10px 0 0; padding:8px; background:#131d26; border:1px solid var(--line-soft); border-radius:8px }
.caption-evidence img { display:block; width:100%; max-height:190px; object-fit:contain; }
.caption-evidence figcaption { margin-top:6px; font-size:12px }
@media (max-width:900px) { .subtitle-workspace { grid-template-columns:1fr } }
.stream-list details { margin:12px 0 }
[aria-pressed="true"] { border-color:var(--accent); background:var(--accent-surface); color:var(--ink) }
@media(max-width:1120px) { .analysis-desk { grid-template-columns:1fr } }
@media(max-width:520px) {
  .analysis-desk > section,.analysis-result { padding:12px }
  .analysis-choices { grid-template-columns:repeat(2,minmax(0,1fr)) }
  .analysis-tabs { gap:5px }
  .analysis-tabs button { padding:5px 7px }
}
</style>
