<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { artifactUrl, clock, operationLabels, request, type Interval, type Result, type Shot, type Version } from './analysisApi'

type EvidenceKind = 'transcript' | 'screen_text' | 'speaker' | 'observation'
type Evidence = Interval & { kind: EvidenceKind; text: string; shots?: number[] }
type Candidate = { kind:'character'|'scene'; title:string; description:string; task_id:string; artifact:number; fixed_version_id?:string|null }
interface Snapshot {
  id:string; number:number
  payload: null | { result_task_ids:string[]; shots:Shot[]; cuts_us:number[]|null; candidates:Candidate[];
    evidence:Evidence[]; subtitle_cues: unknown[]; note:string }
}
const props = defineProps<{ assetId:string; results:Result[]; playhead:number }>()
const emit = defineEmits<{ seek:[time:number]; adaptation:[version:Version]; assetsChanged:[] }>()
const snapshots = ref<Snapshot[]>([]), loaded = ref<Snapshot|null>(null)
const chosen = ref<string[]|null>(null), cuts = ref(''), editCuts = ref(false), note = ref('')
const evidence = ref<Evidence[]>([]), candidates = ref<Candidate[]>([])
const scriptTitle = ref(''), scriptBody = ref(''), approval = ref('')
const error = ref(''), notice = ref(''), busy = ref(false)
const keys = new Map<string,string>()
const useResultIds = computed(() => chosen.value ?? props.results.map(result => result.task_id))
const scene = computed(() => props.results.find(result => result.operation === 'scenes' && useResultIds.value.includes(result.task_id)))
const frames = computed(() => props.results.filter(result => useResultIds.value.includes(result.task_id)).flatMap(result =>
  result.artifacts.filter(a => ['frame','shot_frame'].includes(a.role)).map(a => ({ ...a, task:result.task_id }))))
const revised = computed(() => loaded.value?.payload)
const kinds: Record<EvidenceKind,string> = { transcript:'人工转写', screen_text:'人工标注画面文字',
  speaker:'说话段标注', observation:'画面观察' }
const base = `/analysis/assets/${props.assetId}/revisions`

async function run(action: () => Promise<void>) {
  busy.value = true; error.value = ''; notice.value = ''
  try { await action() } catch (failure) { error.value = String(failure) } finally { busy.value = false }
}
async function loadList() { snapshots.value = await request<Snapshot[]>(base) }
function parseCuts() {
  if (!editCuts.value) return null
  const items = cuts.value.trim().split(/[\s,，]+/).filter(Boolean)
  return items.map(text => {
    if (!/^\d+(\.\d{1,6})?$/.test(text)) throw new Error('切点使用秒数，最多六位小数')
    return Math.round(Number(text)*1_000_000)
  })
}
function addCut() {
  if (!editCuts.value) cuts.value = (scene.value?.shots || []).slice(1).map(s => s.start_us/1e6).join(', ')
  editCuts.value = true
  const points = cuts.value.split(/[\s,，]+/).filter(Boolean).map(Number).concat(props.playhead/1e6)
  cuts.value = [...new Set(points)].sort((a,b) => a-b).join(', ')
}
function chooseResult(id: string, checked: boolean) {
  const next = useResultIds.value.filter(key => key !== id)
  chosen.value = checked ? [...next,id] : next
}
function addEvidence() {
  evidence.value.push({ kind:'observation', start_us:props.playhead, end_us:props.playhead+500000, text:'' })
}
function addCandidate(frame: {task:string;id:number}) {
  candidates.value.push({kind:'scene', title:'', description:'', task_id:frame.task, artifact:frame.id})
}
function keyFor(payload:object) {
  const hash = JSON.stringify(payload)
  const key = keys.get(hash) || crypto.randomUUID()
  keys.set(hash,key)
  return key
}
async function save() {
  await run(async () => {
    const body = {
      expected_version:snapshots.value[0]?.number || 0, result_task_ids:useResultIds.value,
      cuts_us:parseCuts(),
      candidates:candidates.value.map(c => ({...c, fixed_version_id:c.fixed_version_id?.trim() || null})),
      evidence:evidence.value.map(({shots,...item}) => item), note:note.value,
    }
    loaded.value = await request<Snapshot>(base,{...body,idempotency_key:keyFor(body)})
    notice.value = `已保存审核快照 v${loaded.value.number}`
    await loadList()
  })
}
async function loadSnapshot(id:string) {
  await run(async () => {
    loaded.value = await request<Snapshot>(`/analysis/revisions/${id}`)
    const payload = loaded.value.payload
    if (!payload) return
    chosen.value = payload.result_task_ids
    editCuts.value = payload.cuts_us !== null
    cuts.value = payload.cuts_us?.map(n => n/1e6).join(', ') || ''
    note.value = payload.note
    evidence.value = payload.evidence.map(({start_us,end_us,text,kind}) => ({start_us,end_us,text,kind}))
    candidates.value = payload.candidates.map(({kind,title,description,task_id,artifact,fixed_version_id}) =>
      ({kind,title,description,task_id,artifact,fixed_version_id}))
  })
}
function useTranscript() {
  const manual = revised.value?.evidence.filter(e => e.kind === 'transcript').map(e => e.text) || []
  const linked = props.results.filter(r => revised.value?.result_task_ids.includes(r.task_id))
    .flatMap(r => r.subtitle_tracks?.find(t => t.cues.length)?.cues.map(c => c.text) ?? [])
  scriptBody.value = (manual.length ? manual : linked).join('\n').slice(0,100000)
}
async function adopt(kind:'character'|'scene'|'script', index?:number) {
  if (!loaded.value) return
  const id = loaded.value.id
  await run(async () => {
    const candidate = index === undefined ? undefined : revised.value?.candidates[index]
    const body = { kind, candidate:index ?? null, title:candidate?.title || scriptTitle.value,
      body:kind === 'script' ? scriptBody.value : '', note:approval.value }
    const version = await request<Version>(`/analysis/revisions/${id}/adopt`,{...body,idempotency_key:keyFor({...body,id})})
    notice.value = `已保存 ${version.title} · v${version.version}`
    if (kind === 'script') emit('adaptation',version)
    else emit('assetsChanged')
  })
}
onMounted(() => void run(loadList))
</script>

<template>
  <section class="review-panel">
    <h2>证据审核与创作资产</h2>
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="!results.length" class="hint">完成解析步骤后，可选择证据并保存审核快照。</p>
    <div v-if="snapshots.length" class="actions">
      <button v-for="item in snapshots" :key="item.id" :disabled="busy" :aria-pressed="loaded?.id === item.id"
        @click="loadSnapshot(item.id)">审核快照 v{{ item.number }}</button>
    </div>
    <form v-if="results.length" class="review-form" @submit.prevent="save">
      <details>
        <summary>快照证据 · {{ useResultIds.length }} 项</summary>
        <label v-for="result in results" :key="result.task_id" class="check">
          <input type="checkbox" :checked="useResultIds.includes(result.task_id)"
            @change="chooseResult(result.task_id,($event.target as HTMLInputElement).checked)">
          {{ operationLabels[result.operation] }} · {{ result.task_id.slice(0,8) }}
        </label>
      </details>
      <details v-if="scene || editCuts">
        <summary>人工修订切点</summary>
        <label class="check"><input v-model="editCuts" type="checkbox">使用人工切点</label>
        <label v-if="editCuts">切点秒数，按升序用逗号分隔；删除切点可合并相邻镜头
          <textarea v-model="cuts" placeholder="例如 2.125, 8.76"></textarea>
        </label>
        <button type="button" @click="addCut">在播放头添加切点</button>
      </details>
      <details>
        <summary>人工时间证据 · {{ evidence.length }}</summary>
        <fieldset v-for="(item,index) in evidence" :key="index">
          <legend>证据 {{ index+1 }}</legend>
          <div class="editor-grid">
            <label>证据类型<select v-model="item.kind"><option v-for="(label,key) in kinds" :key="key" :value="key">{{ label }}</option></select></label>
            <label>起点（微秒）<input v-model.number="item.start_us" type="number" min="0" required></label>
            <label>终点（微秒）<input v-model.number="item.end_us" type="number" min="1" required></label>
          </div>
          <label>人工描述<textarea v-model="item.text" maxlength="2000" required></textarea></label>
          <button type="button" @click="evidence.splice(index,1)">移除证据</button>
        </fieldset>
        <button type="button" :disabled="evidence.length>=300" @click="addEvidence">添加播放头证据</button>
      </details>
      <details>
        <summary>角色与场景候选 · {{ candidates.length }}</summary>
        <label>添加关键帧候选
          <select aria-label="添加关键帧候选" :disabled="candidates.length>=50" @change="event => {
            const select = event.target as HTMLSelectElement
            const frame = frames[Number(select.value)]
            if (select.value && frame) addCandidate(frame)
            select.value=''
          }">
            <option value="">选择已解析关键帧</option>
            <option v-for="(frame,i) in frames" :key="frame.task+frame.id" :value="i">{{ clock(frame.time_us || 0) }} · {{ frame.name }}</option>
          </select>
        </label>
        <p v-if="!frames.length" class="hint">先完成切镜或抽帧。</p>
        <fieldset v-for="(item,index) in candidates" :key="index">
          <legend>候选 {{ index+1 }}</legend>
          <img :src="artifactUrl(item.task_id,item.artifact)" alt="候选关键帧" loading="lazy">
          <div class="editor-grid">
            <label>候选类型<select v-model="item.kind"><option value="scene">场景</option><option value="character">角色</option></select></label>
            <label>候选名称<input v-model="item.title" required maxlength="200"></label>
          </div>
          <label>候选描述<textarea v-model="item.description" maxlength="4000"></textarea></label>
          <label>已有 P4 固定版本 ID（可留空）<input v-model="item.fixed_version_id" maxlength="36"></label>
          <button type="button" @click="candidates.splice(index,1)">移除候选</button>
        </fieldset>
      </details>
      <label>审核说明<textarea v-model="note" maxlength="4000" required></textarea></label>
      <button class="primary" :disabled="busy || !note.trim() || !useResultIds.length">保存审核快照</button>
    </form>
    <template v-if="revised && loaded">
      <p>v{{ loaded.number }} · {{ revised.shots.length }} 个镜头 · {{ revised.subtitle_cues.length }} 条对齐字幕 · {{ revised.evidence.length }} 条人工证据</p>
      <details v-if="revised.shots.length">
        <summary>已保存的镜头时间轴</summary>
        <div v-for="(shot,i) in revised.shots" :key="i" class="actions aligned">
          <button @click="emit('seek',shot.start_us)">镜头 {{ i+1 }} · {{ clock(shot.start_us) }} – {{ clock(shot.end_us) }}</button>
        </div>
        <p v-for="(item,i) in revised.evidence" :key="i">证据 {{ i+1 }} · {{ item.shots?.length ? '镜头 '+item.shots.join('、') : '镜头范围外' }} · {{ item.text }}</p>
      </details>
      <fieldset>
        <legend>采纳已审核的证据</legend>
        <label>采纳说明<textarea v-model="approval" maxlength="4000"></textarea></label>
        <div v-for="(item,index) in revised.candidates" :key="index" class="actions aligned">
          <span>{{ item.title }} · {{ item.kind==='scene'?'场景':'角色' }}</span>
          <button v-if="!item.fixed_version_id" :disabled="busy || !approval.trim()" @click="adopt(item.kind,index)">采纳为 P4 资产</button>
          <code v-else>{{ item.fixed_version_id }}</code>
        </div>
        <label>审核稿标题<input v-model="scriptTitle" maxlength="200"></label>
        <label>人工确认的审核稿正文<textarea v-model="scriptBody" maxlength="100000" rows="4"></textarea></label>
        <div class="actions aligned">
          <button @click="useTranscript">载入选定字幕或人工转写</button>
          <button class="primary" :disabled="busy || !approval.trim() || !scriptTitle.trim() || !scriptBody.trim()"
            @click="adopt('script')">保存 P4 剧本并打开 P5 改编</button>
        </div>
      </fieldset>
    </template>
  </section>
</template>

<style scoped>
.review-form { display:grid; gap:12px; margin:16px 0 }
.review-form details,.review-panel details { margin:0; padding:14px }
.review-panel label { margin:10px 0 }
.review-panel img { display:block; width:min(240px,100%); border-radius:5px }
.aligned { margin:8px 0 }
code { overflow-wrap:anywhere }
</style>
