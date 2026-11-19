<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { request, statusLabels } from './analysisApi'

interface Version { version_id:string; title:string; version:number; provenance?:{series_approved?:boolean} }
interface Issue { code:string; severity:'warning'|'error'; detail:string; start_ms:number|null; end_ms:number|null; clips?:string[] }
interface Episode {
  number:number; timeline_version_id:string; status:string; reused:boolean
  render_task_id:string;render_status:string;render_error:string|null;qc_status:string;qc_stage:string;qc_error:string|null
  qc:{output_sha256:string;issues:Issue[]}|null;review:{note:string}|null
}
interface Run {
  id:string;plan_version_id:string;created_at:string;status:string;episode_count:number;passed:number;reused:number
  episodes:Episode[]|null;policy:{require_audio:boolean;require_subtitles:boolean}
}
const props=defineProps<{projectId:string}>()
const emit=defineEmits<{ inspectTimeline:[versionId:string] }>()
const plans=ref<Version[]>([]), timelines=ref<Version[]>([]), runs=ref<Run[]>([]), active=ref<Run|null>(null)
const plan=ref(''), prior=ref(''), links=ref<{number:number;title:string;timeline_version_id:string}[]>([])
const requireAudio=ref(false), requireSubtitles=ref(false)
const error=ref(''), notice=ref(''), busy=ref(false), reviewed=ref<Record<number,string>>({})
const selectedId=ref(''), preview=ref('')
const keys=new Map<string,string>()
const states:Record<string,string>={processing:'执行中',needs_rework:'需返工',needs_review:'待人工复核',passed:'通过',cancelled:'已停止'}
let refreshing=false
let timer:ReturnType<typeof setInterval>|undefined
const path=`/production/projects/${props.projectId}/runs`
const ready=computed(()=>!!plan.value && (prior.value ? links.value.some(item=>item.timeline_version_id) :
  links.value.length>0 && links.value.every(item=>item.timeline_version_id)))
function stableKey(body:object){
  const fingerprint=JSON.stringify(body)
  if(!keys.has(fingerprint))keys.set(fingerprint,crypto.randomUUID())
  return keys.get(fingerprint)!
}
function versionLabel(item:Version){return item.title+' · v'+item.version}
async function run(action:()=>Promise<void>){
  busy.value=true;error.value='';notice.value=''
  try{await action()}catch(failure){error.value=String(failure)}finally{busy.value=false}
}
async function refresh(){
  if(!props.projectId || refreshing)return
  refreshing=true
  try{
    runs.value=await request<Run[]>(path)
    const id=selectedId.value
    if(id){
      const current=await request<Run>('/production/runs/'+id)
      if(id===selectedId.value)active.value=current
    }
  }finally{refreshing=false}
}
async function loadVersions(){
  if(!props.projectId)return
  const root=`/projects/${props.projectId}/story/entities?kind=`
  const [bibles,edits]=await Promise.all([request<{items:Version[]}>(root+'story_bible'),request<{items:Version[]}>(root+'timeline')])
  plans.value=bibles.items.filter(item=>item.provenance?.series_approved)
  timelines.value=edits.items
}
async function loadPlan(){
  if(!plan.value){links.value=[];return}
  const id=plan.value
  const report=await request<{episodes:{number:number;title:string}[]}>(`/series/versions/${id}/continuity`)
  if(id===plan.value)links.value=report.episodes.map(episode=>({...episode,timeline_version_id:''}))
}
watch(plan,()=>void run(loadPlan))
async function open(id:string){
  selectedId.value=id;preview.value='';reviewed.value={}
  await run(async()=>{const result=await request<Run>('/production/runs/'+id);if(selectedId.value===id)active.value=result})
}
async function submit(){
  await run(async()=>{
    const body={plan_version_id:plan.value,previous_run_id:prior.value||null,
      timelines:links.value.filter(item=>item.timeline_version_id).map(({number,timeline_version_id})=>({number,timeline_version_id})),
      policy:{require_audio:requireAudio.value,require_subtitles:requireSubtitles.value}}
    const created=await request<Run>(path,{...body,idempotency_key:stableKey(body)})
    selectedId.value=created.id
    active.value=created
    await refresh()
    notice.value='已提交整剧渲染与质检'
  })
}
function startRework(batch:Run){
  prior.value=batch.id
  plan.value=batch.plan_version_id
  for(const link of links.value)link.timeline_version_id=''
  requireAudio.value=batch.policy.require_audio
  requireSubtitles.value=batch.policy.require_subtitles
  notice.value='选择需要替换时间轴的分集。其余分集按原产物校验并复用。'
}
async function approve(episode:Episode){
  if(!active.value || !episode.qc)return
  const batch=active.value.id
  await run(async()=>{
    const body={expected_sha256:episode.qc!.output_sha256,note:reviewed.value[episode.number]||''}
    active.value=await request<Run>(`/production/runs/${batch}/episodes/${episode.number}/review`,
      {...body,idempotency_key:stableKey({...body,batch,episode:episode.number})})
    await refresh()
    notice.value='已保存人工复核意见'
  })
}
onMounted(()=>{
  void run(async()=>{await loadVersions();await refresh()})
  timer=setInterval(()=>{if(!busy.value)void refresh().catch(failure=>{error.value=String(failure)})},3500)
})
onUnmounted(()=>clearInterval(timer))
</script>
<template>
  <section v-if="projectId" class="production">
    <h2>整剧生产与技术质检</h2>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <details>
      <summary>{{ prior ? '提交局部返工' : '提交整剧批次' }}</summary>
      <form class="form-grid" @submit.prevent="submit">
        <label>已批准制作计划<select v-model="plan" :disabled="!!prior" required>
          <option value="">选择故事圣经版本</option>
          <option v-if="prior && !plans.some(item=>item.version_id===plan)" :value="plan">{{ plan }}</option>
          <option v-for="item in plans" :key="item.version_id" :value="item.version_id">{{ versionLabel(item) }}</option>
        </select></label>
        <button v-if="prior" type="button" @click="prior='';plan=''">退出返工</button>
        <p v-if="!plans.length && !prior" class="hint">在故事圣经批准制作计划，并保存各集的固定时间轴后提交。</p>
        <div v-if="links.length" class="editor-grid">
          <label v-for="unit in links" :key="unit.number">第 {{ unit.number }} 集 · {{ unit.title }}
            <select v-model="unit.timeline_version_id" :required="!prior">
              <option value="">{{ prior ? '保留原时间轴' : '选择固定时间轴' }}</option>
              <option v-for="item in timelines" :key="item.version_id" :value="item.version_id">{{ versionLabel(item) }}</option>
            </select>
          </label>
        </div>
        <div class="actions">
          <label class="check"><input v-model="requireAudio" type="checkbox">要求音轨</label>
          <label class="check"><input v-model="requireSubtitles" type="checkbox">要求字幕</label>
          <button class="primary" :disabled="busy || !ready">提交渲染和质检</button>
        </div>
      </form>
    </details>
    <div class="version-list">
      <button v-for="batch in runs" :key="batch.id" :aria-pressed="batch.id===selectedId" :disabled="busy" @click="open(batch.id)">
        {{ states[batch.status] }} · {{ batch.passed }}/{{ batch.episode_count }} 集 · {{ new Date(batch.created_at).toLocaleString('zh-CN') }}
      </button>
    </div>
    <template v-if="active">
      <div class="actions">
        <p>批次 {{ states[active.status] }} · {{ active.passed }}/{{ active.episode_count }} 集通过 · {{ active.reused }} 集复用</p>
        <button v-if="active.status==='processing'" :disabled="busy" @click="run(async()=>{await request('/production/runs/'+active!.id+'/cancel',{});await refresh()})">停止批次</button>
        <button v-else :disabled="busy" @click="startRework(active)">按此批次局部返工</button>
      </div>
      <video v-if="preview" :key="preview" controls :src="`/api/tasks/${preview}/output`"></video>
      <article v-for="episode in active.episodes" :key="episode.number" class="episode">
        <div class="actions">
          <strong>第 {{ episode.number }} 集</strong><span>{{ states[episode.status] }}<template v-if="episode.reused"> · 已校验复用</template></span>
          <button v-if="episode.render_status==='succeeded'" @click="preview=episode.render_task_id">预览本集</button>
          <button @click="emit('inspectTimeline',episode.timeline_version_id)">打开固定时间轴</button>
        </div>
        <p class="hint">渲染 {{ statusLabels[episode.render_status] || episode.render_status }} · 质检 {{ episode.qc_stage==='dependency_failed'?'上游失败未执行':statusLabels[episode.qc_status] || episode.qc_status }}</p>
        <p v-if="episode.render_error || episode.qc_error" class="error">{{ episode.render_error || episode.qc_error }}</p>
        <ul v-if="episode.qc?.issues.length">
          <li v-for="(issue,i) in episode.qc.issues" :key="i" :class="{failed:issue.severity==='error'}">
            {{ issue.detail }} <template v-if="issue.start_ms!==null">· {{ issue.start_ms/1000 }}–{{ (issue.end_ms||0)/1000 }} 秒</template>
          </li>
        </ul>
        <p v-if="episode.review">人工复核 · {{ episode.review.note }}</p>
        <form v-if="episode.status==='needs_review'" class="form-grid" @submit.prevent="approve(episode)">
          <label>第 {{ episode.number }} 集复核意见<textarea v-model="reviewed[episode.number]" required maxlength="4000"></textarea></label>
          <button :disabled="busy || !reviewed[episode.number]?.trim()">确认可接受的告警</button>
        </form>
      </article>
    </template>
  </section>
</template>
<style scoped>
.production { margin-bottom:24px }
.form-grid { display:grid; gap:12px; margin:14px 0 0 }
.episode { padding:14px 0; border-top:1px solid #334050 }
.production video { max-height:59vh }
</style>
