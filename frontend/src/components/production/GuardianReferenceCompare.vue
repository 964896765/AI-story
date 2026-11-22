<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { api } from '../../services/api'
import GuardianVisualChecklist, { type ReviewFrame, type ReviewItem, type ChecklistEntry, type SavedChecklist } from './GuardianVisualChecklist.vue'

interface Reference {
  index:number; role:'character'|'scene'|'style'; title:string; version_id:string|null; version_number:number|null
}
interface Manifest {contract_sha256:string;visual:string;references:Reference[];review_items?:ReviewItem[]}
export interface ComparisonInput {reference:number;frame:number}
export interface SavedComparison {reference:Reference;frame:ReviewFrame}

const props=defineProps<{candidateId:string;frames:ReviewFrame[];saved?:SavedComparison;editable?:boolean;attached?:ComparisonInput|null;
  checklistApproval?:boolean;savedChecklist?:SavedChecklist}>()
const decisions=defineModel<ChecklistEntry[]|null>('checklist',{default:null})
const emit=defineEmits<{attach:[comparison:ComparisonInput];detach:[];seek:[frame:ReviewFrame]}>()
const manifest=ref<Manifest|null>(null), failure=ref(''), loading=ref(true)
const referenceIndex=ref(0), frameIndex=ref<number>()
const referenceLoaded=ref(false), frameLoaded=ref(false), referenceError=ref(false), frameError=ref(false)
const roles={character:'角色',scene:'场景',style:'风格'}
const title=(item:Reference)=>item.role==='style' ? item.title : `${roles[item.role]} · ${item.title} v${item.version_number}`
const seconds=(ms:number)=>`${(ms/1000).toFixed(3)} 秒`
const reference=computed(()=>manifest.value?.references.find(item=>item.index===referenceIndex.value))
const frame=computed(()=>props.frames.find(item=>item.index===frameIndex.value))
const reviewItems=computed(()=>props.savedChecklist?.items || manifest.value?.review_items || [])
const target=computed(()=>props.saved || (props.attached && {
  reference:manifest.value?.references.find(item=>item.index===props.attached?.reference),
  frame:props.frames.find(item=>item.index===props.attached?.frame),
}))
const candidatePath=computed(()=>`/generation/candidates/${props.candidateId}`)
const referenceUrl=computed(()=>`/api${candidatePath.value}/guardian-references/${referenceIndex.value}`)
const frameUrl=computed(()=>`/api${candidatePath.value}/guardian-frames/${frameIndex.value}`)

watch(candidatePath,async(path,_,onCleanup)=>{
  const controller=new AbortController()
  onCleanup(()=>controller.abort())
  loading.value=true;failure.value='';manifest.value=null
  referenceIndex.value=props.saved?.reference.index ?? 0
  frameIndex.value=props.saved?.frame.index ?? props.frames[Math.floor(props.frames.length/2)]?.index
  try {
    const data=await api<Manifest>(`${path}/guardian-references`,{signal:controller.signal})
    if (!controller.signal.aborted) manifest.value=data
  } catch (error) {
    if (!controller.signal.aborted) failure.value=(error as Error).message
  } finally {
    if (!controller.signal.aborted) loading.value=false
  }
},{immediate:true})
watch(referenceUrl,()=>{referenceLoaded.value=false;referenceError.value=false},{flush:'sync'})
watch(frameUrl,()=>{frameLoaded.value=false;frameError.value=false},{flush:'sync'})
</script>

<template>
  <section class="reference-comparison" aria-label="固定参考对照">
    <h3>固定参考对照</h3>
    <p v-if="loading" role="status">正在读取批准镜头的参考图…</p>
    <p v-else-if="failure" class="error" role="alert">{{failure}}</p>
    <template v-else-if="manifest">
      <p v-if="manifest.visual" class="hint">镜头要求 · {{manifest.visual}}</p>
      <p v-if="!manifest.references.length || !frames.length" class="empty">此候选缺少可对照的固定参考图或证据帧。</p>
      <template v-else>
        <div class="comparison-grid">
          <div>
            <label>固定参考图<select v-model="referenceIndex">
              <option v-for="item in manifest.references" :key="item.index" :value="item.index">{{title(item)}} · 图 {{item.index+1}}</option>
            </select></label>
            <img v-if="reference" :key="referenceUrl" :src="referenceUrl" :alt="title(reference)" class="reference-image"
              @load="referenceLoaded=true" @error="referenceLoaded=false;referenceError=true">
          </div>
          <div>
            <label>候选对照帧<select v-model="frameIndex">
              <option v-for="item in frames" :key="item.index" :value="item.index">{{seconds(item.time_ms)}}</option>
            </select></label>
            <img v-if="frame" :key="frameUrl" :src="frameUrl" :alt="`候选证据 ${seconds(frame.time_ms)}`" class="comparison-frame"
              @load="frameLoaded=true" @error="frameLoaded=false;frameError=true">
          </div>
        </div>
        <p v-if="referenceError || frameError" class="error" role="alert">对照图无法读取或未通过完整性检查。</p>
        <div v-if="editable" class="actions">
          <button v-if="frame" type="button" @click="emit('seek',frame)">预览对照时点</button>
          <button v-if="reference && frame" type="button" :disabled="!referenceLoaded || !frameLoaded"
            @click="emit('attach',{reference:reference.index,frame:frame.index})">附到内容审核</button>
          <button v-if="attached" type="button" @click="emit('detach')">移除审核附件</button>
        </div>
        <p v-if="target && target.reference && target.frame" class="attached-comparison" role="status">
          {{saved?'已记录对照':'已选为审核附件'}} · {{title(target.reference)}} · {{seconds(target.frame.time_ms)}}
        </p>
      </template>
    </template>
  </section>
  <GuardianVisualChecklist v-if="reviewItems.length" v-model="decisions" :items="reviewItems" :frames="frames"
    :saved="savedChecklist" :editable="!!checklistApproval" @seek="emit('seek',$event)" />
</template>

<style scoped>
.reference-comparison { padding:12px;min-width:0;margin:12px 0;border:1px solid var(--line);border-radius:9px;background:var(--surface-panel) }
.reference-comparison h3 { margin:0 0 6px }
.reference-comparison p { margin:6px 0 }
.comparison-grid { display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin:9px 0 }
.comparison-grid > div { min-width:0 }
.comparison-grid select { width:100%;min-width:0 }
.comparison-grid img { display:block;width:100%;aspect-ratio:1.25;object-fit:contain;margin:6px 0 0;background:var(--surface-base);border:1px solid var(--line);border-radius:6px }
.attached-comparison { color:var(--accent);font-size:12px }
</style>
