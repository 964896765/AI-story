<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import AnalysisReview from './AnalysisReview.vue'
import AnalysisWaveform from './AnalysisWaveform.vue'
import {
  artifactUrl, clock, operationLabels, request, statusLabels,
  type Job, type Operation, type Result, type Version,
} from './analysisApi'

const props = defineProps<{ projectId: string; assets: {id:string;name:string}[]; initialAssetId: string }>()
const emit = defineEmits<{ adaptation: [version: Version]; assetsChanged: [] }>()
const supported = computed(() => props.assets.filter(asset => /\.(mp4|mov|mkv|webm|avi|wav|mp3)$/i.test(asset.name)))
const assetId = ref(props.initialAssetId)
const currentAsset = computed(() => supported.value.find(asset => asset.id === assetId.value))
const jobs = ref<Job[]>([]), results = ref<Result[]>([]), activeResult = ref<Result | null>(null)
const selectedJob = ref(''), viewSource = ref(''), playing = ref<HTMLMediaElement | null>(null), playhead = ref(0)
const checked = ref<Operation[]>(['inspect'])
const operations = Object.keys(operationLabels) as Operation[]
const error = ref(''), notice = ref(''), busy = ref(false), loading = ref(false)
const logFiles = ref<{name:string;tail:string}[] | null>(null)
const capabilities = ref<{id:string;label:string;available:boolean}[]>([])
const options = reactive({
  container:'mkv', max_edge:720, crf:20, fps:null as number|null, sample_rate:48000,
  channels:null as number|null, frame_mode:'interval', frame_interval:5, frame_time:0,
  scene_threshold:0.30, minimum_shot_seconds:0.30, silence_db:-40, silence_seconds:0.4,
})
const audioOnly = computed(() => /\.(wav|mp3)$/i.test(currentAsset.value?.name || ''))
const queuePath = computed(() => `/analysis/projects/${props.projectId}/assets/${assetId.value}/tasks`)
const sourceUrl = computed(() => viewSource.value || `/api/assets/${assetId.value}/media`)
const keys = new Map<string,string>()
const cache = new Map<string,Result>()
let timer: ReturnType<typeof setInterval> | undefined

async function loadResult(taskId: string) {
  const cached = cache.get(taskId)
  if (cached) return cached
  const result = await request<Result>(`/analysis/tasks/${taskId}/result`)
  if (cache.size >= 24) cache.delete(cache.keys().next().value!)
  cache.set(taskId,result)
  return result
}
async function refresh() {
  const id = assetId.value
  if (!id || loading.value) return
  loading.value = true
  try {
    const list = await request<Job[]>(queuePath.value)
    if (id !== assetId.value) return
    jobs.value = list
    const latest = [...new Set(list.filter(job => job.status === 'succeeded').map(job => job.parameters.operation))]
      .map(op => list.find(job => job.parameters.operation === op && job.status === 'succeeded')!.id)
    const values = await Promise.all(latest.map(loadResult))
    if (id !== assetId.value) return
    results.value = values
    const selected = list.find(job => job.id === selectedJob.value)
    if (selected?.status === 'succeeded' && activeResult.value?.task_id !== selected.id) {
      const result = await loadResult(selected.id)
      if (id === assetId.value && selectedJob.value === selected.id) activeResult.value = result
    }
  } finally { loading.value = false }
}
async function run(action: () => Promise<void>) {
  busy.value = true
  error.value = ''
  notice.value = ''
  try { await action() } catch (failure) { error.value = String(failure) } finally { busy.value = false }
}
function payload(operation: Operation) {
  const common = {operation}
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
  playhead.value = time
  if (playing.value && Number.isFinite(playing.value.duration)) playing.value.currentTime = time/1_000_000
}
watch(assetId, () => {
  jobs.value = []
  results.value = []
  activeResult.value = null
  selectedJob.value = ''
  viewSource.value = ''
  logFiles.value = null
  playhead.value = 0
  error.value = ''
  if (assetId.value) void run(refresh)
})
watch(supported, assets => {
  if (!assets.some(asset => asset.id === assetId.value)) assetId.value = assets[0]?.id || ''
}, {immediate:true})
onMounted(() => {
  void run(async () => {
    const status = await request<{capabilities:typeof capabilities.value}>('/analysis/capabilities')
    capabilities.value = status.capabilities
    await refresh()
  })
  timer = setInterval(() => { if (!busy.value) void refresh().catch(failure => { error.value=String(failure) }) }, 3000)
})
onUnmounted(() => clearInterval(timer))
</script>

<template>
  <p v-if="!projectId" class="empty">选择项目以开始媒体解析。</p>
  <div v-else class="analysis-workspace">
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="!supported.length" class="empty">先在素材资产中心导入音视频。</p>
    <template v-else>
      <div class="workspace">
        <section>
          <h2>本地解析任务</h2>
          <label>解析素材<select v-model="assetId" :disabled="busy">
            <option v-for="asset in supported" :key="asset.id" :value="asset.id">{{ asset.name }}</option>
          </select></label>
          <form class="analysis-options" @submit.prevent="submit">
            <fieldset>
              <legend>选择步骤</legend>
              <span class="analysis-choices">
                <label v-for="operation in operations" :key="operation" class="check">
                  <input v-model="checked" type="checkbox" :value="operation" :disabled="disabled(operation)">{{ operationLabels[operation] }}
                </label>
              </span>
            </fieldset>
            <details v-if="checked.some(op => !['inspect','split','subtitles'].includes(op))">
              <summary>解析参数</summary>
              <div class="editor-grid">
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
              </div>
            </details>
            <button class="primary" :disabled="busy || !currentAsset || !checked.some(op => !disabled(op))">提交本地解析</button>
          </form>
        </section>
        <section>
          <h2>{{ viewSource ? '代理预览' : '原素材预览' }}</h2>
          <audio v-if="audioOnly" :key="sourceUrl" ref="playing" :src="sourceUrl" controls preload="metadata" @timeupdate="playing && (playhead=Math.round(playing.currentTime*1e6))"></audio>
          <video v-else :key="sourceUrl" ref="playing" :src="sourceUrl" controls preload="metadata" @timeupdate="playing && (playhead=Math.round(playing.currentTime*1e6))"></video>
          <p>{{ clock(playhead) }}</p>
          <button v-if="viewSource" @click="viewSource=''">返回原素材</button>
          <AnalysisWaveform v-if="activeResult?.operation === 'waveform'" :result="activeResult" :playhead="playhead" @seek="seek" />
          <p v-if="capabilities.length" class="hint">模型待接入：{{ capabilities.filter(item => !item.available).map(item => item.label).join('、') }}。</p>
        </section>
      </div>
      <section>
        <div class="actions"><h2>解析记录</h2><button :disabled="busy || loading" @click="run(refresh)">刷新解析记录</button></div>
        <p v-if="!jobs.length" class="hint">这份素材暂无解析记录。</p>
        <div v-for="job in jobs" :key="job.id" class="analysis-job">
          <button :aria-pressed="selectedJob===job.id" :disabled="busy" @click="openJob(job)">{{ operationLabels[job.parameters.operation] }}</button>
          <span>{{ statusLabels[job.status] || job.status }} · {{ statusLabels[job.stage] || job.stage }}</span>
          <span v-if="job.error" class="error">{{ job.error }}</span>
          <button v-if="['queued','running'].includes(job.status)" :disabled="busy || job.cancel_requested" @click="control(job,'cancel')">取消</button>
          <button v-if="['failed','cancelled'].includes(job.status)" :disabled="busy" @click="control(job,'retry')">重试</button>
          <button v-if="job.attempt && selectedJob===job.id" :disabled="busy" @click="showLogs(job)">执行日志</button>
        </div>
        <div v-if="logFiles" class="log-tail"><p v-if="!logFiles.length">没有可读取的日志文件。</p><pre v-for="file in logFiles" :key="file.name">{{ file.name }}{{ '\n' }}{{ file.tail }}</pre></div>
      </section>
      <section v-if="activeResult" class="analysis-result">
        <h2>{{ operationLabels[activeResult.operation] }}</h2>
        <p class="hint">{{ activeResult.algorithm }}<span v-if="activeResult.reused_from_task_id"> · 已核对哈希并复用历史结果</span></p>
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
        <div v-if="activeResult.artifacts.length" class="artifacts">
          <article v-for="file in activeResult.artifacts" :key="file.id">
            <button v-if="file.media_type === 'image/jpeg'" class="frame" @click="seek(file.time_us || 0)">
              <img :src="artifactUrl(activeResult.task_id,file.id)" loading="lazy" :alt="clock(file.time_us || 0)+' 处的画面'">
              {{ clock(file.time_us || 0) }}
            </button>
            <p>{{ file.name }} · {{ (file.size_bytes / 1024).toFixed(1) }} KiB</p>
            <div class="actions"><a :href="artifactUrl(activeResult.task_id,file.id,true)">下载</a>
              <button v-if="activeResult.operation==='transcode'" @click="viewSource=artifactUrl(activeResult.task_id,file.id)">预览代理</button>
            </div>
          </article>
        </div>
        <div v-for="track in activeResult.subtitle_tracks" :key="track.stream_index">
          <h3>字幕流 {{ track.stream_index }} · {{ track.language || '语言未标注' }}</h3>
          <p class="hint">{{ track.status }} · {{ track.cues.length }} 条</p>
          <div class="cue-list"><div v-for="(cue,index) in track.cues.slice(0,100)" :key="index" class="actions">
            <button @click="seek(cue.start_us)">{{ clock(cue.start_us) }}</button><span>{{ cue.text }}</span>
          </div></div>
        </div>
      </section>
      <AnalysisReview v-if="currentAsset" :key="assetId" :asset-id="assetId" :results="results" :playhead="playhead"
        @seek="seek" @adaptation="emit('adaptation',$event)" @assets-changed="emit('assetsChanged')" />
    </template>
  </div>
</template>

<style scoped>
.analysis-workspace,.analysis-options { display:grid; gap:14px }
.analysis-options details,.analysis-options fieldset { margin:0 }
.analysis-options { margin-top:14px }
.analysis-choices,.analysis-job { display:flex; flex-wrap:wrap; align-items:center; gap:10px }
.analysis-job { padding:10px 0; border-bottom:1px solid #303b4a }
.artifacts { display:grid; grid-template-columns:repeat(auto-fill,minmax(185px,1fr)); gap:12px }
.artifacts article { border:1px solid #394655; border-radius:6px; padding:12px; min-width:0 }
.frame { width:100%; padding:4px }
.frame img { display:block; width:100%; height:auto; border-radius:4px; margin-bottom:4px }
.cue-list { max-height:260px; overflow:auto }
.cue-list .actions { margin-bottom:7px }
.stream-list details { margin:12px 0 }
[aria-pressed="true"] { border-color:#8ab7fc }
</style>
