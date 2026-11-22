<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { request, statusLabels } from './analysisApi'
import VisualCandidateCheck, { type VisualEvidence, type VisualReport } from './components/production/VisualCandidateCheck.vue'

type Preset = 'push_in'|'pull_out'|'pan_right'
interface Candidate {
  id:string; asset_id:string; status:string; stage:string; progress:number; error:string|null
  story_version_id:string|null
  cancel_requested:boolean; selected_asset_id:string|null; parameters:{preset:Preset;shot_id:string|null}
  guardian?:{contract_sha256:string}|null
  output:{duration?:number; width?:number; height?:number; reused_from_task_id?:string;
    guardian_frames?:{index:number;time_ms:number}[];
    guardian_visual?:VisualReport;
    guardian_review?:{request:{decision:'approved'|'rejected';note:string;category:string|null};evidence:{time_ms:number}|null}}
}
const props=defineProps<{projectId:string;assets:{id:string;name:string}[];initialPlan?:string;initialShot?:string;initialAsset?:string;initialCandidate?:string}>()
const emit=defineEmits<{assetsChanged:[]}>()
const images=computed(()=>props.assets.filter(item=>/\.(png|jpe?g|webp)$/i.test(item.name)))
const candidates=ref<Candidate[]>([]), assetId=ref(props.initialAsset||''), preview=ref(''), plan=ref(props.initialPlan||''), shot=ref(props.initialShot||'')
const aspect=ref('portrait'), frames=ref(72), presets=ref<Preset[]>(['push_in','pan_right'])
const labels:Record<Preset,string>={push_in:'推进',pull_out:'拉远',pan_right:'向右横移'}
const title=ref(''), review=ref(''), notice=ref(''), error=ref(''), busy=ref(false)
const verdict=ref<'approved'|'rejected'>('approved'), category=ref(''), evidenceIndex=ref<number|null>(null), reviewNote=ref('')
const categories={identity:'角色身份',wardrobe:'服装',prop:'道具',scene:'场景',continuity:'连续性',shot_mismatch:'画面与分镜不符',technical:'技术缺陷',other:'其他'}
const modeList=ref<{id:string; available:boolean; label:string}[]>([])
const compareId=ref('')
const player=ref<HTMLVideoElement|null>(null), markedEvidence=ref<number|null>(null)
const keys=new Map<string,string>()
let timer:ReturnType<typeof setInterval>|undefined
let refreshing=false
const base=`/generation/projects/${props.projectId}`
const selected=computed(()=>candidates.value.find(item=>item.id===preview.value))
const evidenceFrames=computed(()=>(selected.value?.output.guardian_frames || []).slice().sort((a,b)=>a.time_ms-b.time_ms))
const visualBlocked=computed(()=>selected.value?.output.guardian_visual?.status==='blocked')

async function run(action:()=>Promise<void>){
  busy.value=true
  error.value=''
  notice.value=''
  try{await action()}catch(failure){error.value=String(failure)}finally{busy.value=false}
}
async function refresh(){
  if(!props.projectId || refreshing)return
  refreshing=true
  try{candidates.value=await request<Candidate[]>(base+'/candidates')}finally{refreshing=false}
}
async function submit(){
  await run(async()=>{
    const body={asset_id:assetId.value,story_version_id:plan.value.trim()||null,shot_id:shot.value.trim()||null,
      candidates:presets.value.map(preset=>({preset,aspect:aspect.value,frames:frames.value}))}
    const signature=JSON.stringify(body)
    if(!keys.has(signature))keys.set(signature,crypto.randomUUID())
    const created=await request<Candidate[]>(base+'/still-motion',{...body,idempotency_key:keys.get(signature)})
    keys.delete(signature)
    await refresh()
    notice.value=`已排队 ${created.length} 个本地候选`
  })
}
function open(candidate:Candidate){
  preview.value=candidate.id
  title.value=(props.assets.find(asset=>asset.id===candidate.asset_id)?.name.split('.').slice(0,-1).join('.') || '静图')+' · '+labels[candidate.parameters.preset]
  review.value=''
  reviewNote.value=''
  verdict.value='approved'
  category.value=''
  evidenceIndex.value=null
  markedEvidence.value=null
  if (candidate.output.guardian_visual?.status==='blocked') markBlocked(candidate.output.guardian_visual)
}
function markBlocked(report:VisualReport) {
  verdict.value='rejected'
  category.value='technical'
  evidenceIndex.value=report.findings[0]?.evidence.index ?? null
}
watch(visualBlocked, blocked=>{
  const report=selected.value?.output.guardian_visual
  if (blocked && report) markBlocked(report)
})
function seekEvidence(frame:VisualEvidence) {
  markedEvidence.value=frame.index
  const media=player.value
  if (!media) return
  const seek=()=>{media.currentTime=frame.time_ms/1000}
  if (media.readyState) seek()
  else media.addEventListener('loadedmetadata',seek,{once:true})
}
async function reviewContent(){
  const item=selected.value
  if(!item?.guardian)return
  await run(async()=>{
    const rejected=verdict.value==='rejected'
    await request(`/generation/candidates/${item.id}/guardian-review`,{
      decision:verdict.value,note:reviewNote.value,category:rejected?category.value:null,frame:rejected?evidenceIndex.value:null,
    })
    await refresh()
    notice.value=rejected?'候选已退回，证据已保存':'内容审核已保存，可以采纳'
  })
}
async function accept(){
  const item=selected.value
  if(!item)return
  await run(async()=>{
    const asset=await request<{name:string}>('/generation/candidates/'+item.id+'/select',{title:title.value,note:review.value})
    await refresh()
    emit('assetsChanged')
    notice.value=`已采纳 ${asset.name}，可在智能二创中选择`
  })
}
async function taskAction(candidate:Candidate,action:'retry'|'cancel'){
  await run(async()=>{
    await request(`/tasks/${candidate.id}/${action}`,{})
    await refresh()
  })
}
onMounted(()=>{
  void run(async()=>{
    modeList.value=(await request<{modes:typeof modeList.value}>('/generation/capabilities')).modes
    if (plan.value && shot.value) {
      const result=await request<{episodes:{shots:{shot_id:string;start_ms:number;duration_ms:number}[]}[]}>(`/series/versions/${plan.value}/continuity`)
      const fixed=result.episodes.flatMap(episode=>episode.shots).find(item=>item.shot_id===shot.value)
      if (fixed)frames.value=Math.round((fixed.start_ms+fixed.duration_ms)*24/1000)-Math.round(fixed.start_ms*24/1000)
    }
    await refresh()
    const linked=candidates.value.find(item=>item.id===props.initialCandidate && item.parameters.shot_id===shot.value)
    const match=linked || candidates.value.find(item=>item.parameters.shot_id===shot.value && item.story_version_id===plan.value
      && item.status==='succeeded' && (!assetId.value || item.asset_id===assetId.value))
    if (match)open(match)
  })
  timer=setInterval(()=>{if(!busy.value)void refresh().catch(failure=>{error.value=String(failure)})},3000)
})
onUnmounted(()=>clearInterval(timer))
</script>

<template>
  <p v-if="!projectId" class="empty">选择项目以制作素材候选。</p>
  <div v-else class="generation-workbench">
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="generation-desk">
      <section>
        <h2>本地静图运镜</h2>
        <p class="hint">本机 CPU 输出 24 fps 的无声 MP4，外部调用费用 ¥0。<span v-if="modeList.length">{{ modeList.filter(mode=>!mode.available).map(mode=>mode.label).join('、') }}待接入。</span></p>
        <form class="create" @submit.prevent="submit">
          <label>参考图片<select v-model="assetId" required>
            <option value="">选择项目授权图片</option><option v-for="asset in images" :key="asset.id" :value="asset.id">{{ asset.name }}</option>
          </select></label>
          <div class="editor-grid">
            <label>画幅<select v-model="aspect"><option value="portrait">9:16</option><option value="landscape">16:9</option><option value="square">1:1</option></select></label>
            <label>成片帧数<input v-model.number="frames" required type="number" min="12" max="240"></label>
          </div>
          <p class="hint">时长 {{ (frames/24).toFixed(2) }} 秒。画面居中裁剪至目标画幅。</p>
          <fieldset>
            <legend>候选运镜</legend>
            <label v-for="(label,key) in labels" :key="key" class="check"><input v-model="presets" :value="key" type="checkbox">{{ label }}</label>
          </fieldset>
          <details :open="!!initialPlan">
            <summary>固定已批准镜头</summary>
            <label>制作计划版本 ID<input v-model="plan" maxlength="36"></label>
            <label>稳定镜头 ID<input v-model="shot" maxlength="48"></label>
          </details>
          <button class="primary" :disabled="busy || !assetId || !presets.length">{{ busy ? '处理中' : '提交运镜候选' }}</button>
        </form>
      </section>
      <section>
        <h2>候选对比与采纳</h2>
        <div v-if="selected?.status==='succeeded'" class="candidate-monitors" :class="{comparing:compareId && compareId!==selected.id}">
          <video ref="player" :key="selected.id" controls preload="metadata" :src="`/api/generation/candidates/${selected.id}/video`" aria-label="当前候选"></video>
          <video v-if="compareId && compareId!==selected.id" :key="compareId" controls preload="metadata" :src="`/api/generation/candidates/${compareId}/video`" aria-label="对比候选"></video>
        </div>
        <figure v-else-if="assetId" class="generation-reference"><img :src="`/api/assets/${assetId}/media`" alt="运镜参考图"><figcaption>输入参考图</figcaption></figure>
        <p v-else class="empty">从记录中选择已验证候选。</p>
        <label v-if="selected && candidates.some(candidate=>candidate.id!==selected?.id && candidate.status==='succeeded')" class="compare-control">A/B 对比候选<select v-model="compareId">
          <option value="">仅预览当前候选</option><option v-for="item in candidates.filter(candidate=>candidate.id!==selected?.id && candidate.status==='succeeded')" :key="item.id" :value="item.id">{{labels[item.parameters.preset]}} · {{item.id.slice(0,8)}}</option>
        </select></label>
        <p v-if="selected?.selected_asset_id">已采纳为项目素材。</p>
        <template v-if="selected?.status==='succeeded' && selected.guardian">
          <div class="candidate-evidence">
            <figure><img :src="`/api/assets/${selected.asset_id}/media`" alt="批准源图"><figcaption>批准源图</figcaption></figure>
            <figure v-for="frame in evidenceFrames" :key="frame.index" :class="{'marked-evidence':markedEvidence===frame.index}">
              <img :src="`/api/generation/candidates/${selected.id}/guardian-frames/${frame.index}`" :alt="`证据帧 ${frame.time_ms} 毫秒`">
              <figcaption>{{(frame.time_ms/1000).toFixed(3)}} 秒</figcaption>
            </figure>
          </div>
          <VisualCandidateCheck :report="selected.output.guardian_visual" @evidence="seekEvidence" />
          <p v-if="selected.output.guardian_review">{{selected.output.guardian_review.request.decision==='approved'?'人工内容审核通过':'候选已退回'}} · {{selected.output.guardian_review.request.note}}</p>
          <form v-else class="create content-review" @submit.prevent="reviewContent">
            <label>内容审核决定<select v-model="verdict"><option value="approved" :disabled="visualBlocked">通过</option><option value="rejected">退回</option></select></label>
            <template v-if="verdict==='rejected'">
              <label>问题类别<select v-model="category" required><option value="">选择问题类别</option>
                <option v-for="(label,key) in categories" :key="key" :value="key">{{label}}</option>
              </select></label>
              <label>问题证据帧<select v-model="evidenceIndex" required><option :value="null" disabled>选择时间点</option>
                <option v-for="frame in evidenceFrames" :key="frame.index" :value="frame.index">{{(frame.time_ms/1000).toFixed(3)}} 秒</option>
              </select></label>
            </template>
            <label>内容审核说明<textarea v-model="reviewNote" required maxlength="2000"></textarea></label>
            <button :disabled="busy || !reviewNote.trim() || (visualBlocked && verdict==='approved') || (verdict==='rejected' && (!category || evidenceIndex===null))">保存内容审核</button>
          </form>
        </template>
        <form v-if="!selected?.selected_asset_id && selected?.status==='succeeded' && (!selected.guardian || selected.output.guardian_review?.request.decision==='approved')" class="create" @submit.prevent="accept">
          <label>素材标题<input v-model="title" required maxlength="200"></label>
          <label>采纳说明<textarea v-model="review" required maxlength="2000"></textarea></label>
          <button class="primary" :disabled="busy || !title.trim() || !review.trim()">采纳为视频素材</button>
        </form>
      </section>
      <section class="generation-checks">
        <h2>生成前检查</h2>
        <dl class="inspector-facts">
          <div><dt>制作方式</dt><dd>本机 FFmpeg</dd></div>
          <div><dt>参考图</dt><dd>{{images.find(item=>item.id===assetId)?.name || '待选择'}}</dd></div>
          <div><dt>计划版本</dt><dd>{{plan || '独立候选'}}</dd></div>
          <div><dt>目标镜头</dt><dd>{{shot || '待关联'}}</dd></div>
          <div><dt>外部调用费用</dt><dd>¥0.00</dd></div>
        </dl>
        <RouterLink :to="{name:'models',query:{project:projectId}}">查看模型与预算</RouterLink>
      </section>
    </div>
    <section>
      <div class="actions"><h2>候选记录</h2><button :disabled="busy" @click="run(refresh)">刷新候选</button></div>
      <p v-if="!candidates.length" class="hint">暂无候选。</p>
      <article v-for="item in candidates" :key="item.id" class="task">
        <div>
          <strong>{{ labels[item.parameters.preset] }} · {{ assets.find(asset=>asset.id===item.asset_id)?.name }}</strong>
          <p v-if="item.parameters.shot_id" class="mono">{{ item.parameters.shot_id }}</p>
          <p>{{ statusLabels[item.status] || item.status }} · {{ statusLabels[item.stage] || item.stage }}</p>
          <p v-if="item.output.guardian_visual?.status==='blocked'" class="error">技术检查阻断</p>
          <p v-if="item.status==='succeeded'">{{ item.output.width }} × {{ item.output.height }} · {{ item.output.duration?.toFixed(2) }} 秒<span v-if="item.output.reused_from_task_id"> · 已核验复用</span></p>
          <p v-if="item.error" class="error">{{ item.error }}</p>
        </div>
        <button v-if="item.status==='succeeded'" :aria-pressed="preview===item.id" @click="open(item)">预览{{ labels[item.parameters.preset] }}</button>
        <button v-if="['queued','running'].includes(item.status)" :disabled="busy || item.cancel_requested" @click="taskAction(item,'cancel')">取消</button>
        <button v-if="['failed','cancelled'].includes(item.status)" :disabled="busy" @click="taskAction(item,'retry')">重试</button>
      </article>
    </section>
  </div>
</template>

<style scoped>
.generation-workbench { display:grid; gap:18px }
.generation-desk { display:grid;grid-template-columns:minmax(210px,.95fr) minmax(250px,2fr) minmax(165px,.82fr);gap:14px;align-items:start }
.candidate-monitors { display:grid;grid-template-columns:minmax(0,1fr);gap:8px }
.candidate-monitors.comparing { grid-template-columns:repeat(2,minmax(0,1fr)) }
.compare-control { margin:10px 0 }
.generation-workbench fieldset,.generation-workbench details { margin:0 }
.generation-reference { margin:0 0 10px; position:relative; background:var(--surface-raised); border-radius:8px; overflow:hidden }
.generation-reference img { width:100%; max-height:320px; object-fit:contain; display:block }
.generation-reference figcaption { padding:8px 10px; color:var(--ink-muted) }
.candidate-evidence { display:grid; grid-template-columns:repeat(auto-fit,minmax(95px,1fr)); gap:8px; margin:12px 0 }
.candidate-evidence figure { margin:0; min-width:0 }
.candidate-evidence img { width:100%; aspect-ratio:1.25; object-fit:contain; background:var(--surface-base); border-radius:6px }
.candidate-evidence figcaption { color:var(--ink-muted); font-size:12px }
.candidate-evidence .marked-evidence img { outline:2px solid var(--accent);outline-offset:-2px }
@media(max-width:1050px) { .generation-desk { grid-template-columns:minmax(200px,.95fr) minmax(250px,2fr) } .generation-checks { grid-column:1/-1 } }
@media(max-width:700px) { .generation-desk,.candidate-monitors.comparing { grid-template-columns:minmax(0,1fr) } }
</style>
