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
  <div class="actions"><h2>队列与 Worker</h2><span v-if="queue">{{queue.paused?'已暂停领取新任务':'允许领取任务'}} · 并发上限 {{queue.concurrency}}</span><button :disabled="busy||!queue" @click="toggle">{{queue?.paused?'恢复队列':'暂停队列'}}</button></div>
  <p class="hint">暂停不会中断已在运行的任务。Worker 超过 15 秒未心跳会显示离线；下列信息来自数据库。</p>
  <p v-if="error" class="error" role="alert">{{error}}</p>
  <p v-if="queue&&!queue.workers.some(w=>w.online)" class="error">当前没有在线 Worker，新任务将保留在队列中。</p>
  <div v-for="w in queue?.workers.slice(0,4)" :key="w.id" class="worker-row"><span>{{w.online?'在线':'离线'}} · PID {{w.pid}} · {{w.state==='busy'?'执行中':w.state==='idle'?'空闲':w.state}}</span><span class="hint">最近心跳 {{new Date(w.last_seen).toLocaleString('zh-CN')}}</span><p v-if="w.error" class="error">{{w.error}}</p></div>
  <div v-if="summary" class="production-summary"><p>项目任务：排队 {{summary.counts.queued||0}} · 执行 {{summary.counts.running||0}} · 完成 {{summary.counts.succeeded||0}} · 失败 {{summary.counts.failed||0}} · 取消 {{summary.counts.cancelled||0}}</p><p>P3 执行尝试 {{summary.attempts}} 次 · 已观测处理 {{summary.observed_processing_seconds.toFixed(1)}} 秒 · 已入账 API 费用 ¥{{(summary.recorded_cents/100).toFixed(2)}}</p><p class="hint">{{summary.note}}</p></div>
 </section>
</template>
