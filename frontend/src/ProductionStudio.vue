<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { request, statusLabels } from './analysisApi'

interface Version { version_id:string; title:string; version:number; provenance?:{series_approved?:boolean} }
interface Issue { code:string; severity:'warning'|'error'; detail:string; start_ms:number|null; end_ms:number|null; clips?:string[] }
interface Policy {
  require_audio:boolean; require_subtitles:boolean; black_ms:number; freeze_ms:number; silence_ms:number; silence_db:number
  min_integrated_lufs?:number|null; max_true_peak_dbtp?:number|null
}
interface Episode {
  number:number; timeline_version_id:string; status:string; reused:boolean; render_reused?:boolean
  render_task_id:string;render_status:string;render_error:string|null;qc_status:string;qc_stage:string;qc_error:string|null
  qc:{
    output_sha256:string;issues:Issue[];rule_version:string
    video?:{width:number;height:number;frames:number|null;frame_rate:string|null}|null
    audio?:{status:string;integrated_lufs:number|null;true_peak_dbtp:number|null}|null
    captions?:{status:string;cue_count?:number;first_ms?:number;last_ms?:number}|null
  }|null
  review:{note:string}|null
}
interface Run {
  id:string;plan_version_id:string;created_at:string;status:string;episode_count:number;passed:number;reused:number;rechecked?:number
  episodes:Episode[]|null;policy:Policy
}
const props=defineProps<{projectId:string;initialRun?:string;initialEpisode?:string}>()
const emit=defineEmits<{
  inspectTimeline:[versionId:string,runId:string,episode:number,clipId?:string];
  openDelivery:[runId:string]
}>()
const plans=ref<Version[]>([]), timelines=ref<Version[]>([]), runs=ref<Run[]>([]), active=ref<Run|null>(null)
const plan=ref(''), prior=ref(''), links=ref<{number:number;title:string;timeline_version_id:string}[]>([])
const requireAudio=ref(false), requireSubtitles=ref(false)
const defaultTiming={black_ms:500,freeze_ms:750,silence_ms:1000,silence_db:-45}
const rules=reactive({...defaultTiming,min_integrated_lufs:'' as number|'',max_true_peak_dbtp:'' as number|''})
const recheckQuality=ref(false), originalPolicy=ref('')
const retryPrevious=ref(false)
const policy=computed<Policy>(()=>({
  require_audio:requireAudio.value,require_subtitles:requireSubtitles.value,
  black_ms:rules.black_ms,freeze_ms:rules.freeze_ms,silence_ms:rules.silence_ms,silence_db:rules.silence_db,
  min_integrated_lufs:rules.min_integrated_lufs==='' ? null : rules.min_integrated_lufs,
  max_true_peak_dbtp:rules.max_true_peak_dbtp==='' ? null : rules.max_true_peak_dbtp,
}))
const error=ref(''), notice=ref(''), busy=ref(false), reviewed=ref<Record<number,string>>({})
const selectedId=ref(props.initialRun||''), preview=ref('')
const previewEpisodeNumber=computed(()=>active.value?.episodes?.find(episode=>episode.render_task_id===preview.value)?.number)
const player=ref<HTMLVideoElement|null>(null), previewPosition=ref<number|null>(null)
const compose=ref<HTMLDetailsElement|null>(null)
const episodeFilter=ref<'all'|'attention'>('all')
const linkedEpisode = /^\d{1,2}$/.test(props.initialEpisode || '') ? Number(props.initialEpisode) : null
const visibleEpisodes=computed(() => (active.value?.episodes || []).filter(episode =>
  episodeFilter.value==='all' || ['needs_rework','needs_review'].includes(episode.status)))
const attentionCount=computed(() => (active.value?.episodes || []).filter(episode =>
  ['needs_rework','needs_review'].includes(episode.status)).length)
const keys=new Map<string,string>()
const states:Record<string,string>={processing:'执行中',needs_rework:'需返工',needs_review:'待人工复核',passed:'通过',cancelled:'已停止'}
let refreshing=false
let timer:ReturnType<typeof setInterval>|undefined
const path=`/production/projects/${props.projectId}/runs`
const ready=computed(()=>!!plan.value && (prior.value ? recheckQuality.value || retryPrevious.value || JSON.stringify(policy.value)!==originalPolicy.value ||
  links.value.some(item=>item.timeline_version_id) :
  links.value.length>0 && links.value.every(item=>item.timeline_version_id)))
const captionLabels:Record<string,string>={verified:'已核对哈希',observed:'已检查时序',absent:'无字幕输出',invalid:'字幕检查未通过'}
const metric=(value:number|null,unit:string)=>value===null ? '未测得' : `${value.toFixed(1)} ${unit}`
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
      const current=await request<Run>(path+'/'+encodeURIComponent(id))
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
  links.value=[]
  if(!plan.value)return
  const id=plan.value
  const report=await request<{episodes:{number:number;title:string}[]}>(`/series/versions/${id}/continuity`)
  if(id===plan.value)links.value=report.episodes.map(episode=>({...episode,timeline_version_id:''}))
}
watch(plan,()=>void run(loadPlan))
async function open(id:string){
  selectedId.value=id;preview.value='';previewPosition.value=null;reviewed.value={};episodeFilter.value='all'
  active.value=null
  await run(async()=>{const result=await request<Run>(path+'/'+id);if(selectedId.value===id)active.value=result})
}
async function submit(){
  await run(async()=>{
    const body={plan_version_id:plan.value,previous_run_id:prior.value||null,
      timelines:links.value.filter(item=>item.timeline_version_id).map(({number,timeline_version_id})=>({number,timeline_version_id})),
      policy:policy.value,recheck_quality:recheckQuality.value}
    const created=await request<Run>(path,{...body,idempotency_key:stableKey(body)})
    preview.value='';previewPosition.value=null;reviewed.value={};episodeFilter.value='all'
    selectedId.value=created.id
    active.value=created
    await refresh()
    notice.value=created.rechecked===created.episode_count ? '已提交整剧复检，使用已核对成片' : '已提交整剧渲染与质检'
  })
}
function startRework(batch:Run,recheck=false){
  prior.value=batch.id
  plan.value=batch.plan_version_id
  for(const link of links.value)link.timeline_version_id=''
  requireAudio.value=batch.policy.require_audio
  requireSubtitles.value=batch.policy.require_subtitles
  Object.assign(rules,{
    black_ms:batch.policy.black_ms ?? defaultTiming.black_ms,
    freeze_ms:batch.policy.freeze_ms ?? defaultTiming.freeze_ms,
    silence_ms:batch.policy.silence_ms ?? defaultTiming.silence_ms,
    silence_db:batch.policy.silence_db ?? defaultTiming.silence_db,
    min_integrated_lufs:batch.policy.min_integrated_lufs ?? '',
    max_true_peak_dbtp:batch.policy.max_true_peak_dbtp ?? '',
  })
  originalPolicy.value=JSON.stringify(policy.value)
  recheckQuality.value=recheck
  retryPrevious.value=batch.episodes?.some(episode=>episode.render_status!=='succeeded' || episode.qc_status!=='succeeded') ?? false
  notice.value=recheck ? '复检会读取保存的成片。成片或字幕损坏时，该集会重新渲染。' : '可为任意集更换时间轴。完好的成片与质检结果可复用。'
  if(compose.value){
    compose.value.open=true
    compose.value.querySelector('summary')?.focus()
  }
}
function leaveRework(){
  prior.value='';plan.value='';recheckQuality.value=false;retryPrevious.value=false;notice.value=''
  originalPolicy.value=''
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
function inspect(episode:Episode, clipId?:string){
  if(active.value)emit('inspectTimeline',episode.timeline_version_id,active.value.id,episode.number,clipId)
}
function positionPreview() {
  if (player.value && previewPosition.value !== null && Number.isFinite(player.value.duration)) {
    player.value.currentTime = Math.min(previewPosition.value, player.value.duration)
    previewPosition.value = null
  }
}
async function previewEpisode(episode:Episode, startMs=0) {
  if (episode.render_status !== 'succeeded') return
  previewPosition.value = Math.max(0,startMs)/1000
  preview.value = episode.render_task_id
  await nextTick()
  positionPreview()
  player.value?.scrollIntoView({block:'nearest'})
}
onMounted(()=>{
  void run(async()=>{
    await Promise.all([loadVersions(),refresh()])
    if (linkedEpisode && active.value?.episodes?.some(episode=>episode.number===linkedEpisode)) {
      await nextTick()
      const article = document.getElementById('production-episode-'+linkedEpisode)
      article?.scrollIntoView({block:'center'})
      article?.focus({preventScroll:true})
    }
  })
  timer=setInterval(()=>{if(!busy.value)void refresh().catch(failure=>{error.value=String(failure)})},3500)
})
onUnmounted(()=>clearInterval(timer))
</script>
<template>
  <section v-if="projectId" class="production">
    <h2>整剧生产与技术质检</h2>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <details ref="compose">
      <summary>{{ recheckQuality ? '提交技术复检' : prior ? '提交局部返工' : '提交整剧批次' }}</summary>
      <form class="form-grid" @submit.prevent="submit">
        <label>已批准制作计划<select v-model="plan" :disabled="!!prior" required>
          <option value="">选择故事圣经版本</option>
          <option v-if="prior && !plans.some(item=>item.version_id===plan)" :value="plan">{{ plan }}</option>
          <option v-for="item in plans" :key="item.version_id" :value="item.version_id">{{ versionLabel(item) }}</option>
        </select></label>
        <button v-if="prior" type="button" @click="leaveRework">退出当前操作</button>
        <p v-if="!plans.length && !prior" class="hint">在故事圣经批准制作计划，并保存各集的固定时间轴后提交。</p>
        <div v-if="links.length" class="editor-grid">
          <label v-for="unit in links" :key="unit.number">第 {{ unit.number }} 集 · {{ unit.title }}
            <select v-model="unit.timeline_version_id" :required="!prior">
              <option value="">{{ prior ? '保留原时间轴' : '选择固定时间轴' }}</option>
              <option v-for="item in timelines" :key="item.version_id" :value="item.version_id">{{ versionLabel(item) }}</option>
            </select>
          </label>
        </div>
        <details class="quality-rules">
          <summary>技术质检阈值</summary>
          <div class="editor-grid">
            <label>黑场最短毫秒<input v-model.number="rules.black_ms" type="number" min="100" max="10000" required></label>
            <label>冻结最短毫秒<input v-model.number="rules.freeze_ms" type="number" min="100" max="10000" required></label>
            <label>静音最短毫秒<input v-model.number="rules.silence_ms" type="number" min="100" max="10000" required></label>
            <label>静音电平（dB）<input v-model.number="rules.silence_db" type="number" min="-99" max="-10" required></label>
            <label>响度下限（LUFS）<input v-model.number="rules.min_integrated_lufs" type="number" min="-60" max="0" step="0.1" placeholder="仅测量"></label>
            <label>真峰值上限（dBTP）<input v-model.number="rules.max_true_peak_dbtp" type="number" min="-20" max="0" step="0.1" placeholder="仅测量"></label>
          </div>
          <p class="hint">低于响度下限或高于真峰值上限时，需要人工复核。</p>
        </details>
        <div class="actions">
          <label class="check"><input v-model="requireAudio" type="checkbox">要求音轨</label>
          <label class="check"><input v-model="requireSubtitles" type="checkbox">要求字幕</label>
          <button class="primary" :disabled="busy || !ready">{{ recheckQuality && !links.some(item=>item.timeline_version_id) ? '提交技术复检' : '提交渲染和质检' }}</button>
        </div>
      </form>
    </details>
    <div class="version-list">
      <button v-for="batch in runs" :key="batch.id" :aria-pressed="batch.id===selectedId" :disabled="busy" @click="open(batch.id)">
        {{ states[batch.status] }} · {{ batch.passed }}/{{ batch.episode_count }} 集 · {{ new Date(batch.created_at).toLocaleString('zh-CN') }}
      </button>
    </div>
    <template v-if="active">
      <div class="actions run-summary">
        <div><strong>批次 {{ states[active.status] }}</strong><p>{{ active.passed }}/{{ active.episode_count }} 集通过 · {{ active.reused }} 集复用<span v-if="active.rechecked"> · {{active.rechecked}} 集复用成片复检</span></p></div>
        <button v-if="active.status==='processing'" :disabled="busy" @click="run(async()=>{await request('/production/runs/'+active!.id+'/cancel',{});await refresh()})">停止批次</button>
        <button v-else :disabled="busy" @click="startRework(active)">按此批次局部返工</button>
        <button v-if="active.status!=='processing'" :disabled="busy" @click="startRework(active,true)">使用当前规则复检</button>
        <a v-if="active.status!=='processing'" :href="'/api'+path+'/'+active.id+'?download=true'">下载质检报告</a>
        <button v-if="active.status==='passed'" class="primary" @click="emit('openDelivery',active.id)">核对授权与交付</button>
      </div>
      <div v-if="attentionCount" class="actions episode-filter" aria-label="分集状态">
        <button type="button" :aria-pressed="episodeFilter==='all'" @click="episodeFilter='all'">全部分集</button>
        <button type="button" :aria-pressed="episodeFilter==='attention'" @click="episodeFilter='attention'">待复核与返工 · {{ attentionCount }}</button>
      </div>
      <div class="review-desk">
        <aside class="review-preview" aria-label="成片监看">
          <div class="preview-heading"><strong>成片监看</strong><span v-if="previewEpisodeNumber">第 {{ previewEpisodeNumber }} 集</span></div>
          <video v-if="preview" :key="preview" ref="player" controls preload="metadata" :aria-label="`第 ${previewEpisodeNumber} 集成片`"
            :src="`/api/tasks/${preview}/output`" @loadedmetadata="positionPreview"></video>
          <p v-else class="hint">{{ active.episodes?.some(episode=>episode.render_status==='succeeded') ? '选择一集预览，或从质检发现跳转到对应时间点。' : '成片完成后可在此预览。' }}</p>
        </aside>
        <div class="episode-list">
      <article v-for="episode in visibleEpisodes" :id="'production-episode-'+episode.number" :key="episode.number" tabindex="-1"
        class="episode" :class="{ 'linked-episode':active.id===initialRun && episode.number===linkedEpisode }">
        <div class="actions">
          <strong>第 {{ episode.number }} 集</strong><span>{{ states[episode.status] }}<template v-if="episode.reused"> · 已校验复用</template><template v-else-if="episode.render_reused"> · 成片复用</template></span>
          <button v-if="episode.render_status==='succeeded'" :aria-pressed="preview===episode.render_task_id" @click="previewEpisode(episode)">预览本集</button>
          <button @click="inspect(episode)">打开固定时间轴</button>
        </div>
        <p class="hint">渲染 {{ statusLabels[episode.render_status] || episode.render_status }} · 质检 {{ episode.qc_stage==='dependency_failed'?'上游失败未执行':statusLabels[episode.qc_status] || episode.qc_status }}</p>
        <p v-if="episode.render_error || episode.qc_error" class="error">{{ episode.render_error || episode.qc_error }}</p>
        <dl v-if="episode.qc?.rule_version==='ffmpeg-technical-v2'" class="quality-measurements">
          <div v-if="episode.qc.video"><dt>画面规格</dt><dd>{{episode.qc.video.width}} × {{episode.qc.video.height}} · {{episode.qc.video.frames ?? '—'}} 帧</dd></div>
          <div v-if="episode.qc.audio"><dt>整段响度</dt><dd>{{metric(episode.qc.audio.integrated_lufs,'LUFS')}}</dd></div>
          <div v-if="episode.qc.audio"><dt>真峰值</dt><dd>{{metric(episode.qc.audio.true_peak_dbtp,'dBTP')}}</dd></div>
          <div v-if="episode.qc.captions"><dt>成片字幕</dt><dd>{{captionLabels[episode.qc.captions.status]}}<span v-if="episode.qc.captions.cue_count!=null"> · {{episode.qc.captions.cue_count}} 条</span></dd></div>
        </dl>
        <ul v-if="episode.qc?.issues.length">
          <li v-for="(issue,i) in episode.qc.issues" :key="i" :class="{failed:issue.severity==='error'}">
            {{ issue.detail }} <template v-if="issue.start_ms!==null">· {{ issue.start_ms/1000 }}–{{ (issue.end_ms||0)/1000 }} 秒</template>
            <button v-if="issue.start_ms!==null && episode.render_status==='succeeded'" class="finding-preview" @click="previewEpisode(episode,issue.start_ms)">预览问题位置</button>
            <div v-if="issue.clips?.length" class="actions finding-clips">
              <button v-for="(clip,index) in issue.clips" :key="clip" @click="inspect(episode,clip)">定位关联片段{{ issue.clips.length>1 ? ' '+(index+1) : '' }}</button>
            </div>
          </li>
        </ul>
        <p v-if="episode.review">人工复核 · {{ episode.review.note }}</p>
        <form v-if="episode.status==='needs_review'" class="form-grid" @submit.prevent="approve(episode)">
          <label>第 {{ episode.number }} 集复核意见<textarea v-model="reviewed[episode.number]" required maxlength="4000"></textarea></label>
          <button :disabled="busy || !reviewed[episode.number]?.trim()">确认可接受的告警</button>
        </form>
      </article>
        </div>
      </div>
    </template>
  </section>
</template>
<style scoped>
.production { margin-bottom:24px }
.form-grid { display:grid; gap:12px; margin:14px 0 0 }
.episode { padding:14px 0; border-top:1px solid #334050 }
.review-desk { display:grid; grid-template-columns:minmax(0,1fr) minmax(260px,.85fr); gap:16px; align-items:start }
.episode-list { grid-column:1; grid-row:1; min-width:0 }
.review-preview { grid-column:2; grid-row:1; min-width:0; position:sticky; top:80px; border:1px solid var(--line-soft); border-radius:8px; overflow:hidden; background:var(--surface-raised) }
.preview-heading { display:flex; justify-content:space-between; align-items:center; gap:8px; padding:10px 12px }
.preview-heading span { color:var(--ink-muted); font-size:12px }
.review-preview video { display:block; width:100%; max-height:53vh; margin:0; border-radius:0; background:#0b0f15 }
.review-preview p { margin:0; padding:0 12px 14px }
@media(max-width:1080px) {
  .review-desk { grid-template-columns:1fr; gap:12px }
  .review-preview { grid-column:1; position:static }
  .episode-list { grid-row:2 }
}
.finding-clips { margin:5px 0 }
.quality-rules .editor-grid { margin-top:10px }
.quality-measurements { display:flex; flex-wrap:wrap; gap:7px; margin:8px 0 }
.quality-measurements div { background:var(--surface-raised); border:1px solid var(--line-soft); border-radius:6px; padding:6px 10px }
.quality-measurements dt { color:var(--ink-muted); font-size:11px }
.quality-measurements dd { margin:2px 0 0; font-size:13px }
.run-summary { background:#101d25; border:1px solid var(--line-soft); border-radius:8px; padding:12px; margin:13px 0 }
.run-summary > div { margin-right:auto }
.run-summary p { margin:4px 0 0; color:var(--ink-muted) }
.episode-filter { margin:10px 0 }
.episode-filter button[aria-pressed=true] { color:var(--accent); background:var(--accent-surface) }
.linked-episode { box-shadow:inset 3px 0 var(--accent); padding-left:11px; background:#122530 }
.finding-preview { margin:5px 0 5px 8px; font-size:12px }
</style>
