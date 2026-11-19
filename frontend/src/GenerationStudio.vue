<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { request, statusLabels } from './analysisApi'

type Preset = 'push_in'|'pull_out'|'pan_right'
interface Candidate {
  id:string; asset_id:string; status:string; stage:string; progress:number; error:string|null
  cancel_requested:boolean; selected_asset_id:string|null; parameters:{preset:Preset;shot_id:string|null}
  output:{duration?:number; width?:number; height?:number; reused_from_task_id?:string}
}
const props=defineProps<{projectId:string;assets:{id:string;name:string}[]}>()
const emit=defineEmits<{assetsChanged:[]}>()
const images=computed(()=>props.assets.filter(item=>/\.(png|jpe?g|webp)$/i.test(item.name)))
const candidates=ref<Candidate[]>([]), assetId=ref(''), preview=ref(''), plan=ref(''), shot=ref('')
const aspect=ref('portrait'), frames=ref(72), presets=ref<Preset[]>(['push_in','pan_right'])
const labels:Record<Preset,string>={push_in:'推进',pull_out:'拉远',pan_right:'向右横移'}
const title=ref(''), review=ref(''), notice=ref(''), error=ref(''), busy=ref(false)
const modeList=ref<{id:string; available:boolean; label:string}[]>([])
const keys=new Map<string,string>()
let timer:ReturnType<typeof setInterval>|undefined
let refreshing=false
const base=`/generation/projects/${props.projectId}`
const selected=computed(()=>candidates.value.find(item=>item.id===preview.value))

async function run(action:()=>Promise<void>){
  busy.value=true
  error.value=''
  notice.value=''
  try{await action()}catch(failure){error.value=String(failure)}finally{busy.value=false}
}
async function refresh(){
  if(!props.projectId || refreshing)return
  refreshing=true
  try{candidates.value=await request<Candidate[]>(base+'/candidates')}finally{refreshing=false}
}
async function submit(){
  await run(async()=>{
    const body={asset_id:assetId.value,story_version_id:plan.value.trim()||null,shot_id:shot.value.trim()||null,
      candidates:presets.value.map(preset=>({preset,aspect:aspect.value,frames:frames.value}))}
    const signature=JSON.stringify(body)
    if(!keys.has(signature))keys.set(signature,crypto.randomUUID())
    const created=await request<Candidate[]>(base+'/still-motion',{...body,idempotency_key:keys.get(signature)})
    keys.delete(signature)
    await refresh()
    notice.value=`已排队 ${created.length} 个本地候选`
  })
}
function open(candidate:Candidate){
  preview.value=candidate.id
  title.value=(props.assets.find(asset=>asset.id===candidate.asset_id)?.name.split('.').slice(0,-1).join('.') || '静图')+' · '+labels[candidate.parameters.preset]
  review.value=''
}
async function accept(){
  const item=selected.value
  if(!item)return
  await run(async()=>{
    const asset=await request<{name:string}>('/generation/candidates/'+item.id+'/select',{title:title.value,note:review.value})
    await refresh()
    emit('assetsChanged')
    notice.value=`已采纳 ${asset.name}，可在智能二创中选择`
  })
}
async function taskAction(candidate:Candidate,action:'retry'|'cancel'){
  await run(async()=>{
    await request(`/tasks/${candidate.id}/${action}`,{})
    await refresh()
  })
}
onMounted(()=>{
  void run(async()=>{
    modeList.value=(await request<{modes:typeof modeList.value}>('/generation/capabilities')).modes
    await refresh()
  })
  timer=setInterval(()=>{if(!busy.value)void refresh().catch(failure=>{error.value=String(failure)})},3000)
})
onUnmounted(()=>clearInterval(timer))
</script>

<template>
  <p v-if="!projectId" class="empty">选择项目以制作素材候选。</p>
  <div v-else class="generation-workbench">
    <p v-if="error" role="alert" class="error">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="workspace">
      <section>
        <h2>本地静图运镜</h2>
        <p class="hint">本机 CPU 输出 24 fps 的无声 MP4，外部调用费用 ¥0。<span v-if="modeList.length">{{ modeList.filter(mode=>!mode.available).map(mode=>mode.label).join('、') }}待接入。</span></p>
        <form class="create" @submit.prevent="submit">
          <label>参考图片<select v-model="assetId" required>
            <option value="">选择项目授权图片</option><option v-for="asset in images" :key="asset.id" :value="asset.id">{{ asset.name }}</option>
          </select></label>
          <div class="editor-grid">
            <label>画幅<select v-model="aspect"><option value="portrait">9:16</option><option value="landscape">16:9</option><option value="square">1:1</option></select></label>
            <label>成片帧数<input v-model.number="frames" required type="number" min="12" max="240"></label>
          </div>
          <p class="hint">时长 {{ (frames/24).toFixed(2) }} 秒。画面居中裁剪至目标画幅。</p>
          <fieldset>
            <legend>候选运镜</legend>
            <label v-for="(label,key) in labels" :key="key" class="check"><input v-model="presets" :value="key" type="checkbox">{{ label }}</label>
          </fieldset>
          <details>
            <summary>固定已批准镜头</summary>
            <label>制作计划版本 ID<input v-model="plan" maxlength="36"></label>
            <label>稳定镜头 ID<input v-model="shot" maxlength="48"></label>
          </details>
          <button class="primary" :disabled="busy || !assetId || !presets.length">{{ busy ? '处理中' : '提交运镜候选' }}</button>
        </form>
      </section>
      <section>
        <h2>候选预览</h2>
        <video v-if="selected?.status==='succeeded'" :key="selected.id" controls preload="metadata" :src="`/api/generation/candidates/${selected.id}/video`"></video>
        <p v-else class="empty">从记录中选择已验证候选。</p>
        <p v-if="selected?.selected_asset_id">已采纳为项目素材。</p>
        <form v-else-if="selected?.status==='succeeded'" class="create" @submit.prevent="accept">
          <label>素材标题<input v-model="title" required maxlength="200"></label>
          <label>采纳说明<textarea v-model="review" required maxlength="2000"></textarea></label>
          <button class="primary" :disabled="busy || !title.trim() || !review.trim()">采纳为视频素材</button>
        </form>
      </section>
    </div>
    <section>
      <div class="actions"><h2>候选记录</h2><button :disabled="busy" @click="run(refresh)">刷新候选</button></div>
      <p v-if="!candidates.length" class="hint">暂无候选。</p>
      <article v-for="item in candidates" :key="item.id" class="task">
        <div>
          <strong>{{ labels[item.parameters.preset] }} · {{ assets.find(asset=>asset.id===item.asset_id)?.name }}</strong>
          <p v-if="item.parameters.shot_id" class="mono">{{ item.parameters.shot_id }}</p>
          <p>{{ statusLabels[item.status] || item.status }} · {{ statusLabels[item.stage] || item.stage }}</p>
          <p v-if="item.status==='succeeded'">{{ item.output.width }} × {{ item.output.height }} · {{ item.output.duration?.toFixed(2) }} 秒<span v-if="item.output.reused_from_task_id"> · 已核验复用</span></p>
          <p v-if="item.error" class="error">{{ item.error }}</p>
        </div>
        <button v-if="item.status==='succeeded'" :aria-pressed="preview===item.id" @click="open(item)">预览{{ labels[item.parameters.preset] }}</button>
        <button v-if="['queued','running'].includes(item.status)" :disabled="busy || item.cancel_requested" @click="taskAction(item,'cancel')">取消</button>
        <button v-if="['failed','cancelled'].includes(item.status)" :disabled="busy" @click="taskAction(item,'retry')">重试</button>
      </article>
    </section>
  </div>
</template>

<style scoped>
.generation-workbench { display:grid; gap:18px }
.generation-workbench fieldset,.generation-workbench details { margin:0 }
</style>
