<script setup lang="ts">
import { computed, reactive, watch } from 'vue'

export interface ReviewFrame {index:number;time_ms:number}
export interface ReviewItem {key:string;label:string;expected:string}
export interface ChecklistEntry {key:string;frame:number}
export interface SavedChecklist {items:(ReviewItem & {frame:ReviewFrame})[]}

const props=defineProps<{items:ReviewItem[];frames:ReviewFrame[];saved?:SavedChecklist;editable:boolean}>()
const decisions=defineModel<ChecklistEntry[]|null>({default:null})
const emit=defineEmits<{seek:[frame:ReviewFrame]}>()
const choices=reactive<Record<string,number|undefined>>({})
const rows=computed(()=>props.items.map(item=>({ ...item, frame:props.frames.find(frame=>frame.index===
  (props.saved?.items.find(saved=>saved.key===item.key)?.frame.index ?? choices[item.key])) })))
const chosen=computed(()=>rows.value.flatMap(item=>item.frame ? [{key:item.key,frame:item.frame.index}] : []))
const seconds=(ms:number)=>`${(ms/1000).toFixed(3)} 秒`

watch(chosen,entries=>{
  decisions.value=entries.length>0 && entries.length===props.items.length ? entries : null
},{immediate:true})
</script>

<template>
  <section class="visual-checklist" aria-label="逐项视觉审核">
    <h3>逐项视觉审核</h3>
    <p v-if="saved" role="status">已记录 {{saved.items.length}} 项通过证据</p>
    <p v-else-if="editable" role="status">{{chosen.length}} / {{items.length}} 项已选择通过证据</p>
    <ul>
      <li v-for="item in rows" :key="item.key">
        <strong>{{item.label}}</strong>
        <p class="expected">{{item.expected}}</p>
        <div v-if="editable || item.frame" class="evidence-controls">
          <label v-if="editable">通过证据帧<select v-model="choices[item.key]" :aria-label="`通过证据帧 · ${item.label}`">
            <option :value="undefined">选择证据帧</option>
            <option v-for="frame in frames" :key="frame.index" :value="frame.index">{{seconds(frame.time_ms)}}</option>
          </select></label>
          <button v-if="item.frame" type="button" @click="emit('seek',item.frame)">定位证据 {{seconds(item.frame.time_ms)}}</button>
        </div>
      </li>
    </ul>
  </section>
</template>

<style scoped>
.visual-checklist { margin:12px 0;padding:12px;border:1px solid var(--line);border-radius:9px;background:var(--surface-panel);container-type:inline-size }
.visual-checklist h3,.visual-checklist p { margin:0 0 6px }
.visual-checklist ul { display:grid;list-style:none;margin:0;padding:0 }
.visual-checklist li { display:flex;flex-direction:column;padding:9px 0;border-top:1px solid var(--line-soft);min-width:0 }
.evidence-controls { display:flex;flex-wrap:wrap;align-items:end;gap:6px;margin-top:auto }
.evidence-controls label { flex:1 1 100px;min-width:0 }
.visual-checklist select { width:100%;min-width:0 }
.expected { white-space:pre-line;color:var(--ink-muted) }
@container (min-width:560px) {
  .visual-checklist ul { grid-template-columns:repeat(2,minmax(0,1fr));column-gap:16px }
}
</style>
