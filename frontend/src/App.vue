<script setup lang="ts">
import { defineAsyncComponent, ref, onMounted, onUnmounted } from 'vue'
const VideoEditor=defineAsyncComponent(()=>import('./VideoEditor.vue'))
const QueuePanel=defineAsyncComponent(()=>import('./QueuePanel.vue'))
const AttemptHistory=defineAsyncComponent(()=>import('./AttemptHistory.vue'))
const StoryStudio=defineAsyncComponent(()=>import('./StoryStudio.vue'))
const TextAdaptation=defineAsyncComponent(()=>import('./TextAdaptation.vue'))
const MediaAnalysis=defineAsyncComponent(()=>import('./MediaAnalysis.vue'))
const SeriesStudio=defineAsyncComponent(()=>import('./SeriesStudio.vue'))
const GenerationStudio=defineAsyncComponent(()=>import('./GenerationStudio.vue'))
const VoiceStudio=defineAsyncComponent(()=>import('./VoiceStudio.vue'))
const TimelineStudio=defineAsyncComponent(()=>import('./TimelineStudio.vue'))
const ProductionStudio=defineAsyncComponent(()=>import('./ProductionStudio.vue'))
const LibraryDelivery=defineAsyncComponent(()=>import('./LibraryDelivery.vue'))
const SystemStudio=defineAsyncComponent(()=>import('./SystemStudio.vue'))
const OperationsStudio=defineAsyncComponent(()=>import('./OperationsStudio.vue'))
interface Project {id:string;name:string;description:string;budget_cents:number}
interface Asset {id:string;name:string;size_bytes:number;authorization:string;sha256:string;media_info:Record<string,unknown>}
interface Task {story_version_id:string|null;batch_id:string|null;error_code:string|null;next_run_at:string;id:string;asset_id:string|null;status:string;kind:string;attempt:number;error:string|null;stage:string;progress:number;cancel_requested:boolean;elapsed_seconds:number;parameters:Record<string,unknown>;output:{storage_key?:string;duration?:number;width?:number;height?:number;size_bytes?:number;has_audio?:boolean}}
interface Event {id:number;attempt:number;message:string;created_at:string}
const projects=ref<Project[]>([]), assets=ref<Asset[]>([]), tasks=ref<Task[]>([]), events=ref<Event[]>([])
const selected=ref(''), preview=ref(''), error=ref(''), health=ref('检查中'), busy=ref(false), name=ref(''), description=ref(''), authorization=ref(''), cost=ref(''), view=ref('素材资产中心'), logTask=ref('')
const outputPreview=ref('')
const isRender=(task:Task)=>task.kind==='render'||task.kind==='timeline_render'
const productionStory=ref<{version_id:string;title:string;version:number}|null>(null)
function useStory(version:{version_id:string;title:string;version:number}){productionStory.value=version;view.value='智能二创'}
const adaptationSource=ref<{version_id:string;title:string;version:number}|null>(null)
function adaptStory(version:{version_id:string;title:string;version:number}){adaptationSource.value=version;view.value='剧情改编'}
const analysisAsset=ref('')
const timelineVersion=ref('')
function openTimeline(versionId:string){timelineVersion.value=versionId;view.value='多轨时间轴'}
function openAnalysis(asset:Asset){analysisAsset.value=asset.id;view.value='智能解析'}
const sections=['素材资产中心','智能解析','智能二创','剧情改编','漫剧定制','故事圣经','生成候选','配音与字幕','多轨时间轴','批量生产','质检与导出','资源与交付','运营中心','运行诊断']
const labels:Record<string,string>={queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败',cancelled:'已取消'}
const stages:Record<string,string>={queued:'等待领取',recovered:'中断恢复',inspecting:'检查输入',encoding:'FFmpeg 编码',validating:'验证成片',publishing:'发布输出',succeeded:'完成',failed:'失败',cancelled:'已取消',retry_wait:'等待自动重试',checkpoint:'核验检查点',resuming_checkpoint:'复用编码检查点',awaiting_review:'待人工审核',approved:'人工已通过',rejected:'人工已拒绝',settlement_recovery:'恢复用量核算',dispatching:'模型调用处理中',received:'响应已保存，核算中'}
let timer:ReturnType<typeof setInterval>|undefined
let refreshing=''
let pendingAssetRefresh=''
let assetUpdatedAt=0
const taskLimit=ref(50), taskOffset=ref(0)
async function api<T>(path:string, options:RequestInit={}):Promise<T>{
 const response=await fetch('/api'+path,options)
 if(!response.ok){let message=`HTTP ${response.status}`;try{const data=await response.json();message=typeof data.detail==='string'?data.detail:JSON.stringify(data.detail)}catch{}throw new Error(message)}
 return response.json()
}
async function refresh(forceAssets=true){
 const project=selected.value
 if(!project)return
 if(refreshing===project){
  if(forceAssets)pendingAssetRefresh=project
  return
 }
 refreshing=project
 const offset=taskOffset.value
 const includeAssets=forceAssets||Date.now()-assetUpdatedAt>=15000
 try{
  const [a,t,c]=await Promise.all([
   includeAssets?api<Asset[]>(`/projects/${project}/assets`):Promise.resolve(null),
   api<Task[]>(`/projects/${project}/tasks?offset=${offset}&limit=${taskLimit.value}`),
   includeAssets?api<{recorded_cents:number;note:string}>(`/projects/${project}/costs`):Promise.resolve(null),
  ])
  if(project!==selected.value)return
  if(a){assets.value=a;assetUpdatedAt=Date.now()}
  if(offset===taskOffset.value)tasks.value=t
  if(c)cost.value=`¥${(c.recorded_cents/100).toFixed(2)} · ${c.note}`
 }catch(e){if(project===selected.value)error.value=String(e)}
 finally{
  if(refreshing===project)refreshing=''
  if(project===selected.value && pendingAssetRefresh===project){
   pendingAssetRefresh=''
   void refresh()
  }else if(project===selected.value && offset!==taskOffset.value)void refresh(false)
 }
}
async function taskPage(direction:number){
 taskOffset.value=Math.max(0,taskOffset.value+direction*taskLimit.value)
 logTask.value=''
 await refresh(false)
}
async function changeProject(){assetUpdatedAt=0;taskOffset.value=0;assets.value=[];tasks.value=[];preview.value='';outputPreview.value='';productionStory.value=null;adaptationSource.value=null;analysisAsset.value='';timelineVersion.value='';events.value=[];logTask.value='';cost.value='';if(selected.value)await refresh()}
async function action(fn:()=>Promise<void>){busy.value=true;error.value='';try{await fn()}catch(e){error.value=String(e)}finally{busy.value=false}}
async function create(){await action(async()=>{const p=await api<Project>('/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.value,description:description.value})});projects.value.unshift(p);selected.value=p.id;name.value='';description.value='';await changeProject()})}
async function upload(event:globalThis.Event){const input=event.target as HTMLInputElement;const files=Array.from(input.files??[]);await action(async()=>{if(!authorization.value.trim())throw new Error('请先填写授权来源');for(const file of files){const form=new FormData();form.append('file',file);form.append('authorization',authorization.value);await api(`/projects/${selected.value}/assets`,{method:'POST',body:form})}await refresh()});input.value=''}
async function probe(asset:Asset){await action(async()=>{await api(`/projects/${selected.value}/tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:asset.id,idempotency_key:`probe:${asset.id}:v1`})});await refresh()})}
async function retry(task:Task){await action(async()=>{await api(`/tasks/${task.id}/retry`,{method:'POST'});await refresh()})}
async function cancel(task:Task){await action(async()=>{await api(`/tasks/${task.id}/cancel`,{method:'POST'});await refresh()})}
async function logs(task:Task){await action(async()=>{events.value=await api<Event[]>(`/tasks/${task.id}/events`);logTask.value=task.id})}
onMounted(async()=>{await action(async()=>{try{await api('/health');health.value='服务就绪'}catch{health.value='服务未就绪：检查后端、数据库迁移和 FFmpeg'}projects.value=await api<Project[]>('/projects');if(projects.value.length){selected.value=projects.value[0].id;await changeProject()}});timer=setInterval(()=>{if(selected.value)void refresh(false)},3000)})
onUnmounted(()=>clearInterval(timer))
</script>

<template>
 <div class="shell">
  <aside><div class="brand">AI 漫剧工厂<span>LOCAL PRODUCTION STUDIO</span></div><nav aria-label="工作区"><button v-for="section in sections" :key="section" :class="{active:view===section}" @click="view=section">{{section}}</button></nav><div class="aside-note">本机工作台<br>仅处理自有或已授权素材</div></aside>
  <main>
   <header><div><p class="eyebrow">PRODUCTION WORKSPACE</p><h1>{{view}}</h1></div><span class="health">{{health}}</span></header>
   <p v-if="error" class="error" role="alert">{{error}} <button @click="error=''">关闭</button></p>
   <div class="projectbar"><label>当前项目 <select v-model="selected" @change="changeProject"><option value="">选择项目</option><option v-for="p in projects" :key="p.id" :value="p.id">{{p.name}}</option></select></label><span v-if="busy" role="status">正在提交真实请求…</span><button :disabled="!selected||busy" @click="refresh()">刷新状态</button></div>
   <template v-if="view==='素材资产中心'">
    <details :open="!projects.length"><summary>新建项目</summary><form class="create" @submit.prevent="create"><label>项目名称<input v-model="name" required maxlength="200" placeholder="输入项目名称"></label><label>项目说明<textarea v-model="description" maxlength="20000" placeholder="故事方向、授权范围或制作要求"></textarea></label><button class="primary" :disabled="busy||!name.trim()">创建项目</button></form></details>
    <div v-if="selected" class="workspace"><section><h2>原始素材 <span>{{assets.length}} 个</span></h2><label>授权来源<textarea v-model="authorization" maxlength="10000" placeholder="记录自有素材声明或授权方、协议编号及使用范围"></textarea></label><label class="upload">导入视频 / 音频 / 字幕 / 文本 / 图片<input type="file" multiple accept=".mp4,.mov,.mkv,.webm,.avi,.wav,.mp3,.srt,.txt,.png,.jpg,.jpeg,.webp" :disabled="busy||!authorization.trim()" @change="upload"></label><p class="hint">媒体每文件上限 2 GiB；SRT/TXT 2 MiB，参考图片 20 MiB。处理不覆盖原始素材。</p><div v-if="!assets.length" class="empty">尚无素材。填写授权来源后导入文件。</div><article v-for="asset in assets" :key="asset.id" class="asset"><div><strong>{{asset.name}}</strong><p>{{(asset.size_bytes/1024/1024).toFixed(2)}} MB · {{Object.keys(asset.media_info).length?'已解析':'待解析'}}</p><p>{{asset.authorization}}</p></div><div class="actions"><button :disabled="/\.(srt|txt)$/i.test(asset.name)" @click="preview=asset.id">预览</button><button :disabled="busy||/\.(srt|txt|png|jpe?g|webp)$/i.test(asset.name)" @click="probe(asset)">读取媒体信息</button><button v-if="/\.(mp4|mov|mkv|webm|avi|wav|mp3)$/i.test(asset.name)" :disabled="busy" @click="openAnalysis(asset)">智能解析</button></div></article></section><section class="preview"><h2>素材预览</h2><img v-if="preview&&/\.(png|jpe?g|webp)$/i.test(assets.find(a=>a.id===preview)?.name||'')" class="reference-preview" :src="`/api/assets/${preview}/media`" alt="授权参考素材"><video v-else-if="preview" :key="preview" controls preload="metadata" :src="`/api/assets/${preview}/media`"></video><div v-else class="empty screen">选择素材开始预览</div><p class="hint">浏览器无法播放的编码可在智能二创中转为 MP4。SRT 仅用于烧录，不支持视频预览。</p><h2>已记录费用</h2><p class="cost">{{cost||'等待读取'}}</p></section></div>
    <div v-else class="empty">创建一个项目，开始管理授权素材。</div>
   </template>
   <MediaAnalysis v-else-if="view==='智能解析'" :key="selected" :project-id="selected" :assets="assets" :initial-asset-id="analysisAsset" @adaptation="adaptStory" @assets-changed="refresh" />
   <template v-else-if="view==='智能二创'"><p v-if="productionStory" class="hint">生产依据：{{productionStory.title}} · v{{productionStory.version}} <button @click="productionStory=null">清除引用</button></p><VideoEditor :project-id="selected" :assets="assets" :story-version-id="productionStory?.version_id" @submitted="refresh" /></template>
   <StoryStudio :key="selected" v-else-if="view==='漫剧定制'" :project-id="selected" :assets="assets" @assets-changed="refresh" @production="useStory" @adaptation="adaptStory" />
   <TextAdaptation v-else-if="view==='剧情改编'" :key="selected" :project-id="selected" :source="adaptationSource" @source-picker="view='漫剧定制'" @production="useStory" />
   <SeriesStudio v-else-if="view==='故事圣经'" :key="selected" :project-id="selected" />
   <GenerationStudio v-else-if="view==='生成候选'" :key="selected" :project-id="selected" :assets="assets" @assets-changed="refresh" />
   <VoiceStudio v-else-if="view==='配音与字幕'" :key="selected" :project-id="selected" @assets-changed="refresh" />
   <TimelineStudio v-else-if="view==='多轨时间轴'" :key="selected" :project-id="selected" :assets="assets" :initial-version="timelineVersion" />
   <template v-else-if="view==='批量生产'">
    <ProductionStudio :key="selected" :project-id="selected" @inspect-timeline="openTimeline" />
    <QueuePanel :project-id="selected" />
    <h2>持久化任务队列</h2><p class="hint">全局同时执行 1 项任务。编码进度来自 FFmpeg 已处理时间，验证完成后才显示 100%。Worker 重启后等待租约过期，再安全恢复未完成剪辑。</p>
    <p v-if="!selected" class="empty">请先选择项目。</p><p v-else-if="!tasks.length" class="empty">暂无任务。导入素材后可读取媒体信息，或在智能二创中提交剪辑任务。</p>
    <div v-if="taskOffset||tasks.length===taskLimit" class="actions"><button :disabled="!taskOffset" @click="taskPage(-1)">上一页任务</button><button :disabled="tasks.length<taskLimit" @click="taskPage(1)">下一页任务</button><span class="hint">任务第 {{ Math.floor(taskOffset/taskLimit)+1 }} 页</span></div>
    <article v-for="task in tasks" :key="task.id" class="task">
     <div><strong>{{assets.find(a=>a.id===task.asset_id)?.name||task.asset_id||(task.kind==='local_voice'?'本机配音':task.kind==='timeline_render'?'多轨渲染':task.kind==='qc_review'?'技术质检':task.kind==='delivery'?'整剧交付':task.kind==='promotion'?'推广包':'剧情改编')}}</strong><p class="mono">{{task.kind==='promotion'?'推广包':task.kind==='delivery'?'整剧交付':task.kind==='qc_review'?'技术质检':task.kind==='timeline_render'?'多轨渲染':task.kind==='render'?'视频剪辑':task.kind==='adapt'?'剧情改编':task.kind==='still_motion'?'静图运镜':task.kind==='local_voice'?'本机配音':'媒体解析'}} · {{task.id}}</p><p v-if="task.batch_id" class="mono">批次 {{task.batch_id}}</p><p v-if="task.story_version_id" class="mono">创作版本 {{task.story_version_id}}</p><p v-if="task.stage==='retry_wait'" class="hint">{{task.error_code}} · 计划重试 {{new Date(task.next_run_at).toLocaleString('zh-CN')}}</p>
      <p>{{stages[task.stage]||task.stage}} · 本次耗时 {{task.elapsed_seconds.toFixed(1)}} 秒 · 尝试 {{task.attempt}}</p>
      <progress v-if="isRender(task)" :value="task.progress" max="100" :aria-label="`编码进度 ${task.progress.toFixed(1)}%`"></progress><span v-if="isRender(task)"> {{task.progress.toFixed(1)}}%</span>
      <details v-if="isRender(task)"><summary>已保存处理参数</summary><pre>{{JSON.stringify(task.parameters,null,2)}}</pre></details>
      <p v-if="task.error" class="error">{{task.error}}</p>
     </div>
     <span :class="['status',task.status]">{{task.cancel_requested&&task.status==='running'?'取消中':labels[task.status]||task.status}}</span>
     <button @click="logs(task)">日志</button><button v-if="['queued','running'].includes(task.status)" :disabled="busy||task.cancel_requested" @click="cancel(task)">取消</button><button v-if="task.kind!=='adapt'&&['failed','cancelled'].includes(task.status)" :disabled="busy" @click="retry(task)">安全重试</button>
     <button v-if="isRender(task)&&task.status==='succeeded'" @click="outputPreview=task.id">预览成片</button><a v-if="isRender(task)&&task.status==='succeeded'" :href="`/api/tasks/${task.id}/output?download=true`">下载成片</a>
    </article>
    <section v-if="logTask"><AttemptHistory :task-id="logTask" /><h2>事件日志</h2><p class="mono">{{logTask}}</p><p v-for="event in events" :key="event.id" class="log">{{new Date(event.created_at).toLocaleString('zh-CN')}} · 尝试 {{event.attempt}} · {{event.message}}</p><button @click="logs(tasks.find(t=>t.id===logTask)!)">刷新日志</button></section>
   </template>
   <template v-else-if="view==='质检与导出'">
    <h2>已验证成片</h2><p class="hint">这里只展示通过视频流、音轨、时长和分辨率技术验证的成片。黑帧、音频质量与字幕内容审核尚未实现。</p>
    <div v-if="taskOffset||tasks.length===taskLimit" class="actions"><button :disabled="!taskOffset" @click="taskPage(-1)">上一页任务</button><button :disabled="tasks.length<taskLimit" @click="taskPage(1)">下一页任务</button><span class="hint">任务第 {{ Math.floor(taskOffset/taskLimit)+1 }} 页</span></div>
    <p v-if="!tasks.some(t=>isRender(t)&&t.status==='succeeded')" class="empty">当前任务页暂无已验证成片。</p>
    <article v-for="task in tasks.filter(t=>isRender(t)&&t.status==='succeeded')" :key="task.id" class="task"><div><strong>{{assets.find(a=>a.id===task.asset_id)?.name||'多轨成片'}}</strong><p>{{task.output.width}} × {{task.output.height}} · {{task.output.duration?.toFixed(2)}} 秒 · {{((task.output.size_bytes||0)/1024/1024).toFixed(2)}} MB · {{task.output.has_audio?'有音轨':'无音轨'}}</p></div><button @click="outputPreview=task.id">预览成片</button><a :href="`/api/tasks/${task.id}/output?download=true`">下载</a></article>
   </template>
   <LibraryDelivery v-else-if="view==='资源与交付'" :key="selected" :project-id="selected" :assets="assets" />
   <OperationsStudio v-else-if="view==='运营中心'" :key="selected" :project-id="selected" />
   <SystemStudio v-else-if="view==='运行诊断'" />
  <section v-if="outputPreview" class="output-preview"><div class="actions"><h2>已验证成片预览</h2><button @click="outputPreview=''">关闭预览</button></div><video :key="outputPreview" controls :src="`/api/tasks/${outputPreview}/output`"></video><p class="hint">MKV 播放取决于浏览器支持，可下载后使用本机播放器。</p></section>
  </main>
 </div>
</template>
