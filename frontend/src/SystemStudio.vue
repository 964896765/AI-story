<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { request, statusLabels } from './analysisApi'

interface Metrics {
  observed_at:string;os:string;logical_cpus:number|null;database_revision:string
  projects:number;recorded_asset_count:number;recorded_asset_bytes:number;observed_attempts:number;observed_task_seconds:number
  disk:{total:number;used:number;free:number}|null
  workers:{id:string;state:string;online:boolean;last_seen:string}[]
  tasks:{kind:string;status:string;count:number}[]
}
const metrics=ref<Metrics|null>(null), error=ref(''), busy=ref(false)
const workerCount=computed(()=>metrics.value?.workers.filter(worker=>worker.online).length||0)
let timer:ReturnType<typeof setInterval>|undefined
const names:Record<string,string>={probe:'媒体基础探测',analyze:'智能解析',render:'视频剪辑',adapt:'剧情改编',
  still_motion:'静图运镜',local_voice:'本机配音',timeline_render:'多轨渲染',qc_review:'技术质检',delivery:'整剧交付',promotion:'推广包'}
const bytes=(n:number)=>n>=1024**3?(n/(1024**3)).toFixed(2)+' GiB':(n/(1024**2)).toFixed(2)+' MiB'
async function refresh(){
  if(busy.value)return
  busy.value=true
  try{metrics.value=await request<Metrics>('/system/metrics');error.value=''}catch(failure){error.value=String(failure)}
  finally{busy.value=false}
}
onMounted(()=>{void refresh();timer=setInterval(()=>void refresh(),10000)})
onUnmounted(()=>clearInterval(timer))
</script>
<template>
  <section>
    <div class="actions"><h2>本机运行状态</h2><button :disabled="busy" @click="refresh">刷新诊断</button></div>
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="metrics" class="hint">最近读取 {{ new Date(metrics.observed_at).toLocaleString('zh-CN') }}</p>
    <template v-if="metrics">
      <dl class="diagnostics">
        <div><dt>数据库迁移</dt><dd>{{ metrics.database_revision }}</dd></div>
        <div><dt>在线 Worker</dt><dd>{{ workerCount }}</dd></div>
        <div><dt>系统 / 逻辑 CPU</dt><dd>{{ metrics.os }} / {{ metrics.logical_cpus ?? '未知' }}</dd></div>
        <div><dt>数据卷剩余空间</dt><dd>{{ metrics.disk ? bytes(metrics.disk.free)+' / '+bytes(metrics.disk.total) : '未知' }}</dd></div>
        <div><dt>当前数据库项目</dt><dd>{{ metrics.projects }}</dd></div>
        <div><dt>已登记素材大小</dt><dd>{{ metrics.recorded_asset_count }} 条 · {{ bytes(metrics.recorded_asset_bytes) }}</dd></div>
        <div><dt>已记录任务尝试</dt><dd>{{ metrics.observed_attempts }} 次 · {{ metrics.observed_task_seconds.toFixed(1) }} 秒</dd></div>
      </dl>
      <h2>任务状态计数</h2>
      <div class="row" v-for="item in metrics.tasks" :key="item.kind+':'+item.status">
        <span>{{ names[item.kind] || item.kind }} · {{ statusLabels[item.status] || item.status }}</span><strong>{{ item.count }}</strong>
      </div>
      <p v-if="!metrics.tasks.length" class="hint">此数据库暂无任务。</p>
    </template>
    <p v-else-if="busy" role="status">正在读取本机诊断。</p>
  </section>
</template>
<style scoped>
.diagnostics { display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:14px }
.diagnostics div { border:1px solid #343e4e;border-radius:6px;padding:12px }
dt { color:#abb8c8;font-size:13px }
dd { margin:9px 0 0 }
.row { display:flex;justify-content:space-between;gap:12px;padding:10px 0;border-top:1px solid #343e4e }
</style>
