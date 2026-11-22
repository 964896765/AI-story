<script setup lang="ts">
import { ref,onMounted,onUnmounted,watch } from 'vue'
const props=defineProps<{projectId:string}>()
interface Worker {id:string;pid:number;state:string;online:boolean;last_seen:string;error:string|null}
const queue=ref<{paused:boolean;concurrency:number;workers:Worker[]}|null>(null)
const summary=ref<{counts:Record<string,number>;attempts:number;observed_processing_seconds:number;recorded_cents:number;note:string}|null>(null)
const error=ref(''),busy=ref(false)
let timer:ReturnType<typeof setInterval>|undefined,refreshing=false
async function get(path:string,options:RequestInit={}){const response=await fetch('/api'+path,options);const data=await response.json();if(!response.ok)throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail));return data}
async function refresh(){if(refreshing)return;refreshing=true;const project=props.projectId;try{queue.value=await get('/queue');const data=project?await get(`/projects/${project}/production-summary`):null;if(project===props.projectId)summary.value=data;error.value=''}catch(e){error.value=String(e)}finally{refreshing=false}}
async function toggle(){busy.value=true;try{await get('/queue',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paused:!queue.value?.paused})});await refresh()}catch(e){error.value=String(e)}finally{busy.value=false}}
watch(()=>props.projectId,()=>{summary.value=null;void refresh()})
onMounted(()=>{void refresh();timer=setInterval(refresh,3000)})
onUnmounted(()=>clearInterval(timer))
</script>
<template>
 <section class="queue-panel">
  <div class="queue-heading">
    <div><h2>队列与 Worker</h2><p v-if="queue" class="hint">{{queue.paused?'已暂停领取新任务':'允许领取任务'}} · {{queue.workers.filter(w=>w.online).length}} 个 Worker 在线 · 并发上限 {{queue.concurrency}}</p></div>
    <button :disabled="busy||!queue" @click="toggle">{{queue?.paused?'恢复队列':'暂停队列'}}</button>
  </div>
  <p v-if="error" class="error" role="alert">{{error}}</p>
  <p v-if="queue&&!queue.workers.some(w=>w.online)" class="error">当前没有在线 Worker，新任务将保留在队列中。</p>
  <div v-if="summary" class="queue-metrics">
    <div v-for="state in [{key:'queued',label:'排队'},{key:'running',label:'运行'},{key:'succeeded',label:'完成'},{key:'failed',label:'失败'},{key:'cancelled',label:'取消'}]" :key="state.key">
      <span>{{state.label}}</span><strong :class="state.key">{{summary.counts[state.key]||0}}</strong>
    </div>
  </div>
  <details v-if="queue" class="queue-workers">
    <summary>进程与心跳</summary>
    <p class="hint">暂停队列时，已在运行的任务会继续处理。超过 15 秒未收到心跳的 Worker 显示为离线。</p>
    <div v-for="w in queue.workers.slice(0,4)" :key="w.id" class="worker-row"><span>{{w.online?'在线':'离线'}} · PID {{w.pid}} · {{w.state==='busy'?'执行中':w.state==='idle'?'空闲':w.state}}</span><span class="hint">最近心跳 {{new Date(w.last_seen).toLocaleString('zh-CN')}}</span><p v-if="w.error" class="error">{{w.error}}</p></div>
    <p v-if="summary" class="hint">执行尝试 {{summary.attempts}} 次 · 已观测处理 {{summary.observed_processing_seconds.toFixed(1)}} 秒 · 已入账 API 费用 ¥{{(summary.recorded_cents/100).toFixed(2)}}。{{summary.note}}</p>
  </details>
 </section>
</template>
<style scoped>
.queue-heading { display:flex; justify-content:space-between; align-items:start; flex-wrap:wrap; gap:10px }
.queue-heading h2 { margin-bottom:4px }
.queue-metrics { display:grid; grid-template-columns:repeat(5,minmax(0,1fr)); gap:6px; margin:4px 0 12px }
.queue-metrics div { display:grid; gap:4px; padding:8px 10px; background:var(--surface-raised); border:1px solid var(--line-soft); border-radius:7px }
.queue-metrics span { color:var(--ink-muted); font-size:12px }
.queue-metrics strong { font-size:21px; font-variant-numeric:tabular-nums }
.queue-workers { margin:0; padding:9px 11px }
.queue-workers p { margin:7px 0 }
@media(max-width:500px) { .queue-metrics div { padding:5px 6px } }
</style>
