<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
interface Project {id:string;name:string;description:string;budget_cents:number}
interface Asset {id:string;name:string;size_bytes:number;authorization:string;sha256:string;media_info:Record<string,unknown>}
interface Task {id:string;asset_id:string;status:string;attempt:number;error:string|null}
interface Event {id:number;attempt:number;message:string;created_at:string}
const projects=ref<Project[]>([]), assets=ref<Asset[]>([]), tasks=ref<Task[]>([]), events=ref<Event[]>([])
const selected=ref(''), preview=ref(''), error=ref(''), health=ref('检查中'), busy=ref(false), name=ref(''), description=ref(''), authorization=ref(''), cost=ref(''), view=ref('素材资产中心'), logTask=ref('')
const sections=['素材资产中心','智能二创','漫剧定制','批量生产','质检与导出','运营中心']
const labels:Record<string,string>={queued:'排队中',running:'执行中',succeeded:'已完成',failed:'失败'}
let timer:ReturnType<typeof setInterval>|undefined
let refreshing=false
async function api<T>(path:string, options:RequestInit={}):Promise<T>{
 const response=await fetch('/api'+path,options)
 if(!response.ok){let message=`HTTP ${response.status}`;try{const data=await response.json();message=typeof data.detail==='string'?data.detail:JSON.stringify(data.detail)}catch{}throw new Error(message)}
 return response.json()
}
async function refresh(){
 if(refreshing)return; refreshing=true
 const project=selected.value
 try{
  const [a,t,c]=await Promise.all([api<Asset[]>(`/projects/${project}/assets`),api<Task[]>(`/projects/${project}/tasks`),api<{recorded_cents:number;note:string}>(`/projects/${project}/costs`)])
  if(project!==selected.value)return
  assets.value=a;tasks.value=t;cost.value=`¥${(c.recorded_cents/100).toFixed(2)} · ${c.note}`
 }catch(e){error.value=String(e)}finally{refreshing=false}
}
async function changeProject(){assets.value=[];tasks.value=[];preview.value='';events.value=[];logTask.value='';cost.value='';if(selected.value)await refresh()}
async function action(fn:()=>Promise<void>){busy.value=true;error.value='';try{await fn()}catch(e){error.value=String(e)}finally{busy.value=false}}
async function create(){await action(async()=>{const p=await api<Project>('/projects',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.value,description:description.value})});projects.value.unshift(p);selected.value=p.id;name.value='';description.value='';await changeProject()})}
async function upload(event:globalThis.Event){const input=event.target as HTMLInputElement;const files=Array.from(input.files??[]);await action(async()=>{if(!authorization.value.trim())throw new Error('请先填写授权来源');for(const file of files){const form=new FormData();form.append('file',file);form.append('authorization',authorization.value);await api(`/projects/${selected.value}/assets`,{method:'POST',body:form})}await refresh()});input.value=''}
async function probe(asset:Asset){await action(async()=>{await api(`/projects/${selected.value}/tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:asset.id,idempotency_key:`probe:${asset.id}:v1`})});await refresh()})}
async function retry(task:Task){await action(async()=>{await api(`/tasks/${task.id}/retry`,{method:'POST'});await refresh()})}
async function logs(task:Task){await action(async()=>{events.value=await api<Event[]>(`/tasks/${task.id}/events`);logTask.value=task.id})}
onMounted(async()=>{await action(async()=>{try{await api('/health');health.value='服务就绪'}catch{health.value='服务未就绪：检查后端、数据库迁移和 FFmpeg'}projects.value=await api<Project[]>('/projects');if(projects.value.length){selected.value=projects.value[0].id;await changeProject()}});timer=setInterval(()=>{if(selected.value)void refresh()},3000)})
onUnmounted(()=>clearInterval(timer))
</script>

<template>
 <div class="shell">
  <aside><div class="brand">AI 漫剧工厂<span>LOCAL PRODUCTION STUDIO</span></div><nav aria-label="工作区"><button v-for="section in sections" :key="section" :class="{active:view===section}" @click="view=section">{{section}}</button></nav><div class="aside-note">本机工作台 · P1<br>仅处理自有或已授权素材<br>云端模型未启用</div></aside>
  <main>
   <header><div><p class="eyebrow">PRODUCTION WORKSPACE</p><h1>{{view}}</h1></div><span class="health">{{health}}</span></header>
   <p v-if="error" class="error" role="alert">{{error}} <button @click="error=''">关闭</button></p>
   <div class="projectbar"><label>当前项目 <select v-model="selected" @change="changeProject"><option value="">选择项目</option><option v-for="p in projects" :key="p.id" :value="p.id">{{p.name}}</option></select></label><span v-if="busy" role="status">正在提交真实请求…</span><button :disabled="!selected||busy" @click="refresh">刷新状态</button></div>
   <template v-if="view==='素材资产中心'">
    <details :open="!projects.length"><summary>新建项目</summary><form class="create" @submit.prevent="create"><label>项目名称<input v-model="name" required maxlength="200" placeholder="输入项目名称"></label><label>项目说明<textarea v-model="description" maxlength="20000" placeholder="故事方向、授权范围或制作要求"></textarea></label><button class="primary" :disabled="busy||!name.trim()">创建项目</button></form></details>
    <div v-if="selected" class="workspace"><section><h2>原始素材 <span>{{assets.length}} 个</span></h2><label>授权来源<textarea v-model="authorization" maxlength="10000" placeholder="记录自有素材声明或授权方、协议编号及使用范围"></textarea></label><label class="upload">批量导入视频 / 音频<input type="file" multiple accept=".mp4,.mov,.mkv,.webm,.avi,.wav,.mp3" :disabled="busy||!authorization.trim()" @change="upload"></label><p class="hint">每文件上限 2 GiB。复制至原始素材区，处理流程不覆盖源文件。</p><div v-if="!assets.length" class="empty">尚无素材。填写授权来源后导入文件。</div><article v-for="asset in assets" :key="asset.id" class="asset"><div><strong>{{asset.name}}</strong><p>{{(asset.size_bytes/1024/1024).toFixed(2)}} MB · {{Object.keys(asset.media_info).length?'已解析':'待解析'}}</p><p>{{asset.authorization}}</p></div><div class="actions"><button @click="preview=asset.id">预览</button><button :disabled="busy" @click="probe(asset)">读取媒体信息</button></div></article></section><section class="preview"><h2>素材预览</h2><video v-if="preview" :key="preview" controls preload="metadata" :src="`/api/assets/${preview}/media`"></video><div v-else class="empty screen">选择素材开始预览</div><p class="hint">浏览器无法播放的编码可先读取媒体信息；格式转换将在 P2 提供。</p><h2>已记录费用</h2><p class="cost">{{cost||'等待读取'}}</p></section></div>
    <div v-else class="empty">创建一个项目，开始管理授权素材。</div>
   </template>
   <template v-else-if="view==='批量生产'"><h2>持久化任务队列</h2><p class="hint">当前支持媒体解析。独立 Worker 运行后处理任务；关闭页面不丢失任务。每 3 秒查询数据库状态。</p><p v-if="!selected" class="empty">请先选择项目。</p><p v-else-if="!tasks.length" class="empty">暂无任务，请在素材资产中心提交媒体解析。</p><article v-for="task in tasks" :key="task.id" class="task"><div><strong>{{assets.find(a=>a.id===task.asset_id)?.name||task.asset_id}}</strong><p class="mono">{{task.id}}</p><p v-if="task.error" class="error">{{task.error}}</p></div><span :class="['status',task.status]">{{labels[task.status]||task.status}}</span><span>尝试 {{task.attempt}}</span><button @click="logs(task)">日志</button><button v-if="task.status==='failed'" :disabled="busy" @click="retry(task)">安全重试</button></article><section v-if="logTask"><h2>事件日志</h2><p class="mono">{{logTask}}</p><p v-for="event in events" :key="event.id" class="log">{{new Date(event.created_at).toLocaleString('zh-CN')}} · 尝试 {{event.attempt}} · {{event.message}}</p><button @click="logs(tasks.find(t=>t.id===logTask)!)">刷新日志</button></section></template>
   <section v-else class="empty"><h2>{{view}}尚未实现</h2><p>本阶段提供项目、素材与解析任务基础。该入口将在后续阶段接入真实业务，当前没有生成或导出结果。</p></section>
  </main>
 </div>
</template>
