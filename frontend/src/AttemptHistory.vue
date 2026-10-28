<script setup lang="ts">
import { ref,watch } from 'vue'
const props=defineProps<{taskId:string}>()
interface Attempt {number:number;worker_id:string;status:string;stage:string;elapsed_seconds:number;error_code:string|null;error:string|null;checkpoints:{stage:string;at:string}[]}
const attempts=ref<Attempt[]>([]),error=ref(''),log=ref(''),busy=ref(false)
async function refresh(){busy.value=true;error.value='';const id=props.taskId;try{const response=await fetch(`/api/tasks/${id}/attempts`);if(!response.ok)throw new Error('无法读取尝试历史');const data=await response.json();if(id===props.taskId)attempts.value=data}catch(e){error.value=String(e)}finally{busy.value=false}}
async function logs(number:number){try{const response=await fetch(`/api/tasks/${props.taskId}/attempts/${number}/logs`);const data=await response.json();if(!response.ok)throw new Error(data.detail);log.value=(data.truncated?'仅显示最后 64 KiB\n':'')+(data.text||'FFmpeg 日志为空（没有警告输出）')}catch(e){error.value=String(e)}}
watch(()=>props.taskId,()=>{attempts.value=[];log.value='';void refresh()},{immediate:true})
</script>
<template>
 <div class="attempt-history"><div class="actions"><h2>执行尝试与检查点</h2><button :disabled="busy" @click="refresh">刷新尝试历史</button></div><p v-if="error" class="error">{{error}}</p><p v-if="!busy&&!attempts.length" class="hint">尚无 P3 执行尝试。旧任务不会伪造补录历史。</p>
 <details v-for="a in attempts" :key="a.number"><summary>尝试 {{a.number}} · {{a.status}} · {{a.elapsed_seconds.toFixed(1)}} 秒</summary><p class="mono">Worker {{a.worker_id}}</p><p v-if="a.error" class="error">{{a.error_code}} · {{a.error}}</p><ol><li v-for="(point,index) in a.checkpoints" :key="index">{{point.stage}} · {{new Date(point.at).toLocaleString('zh-CN')}}</li></ol><button @click="logs(a.number)">读取此尝试的 FFmpeg 日志</button></details><pre v-if="log" class="log-tail">{{log}}</pre></div>
</template>
