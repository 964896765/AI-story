<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../../services/api'
import type { VersionRef } from '../../types/workbench'

export interface BatchPolicy {
  require_audio:boolean
  require_subtitles:boolean
  black_ms?:number
  freeze_ms?:number
  silence_ms?:number
  silence_db?:number
  min_integrated_lufs?:number|null
  max_true_peak_dbtp?:number|null
}
export interface BatchOperation {
  action:'batch'
  plan_version_id:string
  previous_run_id:string|null
  timelines:{number:number;timeline_version_id:string}[]
  policy:BatchPolicy
  recheck_quality:boolean
}
export interface RunOption {
  id:string
  plan_version_id:string
  status:string
  episode_count:number
  created_at:string
  policy:BatchPolicy
}
interface Options {
  episodes:{number:number;title:string}[]
  timelines:(VersionRef & {episode:number|null})[]
}

const props=defineProps<{projectId:string;runs:RunOption[]}>()
const operation=defineModel<BatchOperation|null>({required:true})
const plans=ref<VersionRef[]>([])
const planId=ref(''), previousId=ref('')
const previous=computed(()=>props.runs.find(item=>item.id===previousId.value))
const options=ref<Options|null>(null)
const selected=ref<Record<number,string>>({})
const requireAudio=ref(false), requireSubtitles=ref(false), recheck=ref(false)
const error=ref(''), loading=ref(false)
const endpoint=computed(()=>`/director/projects/${props.projectId}/batch-options`)
const label=(item:VersionRef)=>`${item.title} · v${item.version}`

watch(endpoint, async (path, _, onCleanup) => {
  const control=new AbortController()
  onCleanup(()=>control.abort())
  try {
    plans.value=await api<VersionRef[]>(path,{signal:control.signal})
  } catch (failure) {
    if (!control.signal.aborted) error.value=String(failure)
  }
}, {immediate:true})

watch(previousId, () => {
  const item=previous.value
  planId.value=item?.plan_version_id || ''
  requireAudio.value=item?.policy.require_audio ?? false
  requireSubtitles.value=item?.policy.require_subtitles ?? false
  recheck.value=false
})

watch([planId,previousId], async ([id], _, onCleanup) => {
  options.value=null
  selected.value={}
  loading.value=Boolean(id)
  if (!id) return
  const control=new AbortController()
  onCleanup(()=>control.abort())
  error.value=''
  try {
    const result=await api<Options>(`${endpoint.value}/${id}`,{signal:control.signal})
    if (!control.signal.aborted) options.value=result
  } catch (failure) {
    if (!control.signal.aborted) error.value=String(failure)
  } finally {
    if (!control.signal.aborted) loading.value=false
  }
})

watch(computed<BatchOperation|null>(() => {
  if (!planId.value || !options.value?.episodes.length) return null
  const changes=options.value.episodes.flatMap(({number})=>{
    const id=selected.value[number]
    return id ? [{number,timeline_version_id:id}] : []
  })
  const base=previous.value?.policy
  const policy={...base,require_audio:requireAudio.value,require_subtitles:requireSubtitles.value}
  if (previous.value) {
    if (!changes.length && !recheck.value && base?.require_audio===policy.require_audio &&
        base?.require_subtitles===policy.require_subtitles) return null
  } else if (changes.length!==options.value.episodes.length) return null
  return {action:'batch',plan_version_id:planId.value,previous_run_id:previousId.value || null,
    timelines:changes,policy,recheck_quality:recheck.value}
}), value=>{operation.value=value}, {immediate:true})
</script>

<template>
  <label>基于既有批次<select v-model="previousId">
    <option value="">创建新批次</option>
    <option v-for="item in runs.filter(run=>run.status!=='processing')" :key="item.id" :value="item.id">{{new Date(item.created_at).toLocaleString()}} · {{item.episode_count}} 集 · {{item.id.slice(0,8)}}</option>
  </select></label>
  <label v-if="!previousId">已批准制作计划<select v-model="planId" required>
    <option value="" disabled>{{plans.length?'选择固定计划':'暂无已批准计划'}}</option>
    <option v-for="item in plans" :key="item.version_id" :value="item.version_id">{{label(item)}}</option>
  </select></label>
  <p v-if="loading" class="hint" role="status">正在读取固定分集和时间轴…</p>
  <p v-if="error" class="error" role="alert">{{error}}</p>
  <template v-if="options">
    <p v-if="!options.timelines.length && !previousId" class="hint">请先保存引用当前计划的分集时间轴。</p>
    <label v-for="episode in options.episodes" :key="episode.number">
      第 {{episode.number}} 集时间轴
      <select v-model="selected[episode.number]" :required="!previousId">
        <option :value="undefined">{{previousId?'沿用上一批次':'选择固定版本'}}</option>
        <option v-for="item in options.timelines.filter(item=>item.episode==null || item.episode===episode.number)"
          :key="item.version_id" :value="item.version_id">{{label(item)}}</option>
      </select>
    </label>
    <div class="batch-policy">
      <label><input v-model="requireAudio" type="checkbox"> 要求音轨</label>
      <label><input v-model="requireSubtitles" type="checkbox"> 要求字幕</label>
      <label v-if="previousId"><input v-model="recheck" type="checkbox"> 对复用成片重新质检</label>
    </div>
  </template>
</template>

<style scoped>
.batch-policy { display:grid;gap:7px }
.batch-policy label { display:flex;align-items:center;gap:7px }
.batch-policy input { width:auto }
</style>
