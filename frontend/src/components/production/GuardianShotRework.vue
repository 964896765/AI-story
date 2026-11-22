<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api, post } from '../../services/api'
import { useWorkspace } from '../../router/workspace'
import type { VersionRef } from '../../types/workbench'

interface TimelineOption extends VersionRef { profile:string }
interface ReworkJob { id:string;status:string }
const props=defineProps<{
  projectId:string;seriesVersionId:string;shotId:string;frames:number;sourceIds:string[];
  candidateId?:string;candidateAspect?:string
}>()
const emit=defineEmits<{queued:[id:string]}>()
const { workbench, link }=useWorkspace()
const source=ref(props.sourceIds[0] || ''), aspect=ref(props.candidateAspect || 'portrait')
const preset=ref('push_in'), reason=ref(''), note=ref('')
const busy=ref(false), error=ref(''), notice=ref('')
const editing=ref(false), options=ref<TimelineOption[]>([]), timeline=ref(''), newVersion=ref('')
const editRoot=computed(()=>`/timeline/projects/${props.projectId}/shot-replacements`)
const choices=computed(()=>options.value.filter(item=>item.profile===props.candidateAspect))
let requestKey={body:'',id:''}

function keyFor(body:object) {
  const value=JSON.stringify(body)
  if (requestKey.body!==value) requestKey={body:value,id:crypto.randomUUID()}
  return requestKey.id
}

async function queue() {
  if (busy.value || !reason.value.trim()) return
  const body={series_version_id:props.seriesVersionId,shot_id:props.shotId,asset_id:source.value,
    aspect:aspect.value,preset:preset.value,reason:reason.value.trim()}
  busy.value=true; error.value=''; notice.value=''
  try {
    const result=await post<ReworkJob>(`/generation/projects/${props.projectId}/shot-reworks`,{...body,idempotency_key:keyFor(body)})
    emit('queued',result.id)
    notice.value='已提交单镜头返工候选。'
    reason.value=''
    requestKey={body:'',id:''}
  } catch (failure) { error.value=String(failure) }
  finally { busy.value=false }
}

watch(()=>props.candidateId,()=>{
  editing.value=false; timeline.value=''; newVersion.value=''; options.value=[]; note.value=''
})

async function loadTimelines() {
  const id=props.candidateId
  busy.value=true; error.value=''; notice.value=''
  try {
    const params=new URLSearchParams({series_version_id:props.seriesVersionId,shot_id:props.shotId})
    const result=await api<TimelineOption[]>(`${editRoot.value}/options?${params}`)
    if (props.candidateId!==id) return
    options.value=result; timeline.value=''; editing.value=true
  } catch (failure) { error.value=String(failure) }
  finally { busy.value=false }
}

async function replace() {
  if (busy.value || !props.candidateId || !note.value.trim()) return
  const body={series_version_id:props.seriesVersionId,shot_id:props.shotId,
    timeline_version_id:timeline.value,candidate_id:props.candidateId,note:note.value.trim()}
  busy.value=true; error.value=''; notice.value=''
  try {
    const result=await post<VersionRef>(editRoot.value,{...body,idempotency_key:keyFor(body)})
    newVersion.value=result.version_id
    editing.value=false
    notice.value=`已保存时间轴 v${result.version}，可打开核对。`
    requestKey={body:'',id:''}
  } catch (failure) { error.value=String(failure) }
  finally { busy.value=false }
}
</script>

<template>
  <div class="rework-actions">
    <details>
      <summary>制作单镜头返工候选</summary>
      <form class="shot-form" @submit.prevent="queue">
        <p class="hint">合同固定 {{frames}} 帧 · 外部模型费用 ¥0。候选须人工审核并采纳。</p>
        <label>返工参考图<select v-model="source" required>
          <option v-for="id in sourceIds" :key="id" :value="id">{{workbench.assets.find(item=>item.id===id)?.name || id}}</option>
        </select></label>
        <label>返工画幅<select v-model="aspect"><option value="portrait">9:16</option><option value="landscape">16:9</option><option value="square">1:1</option></select></label>
        <label>返工运镜<select v-model="preset"><option value="push_in">推进</option><option value="pull_out">拉远</option><option value="pan_right">向右横移</option></select></label>
        <label>返工原因<textarea v-model="reason" required maxlength="2000" rows="2"></textarea></label>
        <button type="submit" :disabled="busy || !source || !reason.trim() || frames<12 || frames>240">提交单镜头返工</button>
        <p v-if="frames<12 || frames>240" class="hint">本机运镜支持 12 至 240 帧，可在分镜修订时长。</p>
      </form>
    </details>
    <button v-if="candidateId && !editing" type="button" :disabled="busy" @click="loadTimelines">将已采纳候选用于时间轴</button>
    <form v-if="editing" class="shot-form" @submit.prevent="replace">
      <p v-if="!choices.length" class="hint">暂无同画幅的当前时间轴。可在多轨工作台创建或调整时间轴。</p>
      <template v-else>
        <label>返工基线时间轴<select v-model="timeline" required>
          <option value="" disabled>选择当前时间轴版本</option>
          <option v-for="item in choices" :key="item.version_id" :value="item.version_id">{{item.title}} · v{{item.version}}</option>
        </select></label>
        <label>替换说明<textarea v-model="note" required maxlength="2000" rows="2"></textarea></label>
        <button type="submit" :disabled="busy || !timeline || !note.trim()">保存单镜头替换版本</button>
      </template>
    </form>
    <p v-if="notice" role="status">{{notice}}</p>
    <p v-if="error" class="error" role="alert">{{error}}</p>
    <RouterLink v-if="newVersion" :to="link('timeline',{timeline:newVersion})">打开返工时间轴</RouterLink>
  </div>
</template>

<style scoped>
.rework-actions,.shot-form { display:grid;gap:9px;min-width:0 }
.rework-actions { margin-top:12px }
.rework-actions summary { cursor:pointer;font-weight:600 }
.shot-form { margin-top:9px }
.shot-form p,.rework-actions p { margin:0;overflow-wrap:anywhere }
</style>
