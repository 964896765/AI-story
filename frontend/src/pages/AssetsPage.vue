<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { NButton } from 'naive-ui'
import { AudioLines, Clapperboard, FileText, FolderOpen, Image, Search, Upload } from 'lucide-vue-next'
import { useWorkspace } from '../router/workspace'
import { api, post } from '../services/api'
import type { Asset } from '../types/workbench'

const { workbench, query, go } = useWorkspace()
const title = ref(''), description = ref(''), authorization = ref(''), preview = ref('')
const busy = ref(false), error = ref(''), fileQuery = ref(''), activeType = ref('all'), imported = ref('')
const uploadOpen = ref(query('import') === '1'), previewText = ref(''), previewError = ref('')
const media = /\.(mp4|mov|mkv|webm|avi|wav|mp3)$/i
const image = /\.(png|jpe?g|webp)$/i
const audio = /\.(wav|mp3)$/i
const textFile = /\.(srt|txt)$/i
const format = (asset: Asset) => asset.name.split('.').pop()?.toUpperCase() || '文件'
const size = (bytes: number) => bytes < 1024 ? bytes + ' B' : bytes < 1024**2 ? (bytes/1024).toFixed(1)+' KiB' : (bytes/1024**2).toFixed(2)+' MiB'
const kind = (asset: Asset) => audio.test(asset.name) ? 'audio' : media.test(asset.name) ? 'video' :
  image.test(asset.name) ? 'image' : 'text'
const categories = [
  { id:'all', label:'全部素材', icon:FolderOpen }, { id:'video', label:'视频', icon:Clapperboard },
  { id:'audio', label:'音频', icon:AudioLines }, { id:'image', label:'图片', icon:Image },
  { id:'text', label:'文本与字幕', icon:FileText },
]
const totals = computed(() => {
  const result: Record<string,number> = { all:workbench.assets.length }
  for (const asset of workbench.assets) result[kind(asset)] = (result[kind(asset)] || 0)+1
  return result
})
const visible = computed(() => {
  const term = fileQuery.value.trim().toLocaleLowerCase()
  return workbench.assets.filter(asset => (activeType.value === 'all' || kind(asset) === activeType.value) &&
    (asset.name+' '+asset.authorization).toLocaleLowerCase().includes(term))
})
const current = computed(() => visible.value.find(asset => asset.id === preview.value) || visible.value[0])
const previewUrl = computed(() => current.value ? `/api/assets/${current.value.id}/media` : '')
const streamSummary = computed(() => {
  const streams = current.value?.media_info.streams
  return Array.isArray(streams) ? streams.map(stream => ({
    index:stream.index, codec:stream.codec_name, type:stream.codec_type, size:stream.width && stream.height ? `${stream.width} × ${stream.height}` : '',
  })) : []
})
let refreshTimer: ReturnType<typeof setInterval> | undefined

async function action(operation: () => Promise<void>) {
  busy.value = true
  error.value = ''
  try { await operation() } catch (failure) { error.value = String(failure) } finally { busy.value = false }
}

function create() {
  void action(async () => {
    const project = await workbench.createProject(title.value, description.value)
    await go('assets', { project: project.id })
  })
}

async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  const project = workbench.projectId
  const rights = authorization.value.trim()
  await action(async () => {
    if (!rights) throw new Error('请先填写授权来源')
    let count = 0
    try {
      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        form.append('authorization', rights)
        const result = await api<Asset>(`/projects/${project}/assets`, { method: 'POST', body: form })
        preview.value = result.id
        count++
      }
    } finally {
      if (count) {
        imported.value = `已导入 ${count} 项素材`
        activeType.value = 'all'
        fileQuery.value = ''
      }
      await workbench.loadAssets()
    }
  })
  input.value = ''
}

function probe(asset: Asset) {
  void action(async () => {
    await post(`/projects/${workbench.projectId}/tasks`, { asset_id: asset.id, idempotency_key: `probe:${asset.id}:v1` })
    workbench.refresh()
  })
}

watch(previewUrl, async (url, _, cleanup) => {
  previewText.value = ''
  previewError.value = ''
  if (!current.value || !textFile.test(current.value.name)) return
  const controller = new AbortController()
  cleanup(() => controller.abort())
  try {
    const response = await fetch(url,{signal:controller.signal})
    if (!response.ok) throw new Error('文本预览暂不可用')
    const value = await response.text()
    if (!controller.signal.aborted) previewText.value = value.slice(0,12000)
  } catch (failure) {
    if (!controller.signal.aborted) previewError.value = String(failure)
  }
}, {immediate:true})
onMounted(() => {
  refreshTimer = setInterval(() => {
    if (!busy.value && document.visibilityState !== 'hidden') void workbench.loadAssets()
  }, 15_000)
})
onUnmounted(() => clearInterval(refreshTimer))
</script>

<template>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="imported" class="asset-notice" role="status">{{ imported }}</p>
  <details :open="!workbench.projects.length || query('create') === '1'" class="asset-create">
    <summary>新建项目</summary>
    <form class="create" @submit.prevent="create">
      <label>项目名称<input v-model="title" required maxlength="200" placeholder="输入项目名称"></label>
      <label>项目说明<textarea v-model="description" maxlength="20000" placeholder="故事方向、授权范围或制作要求"></textarea></label>
      <NButton type="primary" attr-type="submit" :loading="busy" :disabled="!title.trim()">创建项目</NButton>
    </form>
  </details>
  <div v-if="workbench.projectId" class="asset-workspace">
    <section class="asset-library">
      <header class="asset-bar">
        <h2>项目素材 <span>{{ workbench.assets.length }} 项</span></h2>
        <NButton type="primary" :aria-expanded="uploadOpen" @click="uploadOpen = !uploadOpen">
          <template #icon><Upload :size="16" /></template>{{ uploadOpen ? '收起导入' : '导入素材' }}
        </NButton>
      </header>
      <div v-if="uploadOpen || !workbench.assets.length" class="import-panel">
        <label>授权来源<textarea v-model="authorization" maxlength="10000" placeholder="自有素材声明或授权方、协议编号及使用范围"></textarea></label>
        <label class="upload">选择本地文件<input type="file" multiple accept=".mp4,.mov,.mkv,.webm,.avi,.wav,.mp3,.srt,.txt,.png,.jpg,.jpeg,.webp"
          :disabled="busy || !authorization.trim()" @change="upload"></label>
        <p class="hint">媒体每文件上限 2 GiB，SRT/TXT 2 MiB，参考图片 20 MiB。</p>
      </div>
      <div class="asset-filters" aria-label="筛选素材类型">
        <button v-for="category in categories" :key="category.id" type="button" :aria-pressed="activeType===category.id" @click="activeType=category.id">
          <component :is="category.icon" :size="15" aria-hidden="true" />{{category.label}}<small>{{totals[category.id] || 0}}</small>
        </button>
      </div>
      <label class="asset-search"><Search :size="16" aria-hidden="true" /><input v-model="fileQuery" type="search"
        aria-label="搜索素材" placeholder="搜索名称或授权来源"></label>
      <p v-if="!visible.length" class="empty">{{ workbench.assets.length ? '没有符合筛选条件的素材。' : '导入文件后将在这里显示。' }}</p>
      <article v-for="asset in visible" :key="asset.id" class="asset asset-row" :class="{ selected:current?.id===asset.id }">
        <button type="button" class="asset-select" :aria-pressed="current?.id===asset.id" @click="preview = asset.id">
          <span class="asset-glyph"><component :is="categories.find(category => category.id===kind(asset))?.icon" :size="20" aria-hidden="true" /></span>
          <span><strong>{{ asset.name }}</strong>
            <small>{{ format(asset) }} · {{ size(asset.size_bytes) }}<template v-if="media.test(asset.name)"> · {{ Object.keys(asset.media_info).length ? '已解析' : '待解析' }}</template></small>
          </span>
        </button>
        <div v-if="media.test(asset.name)" class="actions asset-row-tools">
          <button :disabled="busy" @click="probe(asset)">读取媒体信息</button>
          <button :disabled="busy" @click="go('analysis', { asset: asset.id })">智能解析</button>
        </div>
      </article>
    </section>
    <section class="asset-inspector">
      <h2>素材检查器</h2>
      <template v-if="current">
        <p class="asset-current">{{ current.name }}</p>
        <img v-if="image.test(current.name)" class="reference-preview" :src="previewUrl" :alt="current.name">
        <audio v-else-if="audio.test(current.name)" :key="current.id" controls preload="metadata" :src="previewUrl"></audio>
        <video v-else-if="media.test(current.name)" :key="current.id" controls preload="metadata" :src="previewUrl" @error="previewError='可在智能解析生成 MP4 代理后预览。'"></video>
        <pre v-else class="log-tail">{{ previewText || previewError || '正在读取文本…' }}</pre>
        <p v-if="previewError && media.test(current.name)" class="hint">{{ previewError }}</p>
        <dl><div><dt>类型</dt><dd>{{ format(current) }}</dd></div><div><dt>文件大小</dt><dd>{{ size(current.size_bytes) }}</dd></div></dl>
        <h3>授权来源</h3><p class="rights-note">{{ current.authorization }}</p>
        <h3 v-if="streamSummary.length">媒体流</h3>
        <ul v-if="streamSummary.length" class="stream-summary"><li v-for="stream in streamSummary" :key="stream.index">
          #{{stream.index}} · {{stream.type}} · {{stream.codec}} {{stream.size}}
        </li></ul>
        <details><summary>文件校验</summary><p class="mono">{{ current.sha256 }}</p></details>
      </template>
      <p v-else class="empty">选择素材以查看内容和授权。</p>
    </section>
  </div>
  <p v-else class="empty"><Upload :size="18" aria-hidden="true" /> 创建或选择一个项目，开始管理授权素材。</p>
</template>

<style scoped>
.asset-workspace { display:grid; grid-template-columns:minmax(0,1.7fr) minmax(270px,1fr); gap:18px; align-items:start }
.asset-library,.asset-inspector { min-width:0 }
.asset-bar { display:flex; align-items:center; justify-content:space-between; gap:10px; margin-bottom:13px }
.asset-bar h2 { margin:0 }
.asset-filters { display:flex; flex-wrap:wrap; gap:5px; margin-bottom:10px }
.asset-filters button { display:flex; align-items:center; gap:6px; padding:6px 8px; font-size:12px }
.asset-filters small { color:var(--ink-muted) }
.asset-filters button[aria-pressed=true] { background:var(--accent-surface); color:var(--accent); border-color:var(--accent) }
.asset-search { display:flex; align-items:center; gap:8px; margin-bottom:8px; padding:0 10px; background:var(--surface-raised); border:1px solid var(--line); border-radius:7px }
.asset-search input { flex:1; border:0; padding-inline:0; background:transparent }
.asset-row { margin:0; padding:8px 5px; align-items:center }
.asset-row.selected { background:var(--accent-surface); border-radius:7px }
.asset-select { display:flex; align-items:center; text-align:left; min-width:0; gap:9px; flex:1; border:0!important; background:transparent!important; padding:4px!important }
.asset-select small { display:block; margin-top:4px; color:var(--ink-muted) }
.asset-select strong { overflow-wrap:anywhere }
.asset-glyph { display:grid; place-items:center; flex:0 0 36px; height:36px; background:var(--surface-raised); color:var(--accent); border-radius:7px }
.asset-row-tools { padding-inline:4px }
.asset-inspector { position:sticky; top:calc(var(--topbar-height) + 12px) }
.asset-inspector video,.asset-inspector img,.asset-inspector audio { display:block; width:100%; margin-bottom:12px }
.asset-current { overflow-wrap:anywhere; color:var(--ink-secondary) }
.asset-inspector dl { display:grid; grid-template-columns:1fr 1fr; column-gap:10px; margin:12px 0; padding:10px 0; border-block:1px solid var(--line-soft) }
.asset-inspector dt { color:var(--ink-muted); font-size:12px }
.asset-inspector dd { margin:3px 0 0 }
.asset-inspector h3,.rights-note { margin:0 0 8px }
.asset-inspector .mono { margin:7px 0 0; overflow-wrap:anywhere }
.asset-inspector details { margin-bottom:0 }
.asset-notice { color:var(--positive) }
.import-panel { background:var(--surface-raised); border:1px dashed var(--accent); border-radius:8px; padding:12px; margin-bottom:12px }
.import-panel p { margin:8px 0 0 }
.stream-summary { padding-left:20px }
@media(max-width:1000px) { .asset-workspace { grid-template-columns:1fr } .asset-inspector { position:static } }
@media(max-width:560px) { .asset-row { align-items:stretch } .asset-row-tools { padding-left:49px } }
</style>
