<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ArrowRight, Download, Save } from 'lucide-vue-next'
import { clock, request, type Cue } from './analysisApi'

interface DraftCue { start_ms: number | null; end_ms: number | null; text: string }
interface Revision { id: string; name: string; version: number; media_info: { cue_count: number } }

const props = defineProps<{
  projectId: string; assetId: string; taskId: string; stream: number; cues: Cue[]; cueIndex: number
}>()
const emit = defineEmits<{ seek: [us: number]; assetsChanged: []; editVideo: [id: string] }>()
const edits = reactive<Partial<Record<number, DraftCue | null>>>({})
const versions = ref<Revision[]>([])
const busy = ref(false), error = ref(''), notice = ref('')
const route = `/analysis/projects/${props.projectId}/assets/${props.assetId}/tasks/${props.taskId}/subtitle-tracks/${props.stream}/revisions`
const original = computed(() => {
  const cue = props.cues[props.cueIndex]
  return { start_ms: cue.start_us / 1000, end_ms: cue.end_us / 1000, text: cue.text }
})
const selected = computed(() => edits[props.cueIndex] === undefined ? original.value : edits[props.cueIndex])
const changed = computed(() => Object.keys(edits).length)
const allRemoved = computed(() => Object.values(edits).filter(cue => cue === null).length === props.cues.length)
const formatTime = (ms: number | null) => ms === null ? '–' : clock(ms * 1000)

function update(edit: Partial<DraftCue>) {
  const value = { ...original.value, ...selected.value, ...edit }
  if (value.start_ms === original.value.start_ms && value.end_ms === original.value.end_ms &&
      value.text === original.value.text) {
    delete edits[props.cueIndex]
  } else {
    edits[props.cueIndex] = value
  }
  notice.value = ''
}

function updateTime(key: 'start_ms' | 'end_ms', event: Event) {
  const value = (event.target as HTMLInputElement).valueAsNumber
  update({ [key]: Number.isFinite(value) ? value : null })
}

function removeCue() {
  edits[props.cueIndex] = null
  notice.value = ''
}

function restoreCue() {
  delete edits[props.cueIndex]
  notice.value = ''
}

async function loadVersions() {
  versions.value = await request<Revision[]>(route)
}

async function save() {
  error.value = ''
  notice.value = ''
  for (const [index, cue] of Object.entries(edits)) {
    if (cue && (cue.start_ms === null || cue.end_ms === null || !Number.isInteger(cue.start_ms) ||
        !Number.isInteger(cue.end_ms) || cue.start_ms < 0 || cue.end_ms > 86_400_000 ||
        cue.end_ms <= cue.start_ms || !cue.text.trim())) {
      error.value = `请检查第 ${Number(index)+1} 条的字幕文本和时间（非负整数毫秒，结束晚于开始）。`
      return
    }
  }
  busy.value = true
  try {
    const saved = await request<Revision>(route, { edits })
    versions.value = [saved, ...versions.value.filter(item => item.id !== saved.id)]
      .sort((a, b) => b.version - a.version).slice(0, 20)
    notice.value = `字幕素材 v${saved.version} 已保存 · ${saved.media_info.cue_count} 条`
    emit('assetsChanged')
  } catch (failure) {
    error.value = String(failure)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  busy.value = true
  try { await loadVersions() } catch (failure) { error.value = String(failure) }
  finally { busy.value = false }
})
</script>

<template>
  <form class="subtitle-draft" @submit.prevent="save">
    <div class="draft-heading">
      <h3>校对第 {{cueIndex+1}} 条</h3>
      <span class="hint">{{changed}} 条有修改</span>
    </div>
    <p class="hint">选择左侧字幕以定位并校对。保存到素材库后可用于剪辑和时间轴。</p>
    <fieldset :disabled="busy">
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
      <button v-if="edits[cueIndex] !== undefined" class="restore-cue" type="button" @click="restoreCue">恢复原字幕</button>
    </fieldset>
    <button class="primary save-subtitle" :disabled="busy || allRemoved"><Save :size="15" aria-hidden="true" />保存字幕素材</button>
    <p v-if="allRemoved" class="hint">至少保留一条字幕。</p>
    <p v-if="error" class="error" role="alert">{{error}}</p>
    <p v-if="notice" role="status">{{notice}}</p>

    <section v-if="versions.length" class="subtitle-revisions">
      <h4>已保存字幕</h4>
      <article v-for="version in versions" :key="version.id">
        <span>v{{version.version}} · {{version.media_info.cue_count}} 条</span>
        <div class="actions">
          <a :href="'/api/assets/'+version.id+'/media'" :download="version.name">
            <Download :size="14" aria-hidden="true" />下载 SRT</a>
          <button type="button" @click="emit('editVideo', version.id)">带入剪辑 <ArrowRight :size="14" aria-hidden="true" /></button>
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
.subtitle-draft fieldset { min-width:0; padding:0; border:0; margin:12px 0 }
.subtitle-draft textarea { min-height:78px; width:100%; resize:vertical }
.draft-times { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:8px; margin:8px 0 }
.draft-times small { color:var(--ink-muted); font:11px Consolas,monospace }
.restore-cue { margin-top:7px }
.save-subtitle,.subtitle-revisions button,.subtitle-revisions a { display:inline-flex; gap:6px; align-items:center }
.subtitle-revisions { margin-top:12px; padding:0; background:none; border:0; max-height:250px; overflow:auto }
.subtitle-revisions article { padding:6px 0; border-bottom:1px solid var(--line-soft); font-size:12px }
</style>
