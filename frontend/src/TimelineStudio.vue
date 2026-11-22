<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { Film, Image, Layers3, MonitorPlay } from 'lucide-vue-next'
import { clock, request, statusLabels } from './analysisApi'
import { moveStart, trimBoundary, type EditEdge } from './timelineGestures'

type Role='main'|'overlay'|'dialogue'|'music'|'sfx'|'caption'
type Profile='portrait'|'landscape'|'square'
interface Clip {
  id:string; asset_id:string; at:number; source_in:number; frames:number
  still_motion:'none'|'push_in'; fade_in:number; fade_out:number
}
interface Track { id:string;role:Role;enabled:boolean;locked:boolean;volume:number;clips:Clip[] }
interface Timeline {
  source_version_id:string|null;frame_rate:24;profile:Profile;frames:number;tracks:Track[]
}
interface Version {id:string;version_id:string;title:string;version:number;current_version:number;content:Timeline|null}
interface Job {
  id:string;status:string;stage:string;progress:number;error:string|null;story_version_id:string;cancel_requested:boolean
  output:{frames?:number;duration?:number;has_audio?:boolean;sha256?:string}
}
const props=defineProps<{projectId:string;assets:{id:string;name:string}[];initialVersion?:string;initialClip?:string;canReturn?:boolean}>()
const emit=defineEmits<{returnToProduction:[]}>()
const labels:Record<Role,string>={main:'主画面',overlay:'叠画',dialogue:'对白',music:'音乐',sfx:'音效',caption:'字幕'}
const profiles:Record<Profile,string>={portrait:'9:16',landscape:'16:9',square:'1:1'}
const stack=ref<Version[]>([]), editions=ref<Version[]>([]), active=ref<Version|null>(null), jobs=ref<Job[]>([])
const title=ref(''), message=ref(''), error=ref(''), saved=ref(''), busy=ref(false)
const trackRole=ref<Role>('overlay'), currentClip=ref(''), preview=ref('')
const snap=ref(true)
const workbench=ref<HTMLDivElement|null>(null)
const sourceMonitor=ref<HTMLMediaElement|null>(null)
const sourceError=ref(false)
const browserPreview=ref(''), assetSearch=ref('')
const planVersion=ref(''), planEpisode=ref(1), autoTitle=ref('')
const keys=new Map<string,string>()
const entityPath=`/projects/${props.projectId}/story/entities`
const base=`/timeline/projects/${props.projectId}`
let timer:ReturnType<typeof setInterval>|undefined
function track(role:Role):Track {return {id:crypto.randomUUID(),role,enabled:true,locked:false,volume:1,clips:[]}}
const freshContent=():Timeline=>({frame_rate:24,profile:'portrait',frames:72,source_version_id:null,tracks:[track('main')]})
const timeline=reactive(freshContent())
let gesture: { pointer: number; x: number; width: number; lane: Track; clip: Clip; before: Clip; edge: EditEdge } | null = null
const dirty=computed(()=>JSON.stringify([title.value,timeline])!==saved.value)
const selection=computed(()=>{
  for(const lane of timeline.tracks){
    const clip=lane.clips.find(item=>item.id===currentClip.value)
    if(clip)return {lane,clip}
  }
  return null
})
const activeAsset = computed(() => props.assets.find(asset => asset.id === (browserPreview.value || selection.value?.clip.asset_id)))
const visibleAssets = computed(()=>props.assets.filter(asset=>/\.(png|jpe?g|webp|mp4|mov|mkv|webm|avi|wav|mp3)$/i.test(asset.name)
  && asset.name.toLocaleLowerCase().includes(assetSearch.value.trim().toLocaleLowerCase())).slice(0,24))
const activeMedia = computed(() => {
  const asset = activeAsset.value
  if (!asset) return undefined
  const name = asset.name
  const tag = /\.(png|jpe?g|webp)$/i.test(name) ? 'img' : /\.(wav|mp3)$/i.test(name) ? 'audio' :
    /\.(mp4|mov|mkv|webm|avi)$/i.test(name) ? 'video' : undefined
  return tag ? { tag, url:`/api/assets/${asset.id}/media`, name } : undefined
})
const clipCount = computed(() => timeline.tracks.reduce((count,lane) => count+lane.clips.length,0))
const ticks = computed(() => Array.from({length:5},(_,i) => clock(Math.round(i*Math.max(0,timeline.frames)/4/24*1e6))))
function cueSource() {
  const media = sourceMonitor.value
  if (media && selection.value && !browserPreview.value && Number.isFinite(media.duration)) {
    media.currentTime = Math.min(selection.value.clip.source_in/24,media.duration)
  }
}
watch(() => activeAsset.value?.id, () => { sourceError.value = false })
watch(currentClip,()=>{ browserPreview.value='' })
watch(() => selection.value?.clip.source_in, cueSource)
function possible(lane:Track){
  const visual=lane.role==='main'||lane.role==='overlay'
  const ext=lane.role==='caption'?/\.srt$/i:visual?/\.(mp4|mov|mkv|webm|avi|png|jpe?g|webp)$/i:/\.(mp4|mov|mkv|webm|avi|wav|mp3)$/i
  return props.assets.filter(asset=>ext.test(asset.name))
}
function name(assetId:string){return props.assets.find(item=>item.id===assetId)?.name||'待选素材'}
function trimOrMove(lane: Track, clip: Clip, before: Clip, edge: EditEdge, delta: number, tolerance: number) {
  const markers=[0,timeline.frames,...timeline.tracks.filter(track=>track.enabled).flatMap(track=>
    track.clips.filter(item=>item.id!==clip.id).flatMap(item=>[item.at,item.at+item.frames]))]
  if(edge==='move') {
    clip.at=moveStart(before.at+delta,before,timeline.frames,lane.clips.filter(item=>item.id!==clip.id),markers,tolerance)
    return
  }
  const end=before.at+before.frames
  if(edge==='start') {
    clip.at=trimBoundary(before.at+delta,before.at,end-1,markers,tolerance)
    clip.frames=end-clip.at
    const still=/\.(png|jpe?g|webp)$/i.test(name(clip.asset_id))
    clip.source_in=still ? 0 : before.source_in+clip.at-before.at
  } else {
    clip.frames=trimBoundary(end+delta,before.at+1,end,markers,tolerance)-before.at
  }
  clip.fade_in=Math.min(before.fade_in,clip.frames)
  clip.fade_out=Math.min(before.fade_out,clip.frames-clip.fade_in)
}
function beginGesture(event: PointerEvent, lane: Track, clip: Clip, edge: EditEdge) {
  if(event.button!==0 || gesture)return
  currentClip.value=clip.id
  if(lane.locked || busy.value || !Number.isInteger(clip.at) || !Number.isInteger(clip.frames) || clip.frames<1)return
  const button=event.currentTarget as HTMLButtonElement
  const width=button.parentElement!.getBoundingClientRect().width
  if(width<=0)return
  event.preventDefault()
  button.focus({preventScroll:true})
  button.setPointerCapture(event.pointerId)
  gesture={pointer:event.pointerId,x:event.clientX,width,lane,clip,before:{...clip},edge}
}
function dragClip(event: PointerEvent) {
  if(!gesture || gesture.pointer!==event.pointerId)return
  const {x,width,lane,clip,before,edge}=gesture
  const distance=event.clientX-x
  if(Math.abs(distance)<3) {
    Object.assign(clip,before)
    return
  }
  const framesPerPixel=timeline.frames/width
  trimOrMove(lane,clip,before,edge,Math.round(distance*framesPerPixel),snap.value&&!event.altKey ? Math.max(1,Math.round(8*framesPerPixel)) : 0)
}
function endGesture(event: PointerEvent, cancel=false) {
  if(!gesture || gesture.pointer!==event.pointerId)return
  if(cancel)Object.assign(gesture.clip,gesture.before)
  gesture=null
}
function clipKeys(event: KeyboardEvent, lane: Track, clip: Clip, edge: EditEdge) {
  if(event.key==='Escape' && gesture) {
    Object.assign(gesture.clip,gesture.before)
    gesture=null
    event.preventDefault()
    return
  }
  if(lane.locked || busy.value || gesture || !['ArrowLeft','ArrowRight'].includes(event.key))return
  event.preventDefault()
  currentClip.value=clip.id
  trimOrMove(lane,clip,{...clip},edge,(event.key==='ArrowLeft' ? -1 : 1)*(event.shiftKey ? 10 : 1),0)
}
function requestKey(body:object){
  const signature=JSON.stringify(body)
  if(!keys.has(signature))keys.set(signature,crypto.randomUUID())
  return keys.get(signature)!
}
async function run(action:()=>Promise<void>){
  busy.value=true
  error.value=''
  message.value=''
  try{await action()}catch(failure){error.value=String(failure)}finally{busy.value=false}
}
async function refresh(){
  if(!props.projectId)return
  jobs.value=await request<Job[]>(base+'/renders')
}
async function list(){
  if(!props.projectId)return
  stack.value=(await request<{items:Version[]}>(entityPath+'?kind=timeline')).items
}
async function open(item:Version){
  const version= item.content?item:await request<Version>('/story/versions/'+item.version_id)
  active.value=version
  title.value=version.title
  Object.assign(timeline,version.content)
  saved.value=JSON.stringify([title.value,timeline])
  editions.value=await request<Version[]>('/story/entities/'+version.id+'/versions')
  currentClip.value=''
}
function fresh(){
  Object.assign(timeline,freshContent())
  active.value=null
  editions.value=[]
  title.value=''
  currentClip.value=''
  saved.value=''
}
function addClip(lane:Track){
  const at=Math.max(0,...lane.clips.map(item=>item.at+item.frames))
  if(at>=timeline.frames)return
  const item:Clip={id:crypto.randomUUID(),asset_id:'',at,source_in:0,frames:timeline.frames-at,
    still_motion:'none',fade_in:0,fade_out:0}
  lane.clips.push(item)
  currentClip.value=item.id
}
function moveTrack(index:number,direction:number){
  const newIndex=index+direction
  if(newIndex<0||newIndex>=timeline.tracks.length)return
  const [moved]=timeline.tracks.splice(index,1)
  timeline.tracks.splice(newIndex,0,moved)
}
async function save(){
  await run(async()=>{
    const editing=active.value
    const body={title:title.value,content:timeline,...(editing?{expected_version:editing.current_version}:{kind:'timeline'})}
    const next=await request<Version>(editing?'/story/entities/'+editing.id+'/versions':entityPath,
      {...body,idempotency_key:requestKey(body)})
    await list()
    await open(next)
    message.value=`时间轴 v${next.version} 已保存`
  })
}
async function restore(){
  const version=active.value
  if(!version)return
  await run(async()=>{
    const body={version:version.version,expected_version:version.current_version}
    const result=await request<Version>('/story/entities/'+version.id+'/restore',{...body,idempotency_key:requestKey({...body,id:version.id})})
    await list()
    await open(result)
    message.value=`已追加恢复时间轴 v${result.version}`
  })
}
async function assemble(){
  await run(async()=>{
    const body={series_version_id:planVersion.value.trim(),episode:planEpisode.value,title:autoTitle.value,profile:timeline.profile}
    const result=await request<Version>(base+'/assemble',{...body,idempotency_key:requestKey(body)})
    await list()
    await open(result)
    message.value='已按固定分镜和采纳候选装配时间轴'
  })
}
async function render(){
  const version=active.value
  if(!version || dirty.value)return
  await run(async()=>{
    const body={version_id:version.version_id}
    await request(base+'/renders',{...body,idempotency_key:requestKey(body)})
    await refresh()
    message.value='已提交固定版本多轨渲染'
  })
}
async function control(job:Job,action:'cancel'|'retry'){
  await run(async()=>{await request('/tasks/'+job.id+'/'+action,{}); await refresh()})
}
onMounted(()=>{
  void run(async()=>{
    await list()
    await refresh()
    if(props.initialVersion)await open(await request<Version>('/story/versions/'+props.initialVersion))
    if(props.initialClip && timeline.tracks.some(lane=>lane.clips.some(clip=>clip.id===props.initialClip))){
      currentClip.value=props.initialClip
      await nextTick()
      Array.from(workbench.value?.querySelectorAll<HTMLButtonElement>('button[data-clip-id]') || [])
        .find(button=>button.dataset.clipId===props.initialClip)?.focus()
    }
  })
  timer=setInterval(()=>{if(!busy.value)void refresh().catch(failure=>{error.value=String(failure)})},3000)
})
onUnmounted(()=>clearInterval(timer))
</script>

<template>
  <p v-if="!projectId" class="empty">选择项目以编辑多轨时间轴。</p>
  <div v-else ref="workbench" class="timeline-workbench">
    <div v-if="canReturn" class="actions">
      <button type="button" :disabled="busy || dirty" @click="emit('returnToProduction')">返回原质检批次</button>
      <span v-if="!busy && dirty" class="hint">保存时间轴后可返回质检。</span>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <div class="story-layout timeline-desk">
      <section class="story-library">
        <header class="timeline-panel-title"><Image :size="18" aria-hidden="true" /><h2>素材浏览器</h2></header>
        <label>查找监看素材<input v-model="assetSearch" type="search" placeholder="按名称筛选"></label>
        <div v-if="visibleAssets.length" class="timeline-sources">
          <button v-for="asset in visibleAssets" :key="asset.id" type="button" :aria-pressed="asset.id===activeAsset?.id" @click="browserPreview=asset.id">
            <img v-if="/\.(png|jpe?g|webp)$/i.test(asset.name)" :src="`/api/assets/${asset.id}/media`" alt="" loading="lazy">
            <Film v-else :size="20" aria-hidden="true" />
            <span :title="asset.name">{{asset.name}}</span>
          </button>
        </div>
        <p v-else class="hint">没有符合条件的预览素材。</p>
        <RouterLink :to="{name:'assets',query:{project:projectId}}">打开素材库</RouterLink>
        <header class="timeline-panel-title"><Layers3 :size="18" aria-hidden="true" /><h2>时间轴版本</h2></header>
        <button :disabled="busy" @click="fresh">新建时间轴</button>
        <button v-for="item in stack" :key="item.id" :disabled="busy" :aria-pressed="active?.id===item.id"
          @click="run(()=>open(item))">{{ item.title }} · v{{ item.version }}</button>
        <details v-if="editions.length">
          <summary>历史版本</summary>
          <div class="version-list">
            <button v-for="item in editions" :key="item.version_id" :disabled="busy" @click="run(()=>open(item))">v{{ item.version }}</button>
          </div>
          <button v-if="active && active.version<active.current_version" :disabled="busy" @click="restore">追加恢复此版</button>
        </details>
        <details>
          <summary>按计划自动剪辑</summary>
          <form class="form-grid" @submit.prevent="assemble">
            <label>已审核制作计划版本 ID<input v-model="planVersion" required maxlength="36"></label>
            <label>分集序号<input v-model.number="planEpisode" required type="number" min="1" max="60"></label>
            <label>时间轴名称<input v-model="autoTitle" required maxlength="200"></label>
            <button :disabled="busy">按已采纳候选装配</button>
          </form>
        </details>
      </section>
      <section class="timeline-session">
        <form class="form-grid editor-desk" @submit.prevent="save">
        <div class="timeline-monitor">
          <div class="timeline-monitor-media">
            <img v-if="activeMedia?.tag==='img'" :src="activeMedia.url" :alt="activeMedia.name" @error="sourceError=true">
            <component v-else-if="activeMedia" :is="activeMedia.tag" :key="activeMedia.url" ref="sourceMonitor"
              :src="activeMedia.url" controls preload="metadata" @loadedmetadata="cueSource" @error="sourceError=true"></component>
            <div v-else class="timeline-monitor-empty"><MonitorPlay :size="27" aria-hidden="true" /><span>选择素材片段进行源预览</span></div>
          </div>
          <div class="timeline-monitor-info">
            <p class="hint">视频监看</p>
            <h2>{{ activeAsset?.name || title || '未命名时间轴' }}</h2>
            <p v-if="sourceError" class="error">浏览器无法解码此素材，可在智能解析生成代理。</p>
            <dl><div><dt>画幅</dt><dd>{{profiles[timeline.profile]}}</dd></div><div><dt>轨道 / 片段</dt><dd>{{timeline.tracks.length}} / {{clipCount}}</dd></div></dl>
            <p v-if="selection" class="hint">入点 {{clock(selection.clip.source_in/24*1e6)}} · {{selection.clip.frames}} 帧</p>
            <p class="hint">合成画面在渲染完成后可预览。</p>
          </div>
        </div>
          <div class="timeline-settings">
          <div class="editor-grid">
            <label>时间轴标题<input v-model="title" required maxlength="200"></label>
            <label>输出画幅<select v-model="timeline.profile"><option v-for="(label,key) in profiles" :key="key" :value="key">{{ label }}</option></select></label>
            <label>总帧数（24 fps）<input v-model.number="timeline.frames" required type="number" min="12" max="14400"></label>
          </div>
          <label>固定制作来源版本 ID（可选）<input :value="timeline.source_version_id||''" maxlength="36"
            @input="timeline.source_version_id=($event.target as HTMLInputElement).value.trim()||null"></label>
          <label class="check"><input v-model="snap" type="checkbox">吸附片段边界</label>
          </div>
          <div class="tracks" aria-label="多轨片段">
            <div class="track-header"><strong>剪辑轨道</strong><span>{{ timeline.frames }} 帧 · 24 fps</span></div>
            <div class="track-ruler" aria-label="时间标尺"><time v-for="(tick,index) in ticks" :key="index">{{tick}}</time></div>
            <article v-for="(lane,index) in timeline.tracks" :key="lane.id" class="lane" :data-role="lane.role">
              <div class="actions lane-controls">
                <strong>{{ labels[lane.role] }}</strong>
                <label class="check"><input v-model="lane.enabled" type="checkbox">启用</label>
                <label class="check"><input v-model="lane.locked" type="checkbox">锁定</label>
                <label v-if="['dialogue','music','sfx'].includes(lane.role)">音量<input v-model.number="lane.volume" :disabled="lane.locked" type="number" min="0" max="4" step="0.05"></label>
                <button type="button" :disabled="lane.locked || index===0" @click="moveTrack(index,-1)">上移</button>
                <button type="button" :disabled="lane.locked || index===timeline.tracks.length-1" @click="moveTrack(index,1)">下移</button>
                <button type="button" :disabled="lane.locked || lane.clips.length>=40" @click="addClip(lane)">添加片段</button>
                <button v-if="lane.role!=='main'" type="button" :disabled="lane.locked" @click="timeline.tracks.splice(index,1)">移除</button>
              </div>
              <div class="rail" :class="{muted:!lane.enabled}" @pointermove="dragClip" @pointerup="endGesture($event)"
                @pointercancel="endGesture($event,true)" @lostpointercapture="endGesture($event,true)">
                <template v-for="clip in lane.clips" :key="clip.id">
                  <button class="clip" type="button" :aria-pressed="clip.id===currentClip" :data-clip-id="clip.id"
                    :title="name(clip.asset_id)" :style="{left:(clip.at/Math.max(1,timeline.frames)*100)+'%',width:(clip.frames/Math.max(1,timeline.frames)*100)+'%'}"
                    @click="currentClip=clip.id;browserPreview=''" @pointerdown="beginGesture($event,lane,clip,'move')" @keydown="clipKeys($event,lane,clip,'move')">{{ name(clip.asset_id) }}</button>
                  <template v-if="clip.id===currentClip && !lane.locked">
                    <button v-for="edge in (['start','end'] as const)" :key="edge" class="trim-handle" type="button"
                      :aria-label="edge==='start'?'裁剪片段入点':'裁剪片段出点'"
                      :style="{left:((clip.at+(edge==='end'?clip.frames:0))/Math.max(1,timeline.frames)*100)+'%'}"
                      @pointerdown="beginGesture($event,lane,clip,edge)" @keydown="clipKeys($event,lane,clip,edge)"></button>
                  </template>
                </template>
              </div>
            </article>
          </div>
          <div class="actions">
            <label>附加轨道<select v-model="trackRole"><option v-for="role in (['overlay','dialogue','music','sfx','caption'] as Role[])"
              :key="role" :value="role">{{ labels[role] }}</option></select></label>
            <button type="button" :disabled="timeline.tracks.length>=10 || (trackRole==='caption' && timeline.tracks.some(lane=>lane.role==='caption'))"
              @click="timeline.tracks.push(track(trackRole))">添加轨道</button>
          </div>
          <aside class="timeline-inspector">
          <h2>片段属性</h2>
          <p v-if="!selection" class="hint">在轨道中选择片段以编辑入点、位置和时长。</p>
          <fieldset v-else :disabled="selection.lane.locked">
            <legend>{{ labels[selection.lane.role] }}片段</legend>
            <label>片段素材<select v-model="selection.clip.asset_id" required>
              <option value="">选择项目素材</option><option v-for="asset in possible(selection.lane)" :key="asset.id" :value="asset.id">{{ asset.name }}</option>
            </select></label>
            <div class="editor-grid">
              <label>时间轴位置（帧）<input v-model.number="selection.clip.at" type="number" required min="0" max="14399"></label>
              <label>源入点（帧）<input v-model.number="selection.clip.source_in" type="number" required min="0"></label>
              <label>时长（帧）<input v-model.number="selection.clip.frames" type="number" required min="1" max="14400"></label>
              <label v-if="/\.(png|jpe?g|webp)$/i.test(name(selection.clip.asset_id))">静图运镜<select v-model="selection.clip.still_motion">
                <option value="none">固定</option><option value="push_in">推进</option>
              </select></label>
              <template v-if="selection.lane.role!=='caption'">
                <label>淡入帧数<input v-model.number="selection.clip.fade_in" type="number" required min="0" max="240"></label>
                <label>淡出帧数<input v-model.number="selection.clip.fade_out" type="number" required min="0" max="240"></label>
              </template>
            </div>
            <button type="button" @click="selection.lane.clips.splice(selection.lane.clips.indexOf(selection.clip),1);currentClip=''">移除片段</button>
          </fieldset>
          <div class="actions">
            <button class="primary" :disabled="busy || !title.trim() || !dirty">保存时间轴版本</button>
            <button type="button" :disabled="busy || !active || dirty" @click="render">渲染已保存版本</button>
            <a v-if="active" :href="`/api/timeline/versions/${active.version_id}/manifest`" download="timeline.json">工程 JSON</a>
          </div>
          </aside>
        </form>
      </section>
    </div>
    <section class="timeline-output">
      <header class="timeline-panel-title"><Film :size="18" aria-hidden="true" /><h2>多轨成片</h2></header>
      <video v-if="preview" :key="preview" controls :src="`/api/tasks/${preview}/output`"></video>
      <p v-if="!jobs.length" class="hint">已保存的版本可以提交本地渲染。</p>
      <article v-for="job in jobs" :key="job.id" class="task">
        <div><p>{{ statusLabels[job.status] || job.status }} · {{ statusLabels[job.stage] || job.stage }}</p>
          <p class="mono">时间轴版本 {{ job.story_version_id }}</p><p v-if="job.error" class="error">{{ job.error }}</p>
          <progress v-if="job.status==='running'" :value="job.progress" max="100" aria-label="已处理成片进度"></progress>
        </div>
        <button v-if="job.status==='succeeded'" @click="preview=job.id">预览多轨成片</button>
        <a v-if="job.status==='succeeded'" :href="`/api/tasks/${job.id}/output?download=true`">下载 MP4</a>
        <button v-if="['queued','running'].includes(job.status)" :disabled="busy || job.cancel_requested" @click="control(job,'cancel')">取消</button>
        <button v-if="['failed','cancelled'].includes(job.status)" :disabled="busy" @click="control(job,'retry')">重试</button>
      </article>
    </section>
  </div>
</template>

<style scoped>
.timeline-workbench,.form-grid { display:grid; gap:16px }
.timeline-workbench section { min-width:0 }
.timeline-panel-title { display:flex; align-items:center; gap:8px; color:var(--accent) }
.timeline-panel-title h2 { color:var(--ink); margin:0 }
.timeline-desk { grid-template-columns:minmax(175px,215px) minmax(0,1fr);gap:14px }
.editor-desk { grid-template-columns:minmax(0,1fr) minmax(162px,235px);gap:14px;align-items:start }
.editor-desk>* { min-width:0 }
.editor-desk>.timeline-inspector { grid-column:2;grid-row:1/span 4;padding:12px;border:1px solid var(--line);background:var(--surface-raised);border-radius:11px }
.timeline-inspector .actions { margin-top:10px }
.timeline-inspector .editor-grid { grid-template-columns:minmax(0,1fr) }
.timeline-settings>label { margin-top:8px }
.timeline-sources { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:6px;max-height:360px;overflow:auto }
.timeline-sources button { display:grid;justify-items:center;gap:5px;padding:6px;min-width:0;color:var(--ink-muted) }
.timeline-sources button[aria-pressed=true] { border-color:var(--accent);background:var(--accent-surface) }
.timeline-sources img { width:100%;height:44px;object-fit:cover;border-radius:4px }
.timeline-sources span { max-width:100%;text-overflow:ellipsis;white-space:nowrap;overflow:hidden;font-size:11px }
.timeline-monitor { display:grid;grid-template-columns:minmax(0,1fr);gap:9px;padding:9px;background:var(--surface-raised);border:1px solid var(--line-soft);border-radius:11px }
.timeline-monitor-media { min-width:0;display:grid;place-items:center;background:#172237;border-radius:7px;overflow:hidden }
.timeline-monitor-media :is(img,video) { display:block; height:min(27vh,220px); width:100%; object-fit:contain }
.timeline-monitor-media audio { max-width:95%; margin:18px 0 }
.timeline-monitor-empty { display:grid;place-items:center;align-content:center;gap:9px;aspect-ratio:16/7;color:#dce6f4;font-size:12px;width:100%;padding:10px }
.timeline-monitor-info { min-width:0; padding-right:4px; overflow-wrap:anywhere }
.timeline-monitor-info h2,.timeline-monitor-info p { margin-bottom:6px }
.timeline-monitor-info dl { display:flex; gap:18px; margin:8px 0 }
.timeline-monitor-info dt { color:var(--ink-muted); font-size:12px }
.timeline-monitor-info dd { margin:3px 0 0; font-variant-numeric:tabular-nums }
.tracks { border:1px solid #364660;border-radius:10px;background:#172237;color:#dce6f4;padding:10px }
.tracks :is(label,.track-header span,.track-ruler) { color:#aebfdb }
.track-header,.track-ruler { display:flex; justify-content:space-between; gap:5px; }
.track-header span { color:var(--ink-muted); font-size:12px }
.track-ruler { padding:6px 0; margin-top:6px; border-block:1px solid var(--line-soft); color:var(--ink-muted); font:11px Consolas,monospace }
.timeline-workbench details,.timeline-workbench fieldset { margin:0 }
.timeline-workbench fieldset label { margin:8px 0 }
.lane { margin-bottom:12px }
.lane-controls { min-height:42px; gap:8px }
.lane-controls label input[type=number] { width:74px }
.rail { height:42px;position:relative;overflow:hidden;border:1px solid #394b69;border-radius:4px;background:#121b2f }
.muted { opacity:.5 }
.rail .clip { display:block;height:38px;min-width:9px;position:absolute;padding:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;background:#526d9d;color:#fff;border-color:#90a8d3;touch-action:none;cursor:grab }
.lane[data-role=caption] .clip,.lane[data-role=overlay] .clip { background:#70649a;border-color:#a599c4 }
.lane:is([data-role=dialogue],[data-role=music],[data-role=sfx]) .clip { background:#387a74;border-color:#6eada0 }
.clip[aria-pressed="true"] { border-color:#95c9ff; z-index:1 }
.rail .trim-handle { position:absolute;z-index:2;top:3px;width:10px;height:34px;min-height:0;padding:0;transform:translateX(-50%);background:#86aed8;border-radius:3px;touch-action:none;cursor:ew-resize }
.trim-handle:focus-visible { outline:2px solid white; outline-offset:-2px }
.timeline-workbench video { max-height:60vh }
@media(max-width:1080px) { .timeline-desk { grid-template-columns:minmax(0,1fr) } .timeline-sources { grid-template-columns:repeat(auto-fit,minmax(82px,1fr)) } }
@media(max-width:720px) { .editor-desk { grid-template-columns:minmax(0,1fr) } .editor-desk>.timeline-inspector { grid-column:1;grid-row:auto } }
@media(max-width:530px) { .timeline-monitor { grid-template-columns:1fr } .track-ruler time:nth-child(even) { display:none } }
</style>
