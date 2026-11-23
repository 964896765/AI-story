<script setup lang="ts">
import SpecReference from '../components/production/SpecReference.vue'
import type { ProductionSpecRef } from '../types/productionSpec'
import { computed, nextTick, ref, watch } from 'vue'
import { AlertTriangle, GitCompareArrows } from 'lucide-vue-next'
import { request, statusLabels } from '../analysisApi'
import GuardianShotRework from '../components/production/GuardianShotRework.vue'
import GuardianReferenceCompare, { type SavedComparison } from '../components/production/GuardianReferenceCompare.vue'
import type { ReviewFrame, SavedChecklist } from '../components/production/GuardianVisualChecklist.vue'
import VisualCandidateCheck, { type VisualReport } from '../components/production/VisualCandidateCheck.vue'
import ScreenTextCheck, { type ScreenTextReport } from '../components/production/ScreenTextCheck.vue'
import type { ScreenTextContract } from '../components/production/GuardianShot.vue'
import { useWorkspace } from '../router/workspace'
import { appearance } from '../stores/appearance'

interface Edition {
  id:string; version_id:string; title:string; version:number; project_id:string
  kind:string; content:null | {guardian?:unknown;script_version_id:string}; provenance:{guardian_manifest?:object}
}
interface Finding { code:string; severity:string; detail:string; episode:number; shot:string|null; start_ms?:number; evidence?:Record<string,unknown> }
interface Shot {
  shot_id:string; number:number; description:string; start_ms:number; duration_ms:number; strategy:string
  scene_version_id:string|null; character_version_ids:string[]
  guardian?:{contract_sha256:string; visual:string; source_images:Record<string,string>;screen_text?:ScreenTextContract}|null
}
interface Episode {number:number;title:string;storyboard_version_id:string;shots:Shot[]}
interface Report {approved:boolean;ready_for_review:boolean;issues:Finding[];episodes:Episode[];guardian?:{style:string;shot_count:number};production_spec?:ProductionSpecRef}
interface Candidate {
  id:string;asset_id:string;story_version_id:string;status:string;guardian?:{contract_sha256:string;series_id:string}
  selected_asset_id:string|null;progress:number;error:string|null;rework?:{reason:string}
  parameters:{shot_id:string;preset:string;aspect:string};output:{actual_external_cost_micros?:number;guardian_frames?:{index:number;time_ms:number}[];
    guardian_visual?:VisualReport;
    guardian_screen_text?:ScreenTextReport;
    guardian_review?:{request:{decision:string;note:string;category:string|null};evidence:{time_ms:number}|null;
      comparison?:SavedComparison;checklist?:SavedChecklist}}
}
interface Change {shot_id:string;kind:string;before:{episode:number;start_ms:number}|null;after:{episode:number;start_ms:number}|null}

const { workbench, query, link, go } = useWorkspace()
const choices=ref<Edition[]>([]), history=ref<Edition[]>([]), version=ref<Edition|null>(null), report=ref<Report|null>(null)
const candidates=ref<Candidate[]>([]), episodeNo=ref(0), selectedShot=ref(''), finding=ref<Finding|null>(null), candidateId=ref('')
const loading=ref(true), failure=ref(''), impactFailure=ref(''), baseline=ref(''), changes=ref<Change[]|null>(null), comparing=ref(false)
const episodes=computed(()=>report.value?.episodes || [])
const episode=computed(()=>episodes.value.find(item=>item.number===episodeNo.value))
const shot=computed(()=>episode.value?.shots.find(item=>item.shot_id===selectedShot.value))
const issues=computed(()=>report.value?.issues.filter(item=>episodeNo.value===0 ? item.episode===0 : item.episode===episodeNo.value) || [])
const blockers=computed(()=>report.value?.issues.filter(item=>item.severity==='error').length ?? 0)
const warnings=computed(()=>report.value?.issues.filter(item=>item.severity==='warning').length ?? 0)
const editionOptions=computed(()=>Array.from(new Map([...choices.value,...(version.value?[version.value]:[])]
  .map(item=>[item.version_id,item])).values()))
const activeCandidates=computed(()=>candidates.value.filter(item=>item.guardian?.series_id===version.value?.id
  && item.guardian?.contract_sha256===shot.value?.guardian?.contract_sha256 && item.parameters.shot_id===shot.value?.shot_id))
const candidate=computed(()=>activeCandidates.value.find(item=>item.id===candidateId.value) || activeCandidates.value[0])
const evidenceFrames=computed(()=>(candidate.value?.output.guardian_frames || []).slice().sort((a,b)=>a.time_ms-b.time_ms))
const applicableCandidate=computed(()=>candidate.value?.story_version_id===version.value?.version_id &&
  candidate.value?.selected_asset_id && candidate.value.output.guardian_review?.request.decision==='approved' ? candidate.value.id : undefined)
const activeApproval=computed(()=>history.value.find(item=>item.provenance.guardian_manifest)?.version_id===version.value?.version_id)
const shotFrames=computed(()=>shot.value ? Math.round((shot.value.start_ms+shot.value.duration_ms)*24/1000)-Math.round(shot.value.start_ms*24/1000) : 0)
const shotSelect=ref<HTMLSelectElement|null>(null)
const focusedFrame=ref('')
const candidateFailure=ref('')
const refreshCandidates=ref(0)
function focusEvidence(frame:ReviewFrame) {
  const id=`guardian-evidence-${candidate.value?.id}-${frame.index}`
  const element=document.getElementById(id)
  if (!element) return
  focusedFrame.value=id
  element.scrollIntoView({block:'center'})
  element.focus({preventScroll:true})
}
const issueCount=(number:number)=>report.value?.issues.filter(item=>item.episode===number).length || 0
const time=(ms:number)=>(ms/1000).toFixed(3)+' 秒'
const kinds:Record<string,string>={added:'新增',removed:'移除',contract_changed:'合同变化',moved:'位置变化',unchanged:'可按原合同复用'}
const evidenceLabels:Record<string,string>={expected:'预期值',observed:'实际登记',previous_episode:'前一集',previous_shot:'前一镜头',
  character_version_id:'角色版本',fields:'差异字段',transition_note:'衔接说明',fact:'事实键名',field:'检查字段',allowed:'可用服装',
  observed_version_id:'实际版本',allowed_version_ids:'已锁定版本',wardrobe_id:'服装',left_hand:'左手',right_hand:'右手',action:'动作',
  position:'位置',scene_version_id:'场景版本'}
const changedFields=computed(()=>finding.value?.evidence?.fields as Record<string,{expected:unknown;observed:unknown}>|undefined)
const displayValue=(value:unknown)=>value==null || value==='' ? '—' : typeof value==='object' ? JSON.stringify(value) : String(value)

function pickEpisode(number:number) {
  episodeNo.value=number
  finding.value=issues.value[0] || null
  selectedShot.value=finding.value?.shot || episode.value?.shots[0]?.shot_id || ''
  candidateId.value=''
}
function pickFinding(item:Finding) {
  finding.value=item
  selectedShot.value=item.shot || ''
  candidateId.value=''
}
function pickShot(id:string) {
  selectedShot.value=id
  finding.value=issues.value.find(item=>item.shot===id) || null
  candidateId.value=''
}
async function locateImpact(change:Change) {
  if (!change.after) return
  pickEpisode(change.after.episode)
  pickShot(change.shot_id)
  await nextTick()
  shotSelect.value?.focus()
}
function queuedRework(id:string) {
  candidateId.value=id
  refreshCandidates.value++
}
watch([version,selectedShot,refreshCandidates],([edition,id],_,onCleanup)=>{
  candidateFailure.value=''
  if (!edition || !id) { candidates.value=[]; return }
  let current=true
  let timer:ReturnType<typeof setTimeout>
  onCleanup(()=>{current=false;clearTimeout(timer)})
  const params=new URLSearchParams({series_id:edition.id,shot_id:id})
  async function refresh() {
    try {
      const rows=await request<Candidate[]>(`/generation/projects/${workbench.projectId}/candidates?${params}`)
      if (!current) return
      candidates.value=rows
      candidateFailure.value=''
      if (rows.some(item=>['queued','running'].includes(item.status))) timer=setTimeout(refresh,1500)
    } catch(error) { if (current) candidateFailure.value=String(error) }
  }
  void refresh()
})
let loadToken=0
watch(()=>workbench.projectId,async(project)=>{
  const token=++loadToken
  choices.value=[]; history.value=[]; version.value=null; report.value=null; candidates.value=[]
  loading.value=!!project; failure.value=''
  if(!project)return
  try {
    const path='/projects/'+encodeURIComponent(project)+'/story/entities?kind=story_bible'
    const list=await request<{items:Edition[]}>(path)
    if(token!==loadToken)return
    choices.value=list.items
    const id=query('version') || list.items[0]?.version_id
    if(!id)return
    const current=await request<Edition>('/story/versions/'+encodeURIComponent(id))
    if(token!==loadToken)return
    if(current.project_id!==project || current.kind!=='story_bible')throw new Error('此版本不属于当前项目的故事圣经')
    const [result,versions]=await Promise.all([
      request<Report>('/series/versions/'+encodeURIComponent(id)+'/continuity'),
      request<Edition[]>('/story/entities/'+current.id+'/versions'),
    ])
    if(token!==loadToken)return
    version.value=current; report.value=result; history.value=versions
    const linkedShot=query('shot')
    const linkedEpisode=result.episodes.find(item=>item.shots.some(shot=>shot.shot_id===linkedShot))
    pickEpisode(linkedEpisode?.number ?? result.issues[0]?.episode ?? result.episodes[0]?.number ?? 0)
    if (linkedEpisode) { pickShot(linkedShot); candidateId.value=query('candidate') }
  }catch(error){if(token===loadToken)failure.value=String(error)}finally{if(token===loadToken)loading.value=false}
},{immediate:true})

async function compare() {
  if(!version.value || !baseline.value)return
  comparing.value=true; impactFailure.value=''; changes.value=null
  try {
    const result=await request<{shots:Change[]}>(`/series/versions/${version.value.version_id}/impact?baseline_version_id=${encodeURIComponent(baseline.value)}`)
    changes.value=result.shots
  } catch(error){impactFailure.value=String(error)} finally{comparing.value=false}
}
</script>

<template>
  <div class="guardian-workbench" :data-theme="appearance">
    <p v-if="loading" role="status">正在读取制作约束与审核记录…</p>
    <p v-else-if="failure" role="alert" class="guardian-error">{{ failure }}</p>
    <p v-else-if="!workbench.projectId">请选择项目。</p>
    <section v-else-if="!version" class="guardian-panel guardian-start">
      <div>
        <h2>当前项目还没有故事圣经</h2>
        <p>Guardian 需要一份固定计划，把分集、分镜和审核证据对应到具体镜头。</p>
        <RouterLink :to="link('wizard',{step:4})">查看分镜到质检的完整步骤</RouterLink>
      </div>
      <ol>
        <li><RouterLink :to="link('story',{flow:5})">保存原稿、剧本和分集</RouterLink><small>先确定本次采用的内容版本。</small></li>
        <li><RouterLink :to="link('storyboard',{flow:13})">建立分镜</RouterLink><small>给每个镜头填写时长、人物、场景和动作。</small></li>
        <li><RouterLink :to="link('bible',{flow:16})">打开故事圣经</RouterLink><small>引用固定分镜，核对连续性并批准计划，再回来检查候选与证据。</small></li>
      </ol>
    </section>
    <template v-else>
      <SpecReference :project-id="workbench.projectId" :version-id="report?.production_spec?.id" />
      <div class="guardian-toolbar">
        <label>故事圣经<select :value="version.version_id" @change="go('guardian',{version:($event.target as HTMLSelectElement).value})">
          <option v-for="item in editionOptions" :key="item.version_id" :value="item.version_id">{{ item.title }} · v{{ item.version }}</option>
        </select></label>
        <label>历史版本<select :value="version.version_id" @change="go('guardian',{version:($event.target as HTMLSelectElement).value})">
          <option v-for="item in history" :key="item.version_id" :value="item.version_id">v{{item.version}}</option>
        </select></label>
        <RouterLink :to="link('bible',{version:version.version_id})">打开固定故事圣经</RouterLink>
      </div>
      <p v-if="!report?.guardian" class="guardian-panel">所选版本沿用基础连续性检查。可在故事圣经的「Guardian 正史与风格锁」启用规则。</p>
      <template v-else>
        <dl class="guardian-metrics">
          <div><dt>规则状态</dt><dd :class="{'guardian-error':blockers}">{{ blockers?'存在阻断':report.approved?'已批准':'待批准' }}</dd></div>
          <div><dt>固定镜头</dt><dd>{{ report.guardian.shot_count }}</dd></div>
          <div><dt>阻断问题</dt><dd>{{ blockers }}</dd></div>
          <div><dt>规则告警</dt><dd>{{ warnings }}</dd></div>
        </dl>
        <div class="guardian-layout">
          <section class="guardian-panel issue-panel" aria-label="分集与问题">
            <h2>分集与问题</h2>
            <button type="button" :aria-pressed="episodeNo===0" @click="pickEpisode(0)">全剧 <span>{{ issueCount(0) }}</span></button>
            <button v-for="unit in episodes" :key="unit.number" type="button" :aria-pressed="episodeNo===unit.number" @click="pickEpisode(unit.number)">
              {{ unit.title === `第 ${unit.number} 集` ? unit.title : `第 ${unit.number} 集 · ${unit.title}` }} <span>{{ issueCount(unit.number) }}</span>
            </button>
            <div v-if="issues.length" class="guardian-issues">
              <button v-for="(item,index) in issues" :key="index" type="button" :aria-pressed="finding===item" @click="pickFinding(item)">
                <AlertTriangle :size="16" aria-hidden="true" /><span>{{ item.detail }}<small>{{item.severity==='error'?'阻断':'人工复核'}}<template v-if="item.shot"> · {{item.shot}}</template></small></span>
              </button>
            </div>
            <p v-else class="guardian-muted">这一范围暂无规则发现。</p>
          </section>

          <section class="guardian-panel evidence-panel">
            <h2>问题与证据</h2>
            <label v-if="episode">镜头<select ref="shotSelect" :value="selectedShot" @change="pickShot(($event.target as HTMLSelectElement).value)">
              <option value="">选择镜头</option>
              <option v-for="item in episode.shots" :key="item.shot_id" :value="item.shot_id">{{item.number}} · {{item.description}}</option>
            </select></label>
            <article v-if="finding" class="finding-detail">
              <strong :class="{'guardian-error':finding.severity==='error'}">{{ finding.detail }}</strong>
              <p>{{ finding.code }}<template v-if="finding.start_ms!==undefined"> · {{time(finding.start_ms)}}</template></p>
              <dl v-if="finding.evidence" class="evidence-values">
                <template v-for="(value,key) in finding.evidence" :key="key">
                  <template v-if="key!=='fields'"><dt>{{ evidenceLabels[key] || key }}</dt><dd>{{ displayValue(value) }}</dd></template>
                </template>
              </dl>
              <table v-if="changedFields" class="state-comparison">
                <thead><tr><th scope="col">状态</th><th scope="col">前镜收尾</th><th scope="col">当前开场</th></tr></thead>
                <tbody><tr v-for="(difference,key) in changedFields" :key="key">
                  <th scope="row">{{evidenceLabels[key] || key}}</th><td>{{displayValue(difference.expected)}}</td><td>{{displayValue(difference.observed)}}</td>
                </tr></tbody>
              </table>
            </article>
            <template v-if="shot">
              <label v-if="activeCandidates.length">生成候选<select :value="candidate?.id" @change="candidateId=($event.target as HTMLSelectElement).value">
                <option v-for="item in activeCandidates" :key="item.id" :value="item.id">{{item.parameters.preset}} · {{item.id.slice(0,8)}}</option>
              </select></label>
              <div v-if="candidate && evidenceFrames.length" class="evidence-grid">
                <figure><img :src="`/api/assets/${candidate.asset_id}/media`" alt="锁定运镜源图"><figcaption>锁定源图</figcaption></figure>
                <figure v-for="frame in evidenceFrames" :id="`guardian-evidence-${candidate.id}-${frame.index}`" :key="frame.index"
                  :class="{'evidence-active':focusedFrame===`guardian-evidence-${candidate.id}-${frame.index}`}" tabindex="-1">
                  <img :src="`/api/generation/candidates/${candidate.id}/guardian-frames/${frame.index}`" :alt="`候选 ${time(frame.time_ms)}`">
                  <figcaption>{{time(frame.time_ms)}}</figcaption>
                </figure>
              </div>
              <VisualCandidateCheck v-if="candidate?.status==='succeeded'" :report="candidate.output.guardian_visual" @evidence="focusEvidence" />
              <ScreenTextCheck v-if="candidate?.output.guardian_screen_text" :report="candidate.output.guardian_screen_text" @evidence="focusEvidence" />
              <GuardianReferenceCompare v-if="candidate?.status==='succeeded'" :key="candidate.id"
                :candidate-id="candidate.id" :frames="evidenceFrames" :saved="candidate.output.guardian_review?.comparison"
                :saved-checklist="candidate.output.guardian_review?.checklist" @seek="focusEvidence" />
              <p v-if="candidate?.output.guardian_review">{{ candidate.output.guardian_review.request.decision==='approved'?'人工通过':'人工退回' }} · {{candidate.output.guardian_review.request.note}}</p>
              <p v-else-if="candidate?.status==='succeeded'">候选待人工内容审核。</p>
              <p v-else-if="candidate" role="status">{{statusLabels[candidate.status] || candidate.status}} · {{Math.round(candidate.progress)}}%</p>
              <p v-else class="guardian-muted">此合同暂无已验证候选证据。</p>
              <p v-if="candidate?.rework">返工原因 · {{candidate.rework.reason}}</p>
              <p v-if="candidate?.error || candidateFailure" class="guardian-error" role="alert">{{candidate?.error || candidateFailure}}</p>
              <template v-if="report.approved && shot.guardian && shot.strategy==='still_motion'">
                <RouterLink :to="link('generation',{plan:version.version_id,shot:shot.shot_id,asset:candidate?.asset_id || Object.keys(shot.guardian.source_images)[0],candidate:candidate?.id})">打开生成与候选审核</RouterLink>
                <GuardianShotRework v-if="activeApproval" :key="shot.shot_id" :project-id="workbench.projectId" :series-version-id="version.version_id"
                  :shot-id="shot.shot_id" :frames="shotFrames" :source-ids="Object.keys(shot.guardian.source_images)"
                  :candidate-id="applicableCandidate" :candidate-aspect="candidate?.parameters.aspect" @queued="queuedRework" />
                <p v-else class="guardian-muted">请切换至当前批准版本后提交返工。</p>
              </template>
            </template>
            <p v-else-if="!finding" class="guardian-muted">请选择分集或镜头以查看证据。</p>
          </section>

          <aside class="guardian-panel lock-panel">
            <h2>版本检查器</h2>
            <dl class="evidence-values">
              <dt>故事圣经</dt><dd>{{version.title}} · v{{version.version}}</dd>
              <dt>风格锁</dt><dd>{{report.guardian.style}}</dd>
              <template v-if="shot">
                <dt>镜头合同</dt><dd><code>{{shot.guardian?.contract_sha256 || '待锁定'}}</code></dd>
                <dt v-if="shot.guardian">画面约束</dt><dd v-if="shot.guardian">{{shot.guardian.visual}}</dd>
                <template v-if="shot.guardian?.screen_text">
                  <dt>固定文字语言</dt><dd>{{shot.guardian.screen_text.language}}</dd>
                  <dt v-if="shot.guardian.screen_text.required.length">必现文字</dt><dd v-if="shot.guardian.screen_text.required.length">{{shot.guardian.screen_text.required.join('、')}}</dd>
                  <dt v-if="shot.guardian.screen_text.forbidden.length">禁现文字</dt><dd v-if="shot.guardian.screen_text.forbidden.length">{{shot.guardian.screen_text.forbidden.join('、')}}</dd>
                </template>
                <dt>场景版本</dt><dd>{{shot.scene_version_id || '待锁定'}}</dd>
                <dt>角色版本</dt><dd v-for="key in shot.character_version_ids" :key="key">{{key}}</dd>
                <dt v-if="candidate">实际外部费用</dt><dd v-if="candidate">{{candidate.output.actual_external_cost_micros===0?'¥0':'未知'}}</dd>
              </template>
            </dl>
            <RouterLink v-if="episode" :to="link('storyboard',{version:episode.storyboard_version_id,shot:shot?.shot_id})">打开固定分镜</RouterLink>
          </aside>
        </div>
        <section v-if="history.length>1" class="guardian-panel impact-panel">
          <h2><GitCompareArrows :size="18" aria-hidden="true" /> 版本影响分析</h2>
          <form class="compare-form" @submit.prevent="compare">
            <label>对比基线<select v-model="baseline" required><option value="">选择同一故事圣经历史版本</option>
              <option v-for="item in history.filter(item=>item.version_id!==version?.version_id)" :key="item.version_id" :value="item.version_id">v{{item.version}}</option>
            </select></label>
            <button type="submit" :disabled="!baseline || comparing">{{ comparing?'正在比较…':'比较镜头合同' }}</button>
          </form>
          <p v-if="impactFailure" role="alert" class="guardian-error">{{impactFailure}}</p>
          <ul v-if="changes" class="impact-list"><li v-for="change in changes" :key="change.shot_id">
            {{change.shot_id}} · {{kinds[change.kind]}}
            <button v-if="change.after && change.kind!=='unchanged'" type="button" @click="locateImpact(change)">定位镜头 {{change.shot_id}}</button>
          </li></ul>
        </section>
      </template>
    </template>
  </div>
</template>

<style scoped>
.guardian-start { display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.1fr);gap:18px;align-items:start }
.guardian-start h2 { margin-top:0 }
.guardian-start ol { margin:0;padding-inline-start:24px }
.guardian-start li { padding:6px 0 }
.guardian-start small { display:block;color:var(--ink-muted);margin-top:3px }
@media(max-width:730px) { .guardian-start { grid-template-columns:minmax(0,1fr) } }
.guardian-workbench { --gb:var(--surface-base);--gp:var(--surface-panel);--ga:var(--accent-surface);--gl:var(--line);--gt:var(--ink);--gm:var(--ink-muted);--gx:var(--accent);--ge:var(--negative);color:var(--gt) }
.guardian-toolbar,.compare-form { display:flex;flex-wrap:wrap;align-items:end;gap:12px;margin-bottom:14px }
.guardian-workbench h2 { display:flex; align-items:center; gap:8px; margin:0 0 8px; color:var(--gt) }
.guardian-muted,.guardian-workbench small { color:var(--gm);margin:0 }
.guardian-workbench a { color:var(--gx); display:block; padding:7px 0; overflow-wrap:anywhere }
.guardian-workbench label { color:var(--gm); min-width:0 }
.guardian-workbench button,.guardian-workbench select { appearance:none; border:1px solid var(--gl); background-color:var(--gp); color:var(--gt); max-width:100%; transition:none }
.guardian-workbench select { padding-right:28px; background-image:linear-gradient(45deg,transparent 50%,var(--gm) 50%),linear-gradient(135deg,var(--gm) 50%,transparent 50%); background-position:right 15px center,right 10px center; background-size:5px 5px; background-repeat:no-repeat }
.guardian-workbench button { display:inline-flex; align-items:center; gap:8px }
.guardian-workbench button[aria-pressed=true],.guardian-workbench button:hover:not(:disabled) { background:var(--ga); border-color:var(--gx); color:var(--gx) }
.guardian-metrics { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:10px; margin:0 0 14px }
.guardian-metrics div,.guardian-workbench .guardian-panel { padding:16px;border:1px solid var(--gl);background:var(--gp);border-radius:14px;min-width:0;margin:0;box-shadow:var(--shadow) }
.guardian-metrics dt { color:var(--gm); font-size:12px }
.guardian-metrics dd { font-size:21px; margin:4px 0 0; font-weight:700 }
.guardian-layout { display:grid; grid-template-columns:minmax(170px,1fr) minmax(250px,2.1fr) minmax(180px,1fr); gap:12px; align-items:start }
.issue-panel button { width:100%; justify-content:space-between; margin-bottom:6px; text-align:left }
.issue-panel button span { overflow-wrap:anywhere }
.guardian-issues { border-top:1px solid var(--gl); padding-top:9px; margin-top:8px }
.guardian-issues button { justify-content:start }
.guardian-issues svg { flex:none }
.guardian-issues small { display:block }
.evidence-panel select { margin-bottom:8px }
.evidence-grid figure:is(:focus,.evidence-active) { outline:2px solid var(--accent);outline-offset:2px }
.guardian-error { color:var(--ge) }
.finding-detail { background:var(--gb); border:1px solid var(--gl); border-radius:10px; padding:10px; margin-bottom:10px; overflow-wrap:anywhere }
.evidence-values { display:grid; gap:5px; margin:8px 0; overflow-wrap:anywhere }
.evidence-values dt { color:var(--gm); font-size:12px }
.evidence-values dd { margin:0 0 4px; white-space:pre-wrap }
.state-comparison { width:100%; table-layout:fixed; border-collapse:collapse; text-align:left }
.state-comparison :is(th,td) { padding:6px; border-top:1px solid var(--gl); overflow-wrap:anywhere }
.state-comparison thead th { font-size:12px; color:var(--gm) }
.evidence-grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(80px,1fr)); gap:6px }
.evidence-grid figure { margin:0; min-width:0 }
.evidence-grid img { display:block; width:100%; aspect-ratio:1.3; object-fit:contain; background:var(--gb); border:1px solid var(--gl); border-radius:8px }
.evidence-grid figcaption { font-size:11px; color:var(--gm) }
.guardian-workbench .impact-panel { margin-top:12px }
.impact-list { max-height:230px; overflow:auto }
@media(max-width:1250px) { .guardian-layout { grid-template-columns:minmax(150px,1fr) minmax(220px,1.8fr) } .lock-panel { grid-column:2 } }
@media(max-width:760px) { .guardian-layout { grid-template-columns:minmax(0,1fr) } .lock-panel { grid-column:auto } .guardian-metrics { grid-template-columns:repeat(2,minmax(0,1fr)) } }
</style>
