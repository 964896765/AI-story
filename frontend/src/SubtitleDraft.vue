<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ArrowRight, Download, Save } from 'lucide-vue-next'
import { clock, request, type Cue, type ReviewCue, type SubtitlePreview } from './analysisApi'

interface DraftCue { start_ms: number | null; end_ms: number | null; text: string }
interface Revision { id: string; name: string; version: number; media_info: { cue_count: number } }
interface RevisionDetail { id: string; version: number; cues: Cue[] }
type Edits = Partial<Record<number, DraftCue | null>>

const props = defineProps<{
  projectId: string; assetId: string; taskId: string; stream: number; cues: Cue[]; cueIndex: number
}>()
const emit = defineEmits<{ seek: [us: number]; assetsChanged: []; editVideo: [id: string]; preview: [value: SubtitlePreview] }>()
const edits = ref<Edits>({})
const base = ref<RevisionDetail | null>(null)
const versions = ref<Revision[]>([])
const busy = ref(false), error = ref(''), notice = ref('')
const storageWarning = ref(''), restoreBlocked = ref(false)
const route = `/analysis/projects/${props.projectId}/assets/${props.assetId}/tasks/${props.taskId}/subtitle-tracks/${props.stream}/revisions`
const storageKey = `ai-story:subtitle-draft:v1:${props.projectId}:${props.assetId}:${props.taskId}:${props.stream}`
let lastStored: string | null = null
const baseCues = computed(() => base.value?.cues ?? props.cues)
const cueIndex = computed(() => Math.min(props.cueIndex,baseCues.value.length-1))
const baseCue = computed(() => {
  const cue = baseCues.value[cueIndex.value]
  return { start_ms: Math.floor(cue.start_us / 1000), end_ms: Math.floor(cue.end_us / 1000), text: cue.text }
})
const selected = computed(() => edits.value[cueIndex.value] === undefined ? baseCue.value : edits.value[cueIndex.value])
const changed = computed(() => Object.keys(edits.value).length)
const allRemoved = computed(() => Object.values(edits.value).filter(cue => cue === null).length === baseCues.value.length)
const formatTime = (ms: number | null) => ms === null ? '–' : clock(ms * 1000)

function validCue(cue: DraftCue): cue is DraftCue & {start_ms:number; end_ms:number} {
  return cue.start_ms !== null && cue.end_ms !== null && Number.isInteger(cue.start_ms) &&
    Number.isInteger(cue.end_ms) && cue.start_ms >= 0 && cue.end_ms <= 86_400_000 &&
    cue.end_ms > cue.start_ms && !!cue.text.trim()
}
const previewRows = computed<ReviewCue[]>(() => baseCues.value.map((cue,index) => {
  const edit = edits.value[index]
  if (edit === undefined) return cue
  if (!edit || !validCue(edit)) return { ...cue, hidden:true }
  return { ...cue, start_us:edit.start_ms * 1000, end_us:edit.end_ms * 1000, text:edit.text }
}))
watch([previewRows, base], ([cues, revision]) => {
  emit('preview', {task:props.taskId, stream:props.stream, baseId:revision?.id ?? null, cues})
}, {immediate:true})

function persist() {
  try {
    if (localStorage.getItem(storageKey) !== lastStored) {
      storageWarning.value = '另一个标签页更新了本机草稿。刷新可读取该草稿，或将当前修改保存为字幕版本。'
      return
    }
    const next = changed.value ? JSON.stringify({baseId:base.value?.id ?? null, edits:edits.value}) : null
    if (next && next.length > 2_000_000) throw new Error('draft too large')
    if (next === null) localStorage.removeItem(storageKey)
    else localStorage.setItem(storageKey,next)
    lastStored = next
    storageWarning.value = ''
  } catch {
    storageWarning.value = '浏览器暂时无法保留草稿。离开前请保存字幕素材。'
  }
}

function update(edit: Partial<DraftCue>) {
  const value = { ...baseCue.value, ...selected.value, ...edit }
  if (value.start_ms === baseCue.value.start_ms && value.end_ms === baseCue.value.end_ms &&
      value.text === baseCue.value.text) {
    delete edits.value[cueIndex.value]
  } else {
    edits.value[cueIndex.value] = value
  }
  notice.value = ''
  persist()
}

function updateTime(key: 'start_ms' | 'end_ms', event: Event) {
  const value = (event.target as HTMLInputElement).valueAsNumber
  update({ [key]: Number.isFinite(value) ? value : null })
}

function removeCue() {
  edits.value[cueIndex.value] = null
  notice.value = ''
  persist()
}

function restoreCue() {
  delete edits.value[cueIndex.value]
  notice.value = ''
  persist()
}

function discard() {
  edits.value = {}
  if (restoreBlocked.value) base.value = null
  restoreBlocked.value = false
  error.value = ''
  notice.value = '已放弃本机草稿'
  persist()
}

function fetchBase(id: string) {
  return request<RevisionDetail>(route+'/'+encodeURIComponent(id))
}

async function openBase(id: string | null) {
  error.value = ''
  notice.value = ''
  busy.value = true
  try {
    base.value = id ? await fetchBase(id) : null
    notice.value = base.value ? `已载入字幕 v${base.value.version}` : '已载入原字幕'
  } catch (failure) {
    error.value = String(failure)
  } finally {
    busy.value = false
  }
}

async function restoreLocal() {
  try { lastStored = localStorage.getItem(storageKey) }
  catch {
    storageWarning.value = '浏览器暂时无法读取本机草稿。'
    return
  }
  if (!lastStored) return
  try {
    const saved = JSON.parse(lastStored)
    if (!saved || !saved.edits || typeof saved.edits !== 'object' || Array.isArray(saved.edits) ||
        !(saved.baseId === null || typeof saved.baseId === 'string')) throw new Error('草稿格式无效')
    const revision = saved.baseId ? await fetchBase(saved.baseId) : null
    const rows = revision?.cues ?? props.cues
    const recovered: Edits = {}
    for (const [index,cue] of Object.entries<DraftCue | null>(saved.edits)) {
      if (!/^(0|[1-9]\d*)$/.test(index) || Number(index) >= rows.length ||
          (cue !== null && (!cue || typeof cue.text !== 'string' ||
            !(cue.start_ms === null || Number.isFinite(cue.start_ms)) ||
            !(cue.end_ms === null || Number.isFinite(cue.end_ms))))) throw new Error('草稿与底稿不匹配')
      recovered[Number(index)] = cue
    }
    base.value = revision
    edits.value = recovered
    notice.value = '已恢复本机草稿'
  } catch (failure) {
    restoreBlocked.value = true
    error.value = '无法恢复本机草稿。可刷新重试，或放弃这份草稿。'+String(failure)
  }
}

async function save() {
  error.value = ''
  notice.value = ''
  for (const [index, cue] of Object.entries(edits.value)) {
    if (cue && !validCue(cue)) {
      error.value = `请检查第 ${Number(index)+1} 条的字幕文本和时间（非负整数毫秒，结束晚于开始）。`
      return
    }
  }
  busy.value = true
  try {
    const saved = await request<Revision>(route, { edits:edits.value, base_revision_id:base.value?.id ?? null })
    versions.value = [saved, ...versions.value.filter(item => item.id !== saved.id)]
      .sort((a, b) => b.version - a.version).slice(0, 20)
    notice.value = `字幕素材 v${saved.version} 已保存 · ${saved.media_info.cue_count} 条`
    emit('assetsChanged')
    try {
      base.value = await fetchBase(saved.id)
      edits.value = {}
      persist()
    } catch (failure) {
      error.value = '字幕已保存，重新载入版本时出错。'+String(failure)
    }
  } catch (failure) {
    error.value = String(failure)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  busy.value = true
  try {
    await restoreLocal()
    versions.value = await request<Revision[]>(route)
  } catch (failure) { error.value ||= String(failure) }
  finally { busy.value = false }
})
</script>

<template>
  <form class="subtitle-draft" @submit.prevent="save">
    <div class="draft-heading">
      <h3>校对第 {{cueIndex+1}} 条</h3>
      <span class="hint">{{changed}} 条有修改</span>
    </div>
    <p class="draft-base">当前底稿 · {{base ? '字幕 v'+base.version : '原字幕'}}</p>
    <fieldset :disabled="busy || restoreBlocked">
      <template v-if="selected">
        <label>字幕文本<textarea :value="selected.text" maxlength="4000" rows="3"
          @input="update({ text: ($event.target as HTMLTextAreaElement).value })"></textarea></label>
        <div class="draft-times">
          <label>开始（毫秒）<input :value="selected.start_ms" type="number" min="0" max="86399999" step="1" required
            @input="updateTime('start_ms', $event)"><small>{{formatTime(selected.start_ms)}}</small></label>
          <label>结束（毫秒）<input :value="selected.end_ms" type="number" min="1" max="86400000" step="1" required
            @input="updateTime('end_ms', $event)"><small>{{formatTime(selected.end_ms)}}</small></label>
        </div>
        <div class="actions">
          <button type="button" :disabled="selected.start_ms===null || selected.start_ms<0"
            @click="emit('seek', (selected.start_ms ?? 0)*1000)">定位修订开始</button>
          <button type="button" @click="removeCue">移除本条</button>
        </div>
      </template>
      <p v-else class="hint">本条将在校对版中移除。</p>
      <button v-if="edits[cueIndex] !== undefined" class="restore-cue" type="button" @click="restoreCue">恢复本条底稿</button>
    </fieldset>
    <div class="actions">
      <button class="primary save-subtitle" :disabled="busy || allRemoved || restoreBlocked"><Save :size="15" aria-hidden="true" />保存字幕素材</button>
      <button v-if="changed || restoreBlocked" type="button" :disabled="busy" @click="discard">放弃草稿</button>
      <button v-if="base" type="button" :disabled="busy || !!changed || restoreBlocked" @click="openBase(null)">从原字幕开始</button>
    </div>
    <p v-if="allRemoved" class="hint">至少保留一条字幕。</p>
    <p v-if="error" class="error" role="alert">{{error}}</p>
    <p v-if="notice" role="status">{{notice}}</p>
    <p v-if="storageWarning" class="hint" role="status">{{storageWarning}}</p>

    <section v-if="versions.length" class="subtitle-revisions">
      <h4>已保存字幕</h4>
      <p v-if="changed" class="hint">保存或放弃草稿后可切换底稿。</p>
      <article v-for="version in versions" :key="version.id" :data-version="version.version">
        <span>v{{version.version}} · {{version.media_info.cue_count}} 条<span v-if="base?.id===version.id"> · 当前底稿</span></span>
        <div class="actions">
          <a :href="'/api/assets/'+version.id+'/media'" :download="version.name">
            <Download :size="14" aria-hidden="true" />下载 SRT</a>
          <button type="button" @click="emit('editVideo', version.id)">带入剪辑 <ArrowRight :size="14" aria-hidden="true" /></button>
          <button type="button" :disabled="busy || !!changed || restoreBlocked || base?.id===version.id"
            @click="openBase(version.id)">继续编辑</button>
        </div>
      </article>
    </section>
  </form>
</template>

<style scoped>
.subtitle-draft { min-width:0; margin:0; border:1px solid var(--line-soft); padding:12px; border-radius:8px; background:#131d26 }
.draft-heading,.subtitle-revisions article { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:6px }
.draft-heading h3,.subtitle-revisions h4 { margin:0 }
.subtitle-draft p { margin:7px 0 }
.draft-base { color:var(--ink-secondary); font-size:12px }
.subtitle-draft fieldset { min-width:0; padding:0; border:0; margin:12px 0 }
.subtitle-draft textarea { min-height:78px; width:100%; resize:vertical }
.draft-times { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin:8px 0 }
.draft-times small { color:var(--ink-muted); font:11px Consolas,monospace }
.restore-cue { margin-top:7px }
.save-subtitle,.subtitle-revisions button,.subtitle-revisions a { display:inline-flex; gap:6px; align-items:center }
.subtitle-revisions { margin-top:12px; padding:0; background:none; border:0; max-height:250px; overflow:auto }
.subtitle-revisions article { padding:6px 0; border-bottom:1px solid var(--line-soft); font-size:12px }
</style>
