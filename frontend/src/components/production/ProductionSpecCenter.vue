<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { api, post } from '../../services/api'
import { specLabels, specPath, type ProductionSettings, type ProductionSpec } from '../../types/productionSpec'
const props=defineProps<{projectId:string;initialVersion?:string;legacyNote?:string}>()
const path=specPath(props.projectId)
const blank:ProductionSettings={episode_count:null,episode_duration_ms:null,style:'',profile:null,
  width:null,height:null,fps:24,platform:'',region:'CN',budget_cents:0,budget_currency:'CNY',restrictions:'',imported_note:''}
type Change={key:keyof ProductionSettings;before:unknown;after:unknown;modules:string[]}
const form=reactive({...blank}), history=ref<ProductionSpec[]>([]), selected=ref<ProductionSpec|null>(null)
const compareId=ref(''), comparison=ref<{changes:Change[];affected_modules:string[];pinned_references:Record<string,number>}|null>(null)
const busy=ref(false),error=ref(''),notice=ref(''),confirmRestore=ref(false),more=ref(false),loaded=ref(false)
const head=computed(()=>history.value[0])
const isHistorical=computed(()=>!!selected.value && selected.value.id!==head.value?.id)
let lastRequest={signature:'',key:''}
function requestKey(payload:object) {
  const signature=JSON.stringify(payload)
  if(signature!==lastRequest.signature)lastRequest={signature,key:crypto.randomUUID()}
  return lastRequest.key
}
async function run(operation:()=>Promise<void>) {
  busy.value=true;error.value='';notice.value=''
  try {await operation()} catch(failure) {error.value=String(failure)} finally {busy.value=false}
}
function choose(spec:ProductionSpec|null) {
  selected.value=spec;Object.assign(form,blank,spec?.settings)
  compareId.value=history.value.find(item=>item.id!==spec?.id)?.id || ''
  comparison.value=null;confirmRestore.value=false
}
async function load() {
  const result=await api<{items:ProductionSpec[];has_more:boolean}>(path)
  history.value=result.items;more.value=result.has_more
  const match=props.initialVersion && (history.value.find(item=>item.id===props.initialVersion) ||
    await api<ProductionSpec>(path+'/'+encodeURIComponent(props.initialVersion)))
  choose(match || head.value || null)
  loaded.value=true
}
async function loadMore() {
  const result=await api<{items:ProductionSpec[];has_more:boolean}>(path+'?offset='+history.value.length)
  history.value.push(...result.items);more.value=result.has_more
}
function useProfile() {
  const sizes={portrait:[720,1280],landscape:[1280,720],square:[720,720]} as const
  if(form.profile) [form.width,form.height]=sizes[form.profile]
}
function copyNote() {
  form.imported_note=props.legacyNote || ''
  notice.value='已复制到草稿。保存后写入规格版本，浏览器原备注保留。'
}
async function publish(restore=false) {
  const numberOrNull=(value:number|null|string)=>typeof value==='number' ? value : null
  const data=restore ? {source_version_id:selected.value!.id} : {settings:{
    ...form,episode_count:numberOrNull(form.episode_count),episode_duration_ms:numberOrNull(form.episode_duration_ms),
    width:numberOrNull(form.width),height:numberOrNull(form.height),fps:numberOrNull(form.fps),
    budget_cents:numberOrNull(form.budget_cents),
  }}
  const payload={...data,expected_version:head.value?.version || 0}
  const result=await post<ProductionSpec>(path+(restore?'/restore':''),{...payload,idempotency_key:requestKey(payload)})
  const refreshed=await api<{items:ProductionSpec[];has_more:boolean}>(path)
  history.value=refreshed.items;more.value=refreshed.has_more;choose(history.value.find(item=>item.id===result.id) || result)
  notice.value=`已${restore?'恢复为':'保存'}规格 v${result.version}`
}
async function compare() {
  const params=new URLSearchParams({left:compareId.value,right:selected.value!.id})
  comparison.value=await api(path+'/compare?'+params)
}
onMounted(()=>void run(load))
</script>
<template>
  <section class="spec-center" aria-labelledby="project-spec-heading">
    <header><div><h2 id="project-spec-heading">项目制作规格</h2><p class="hint">保存时追加版本。已批准内容继续读取原规格。</p></div>
      <span v-if="head">当前 v{{head.version}}</span></header>
    <p v-if="notice" role="status">{{notice}}</p>
    <p v-if="error" class="error" role="alert">{{error}}</p>
    <button v-if="error && !loaded" type="button" @click="run(load)">重新读取</button>
    <div v-if="loaded" class="spec-layout">
      <form @submit.prevent="run(()=>publish())">
        <fieldset :disabled="busy || isHistorical">
          <div class="spec-fields">
            <label>计划集数<input v-model.number="form.episode_count" type="number" min="1" max="50"></label>
            <label>单集目标时长（毫秒）<input v-model.number="form.episode_duration_ms" type="number" min="500" max="600000"></label>
            <label class="wide">画风与美术<textarea v-model="form.style" maxlength="2000"></textarea></label>
            <label>画幅<select v-model="form.profile" @change="useProfile"><option :value="null">待填写</option><option value="portrait">9:16 竖屏</option><option value="landscape">16:9 横屏</option><option value="square">1:1 方形</option></select></label>
            <label>输出帧率<input v-model.number="form.fps" type="number" min="1" max="120"></label>
            <label>输出宽度<input v-model.number="form.width" type="number" min="2" max="8192"></label>
            <label>输出高度<input v-model.number="form.height" type="number" min="2" max="8192"></label>
            <label>发行平台标识<input v-model.trim="form.platform" maxlength="40" placeholder="例如 local-test"></label>
            <label>发行地域<input v-model.trim="form.region" maxlength="5" placeholder="CN 或 WORLD"></label>
            <label>制作预算（分）<input v-model.number="form.budget_cents" type="number" min="0" max="10000000000"></label>
            <label>币种<select v-model="form.budget_currency"><option>CNY</option><option>USD</option></select></label>
            <label class="wide">制作限制<textarea v-model="form.restrictions" maxlength="2000"></textarea></label>
            <div v-if="legacyNote || form.imported_note" class="wide">
              <button v-if="legacyNote && !form.imported_note" type="button" @click="copyNote">复制本机备注到规格草稿</button>
              <label v-if="form.imported_note">已复制的历史备注<textarea v-model="form.imported_note" maxlength="4000"></textarea></label>
            </div>
          </div>
          <button type="submit" class="primary">保存规格新版本</button>
        </fieldset>
      </form>
      <aside>
        <h3>版本历史</h3>
        <label v-if="history.length">查看规格版本<select :value="selected?.id" :disabled="busy" @change="choose(history.find(item=>item.id===($event.target as HTMLSelectElement).value) || null)">
          <option v-if="selected && !history.some(item=>item.id===selected?.id)" :value="selected.id">v{{selected.version}} · 历史版本</option>
          <option v-for="item in history" :key="item.id" :value="item.id">v{{item.version}} · {{new Date(item.created_at).toLocaleString()}}</option>
        </select></label>
        <button v-if="more" :disabled="busy" type="button" @click="run(loadMore)">查看更多版本</button>
        <p v-if="!selected" class="hint">当前项目尚未保存制作规格。</p>
        <template v-else>
          <p>SHA-256 <span class="mono hash">{{selected.sha256}}</span></p>
          <p v-if="selected.missing_fields.length" class="hint">待填写 {{selected.missing_fields.map(field=>specLabels[field as keyof ProductionSettings] || field).join('、')}}</p>
          <ul v-if="selected.compatibility_errors.length"><li v-for="issue in selected.compatibility_errors" :key="issue">{{issue}}</li></ul>
          <p v-if="!selected.missing_fields.length && !selected.compatibility_errors.length" class="hint">符合本机流程规格</p>
          <label v-if="history.length>1">比较基线<select v-model="compareId" @change="comparison=null">
            <option v-for="item in history.filter(item=>item.id!==selected?.id)" :key="item.id" :value="item.id">v{{item.version}}</option>
          </select></label>
          <button v-if="compareId" :disabled="busy" type="button" @click="run(compare)">比较规格与影响</button>
          <template v-if="comparison">
            <p>可能受影响 {{comparison.affected_modules.join('、') || '无业务字段变化'}}</p>
            <ul><li v-for="item in comparison.changes" :key="item.key">{{specLabels[item.key]}} · {{item.before ?? '未设置'}} → {{item.after ?? '未设置'}}</li></ul>
            <p class="hint">已有 {{Object.values(comparison.pinned_references).reduce((a,b)=>a+b,0)}} 条记录固定比较基线版本。</p>
          </template>
          <div v-if="isHistorical" class="actions">
            <button v-if="!confirmRestore" type="button" :disabled="busy" @click="confirmRestore=true">恢复历史规格</button>
            <button v-else type="button" :disabled="busy" @click="run(()=>publish(true))">确认恢复为新版本</button>
          </div>
        </template>
      </aside>
    </div>
  </section>
</template>
<style scoped>
.spec-center { grid-column:1/-1 }
.spec-center header { display:flex; justify-content:space-between; gap:12px }
.spec-center header h2,.spec-center header p { margin:0 0 5px }
.spec-layout { display:grid; grid-template-columns:minmax(0,2fr) minmax(230px,1fr); gap:18px;margin-top:12px }
.spec-fields { display:grid; grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-bottom:10px }
.spec-fields .wide { grid-column:1/-1 }
.spec-center fieldset { border:0;padding:0;margin:0;min-width:0 }
.spec-center aside { overflow-wrap:anywhere;border-left:1px solid var(--line);padding-left:14px;min-width:0 }
.hash { overflow-wrap:anywhere }
@media(max-width:760px) { .spec-layout { grid-template-columns:minmax(0,1fr) } .spec-center aside { border-left:0;padding-left:0 } }
</style>
