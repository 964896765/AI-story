<script setup lang="ts">
import { computed, ref, watch } from 'vue'
const props=defineProps<{projectId:string;assets:{id:string;name:string}[]}>()
const emit=defineEmits<{submitted:[]}>()
const chosen=ref<string[]>([]),start=ref(0),end=ref<number|''>(''),duration=ref<number|''>('')
const aspect=ref('original'),strategy=ref('pad'),resolution=ref('source'),format=ref('mp4'),crf=ref(18)
const audioMode=ref('keep'),audio=ref(''),subtitle=ref(''),volume=ref(1),busy=ref(false),message=ref(''),error=ref('')
const keys=new Map<string,string>()
const videos=computed(()=>props.assets.filter(a=>/\.(mp4|mov|mkv|webm|avi)$/i.test(a.name)))
const subtitles=computed(()=>props.assets.filter(a=>/\.srt$/i.test(a.name)))
const audioAssets=computed(()=>props.assets.filter(a=>!/\.srt$/i.test(a.name)))
const storageKey=()=>`ai-story:p2:batch-keys:${props.projectId}`
function newBatch(){keys.clear();sessionStorage.removeItem(storageKey());message.value='已开始新批次；下次提交将新建任务。'}
watch(()=>props.projectId,()=>{chosen.value=[];audio.value='';subtitle.value='';keys.clear();message.value='';error.value='';try{for(const [signature,key] of Object.entries(JSON.parse(sessionStorage.getItem(storageKey())||'{}')))if(typeof key==='string')keys.set(signature,key)}catch{}},{immediate:true})
async function submit(){
 busy.value=true;message.value='';error.value=''
 const project=props.projectId
 const parameters={start:start.value,end:end.value===''?null:end.value,duration:duration.value===''?null:duration.value,aspect:aspect.value,strategy:strategy.value,resolution:resolution.value,format:format.value,crf:crf.value,audio_mode:audioMode.value,audio_asset_id:audioMode.value==='replace'?audio.value||null:null,subtitle_asset_id:subtitle.value||null,volume:volume.value}
 let count=0
 try{
  for(const assetId of chosen.value){
   const signature=JSON.stringify({project,assetId,parameters})
   if(!keys.has(signature)){keys.set(signature,crypto.randomUUID());sessionStorage.setItem(storageKey(),JSON.stringify(Object.fromEntries(keys)))}
   const response=await fetch(`/api/projects/${project}/tasks`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({asset_id:assetId,kind:'render',parameters,idempotency_key:keys.get(signature)})})
   if(!response.ok){const data=await response.json();throw new Error(typeof data.detail==='string'?data.detail:JSON.stringify(data.detail))}
   count++
  }
  message.value=`已确认 ${count} 项任务入队（同一批次重复提交会复用任务）。`
 }catch(e){error.value=`已提交 ${count} 项；${String(e)}。可修正后再次提交，已接收的相同任务不会重复创建。`}
 finally{busy.value=false;emit('submitted')}
}
</script>

<template>
 <section>
  <h2>批量剪辑与成片输出</h2>
  <p class="hint">选择授权视频并统一设置参数。字幕时间以裁剪后的片段 00:00 为起点；替换音轨从音频开头使用，过短补静音、过长截断。</p>
  <p v-if="!projectId" class="empty">请先选择项目。</p>
  <form v-else @submit.prevent="submit">
   <fieldset :disabled="busy"><legend>输入视频</legend><p v-if="!videos.length" class="hint">请先在素材资产中心导入视频。</p><label v-for="video in videos" :key="video.id" class="check"><input v-model="chosen" type="checkbox" :value="video.id">{{video.name}}</label></fieldset>
   <fieldset :disabled="busy"><legend>时间与画面</legend><div class="editor-grid">
    <label>开始时间（秒）<input v-model.number="start" type="number" min="0" max="86400" step="0.001" required></label>
    <label>结束时间（可空）<input v-model.number="end" type="number" min="0.001" max="86400" step="0.001" :disabled="duration!==''"></label>
    <label>裁剪时长（可空）<input v-model.number="duration" type="number" min="0.001" max="86400" step="0.001" :disabled="end!==''"></label>
    <label>画幅<select v-model="aspect"><option value="original">保留原画幅</option><option>9:16</option><option>16:9</option><option>1:1</option></select></label>
    <label>缩放策略<select v-model="strategy"><option value="pad">等比缩放并留黑边</option><option value="crop">等比缩放并居中裁切</option><option value="fit">仅等比缩放（输出尺寸随内容）</option></select></label>
    <label>分辨率<select v-model="resolution"><option value="source">沿用源尺寸基准</option><option value="720">720p / 短边 720</option><option value="1080">1080p / 短边 1080</option><option value="1440">1440p / 短边 1440</option><option value="2160">2160p / 短边 2160</option></select></label>
    <label>输出格式<select v-model="format"><option value="mp4">MP4 · H.264 / AAC</option><option value="mkv">MKV · H.264 / AAC</option></select></label>
    <label>CRF（越低画质越高）<input v-model.number="crf" type="number" min="0" max="28" required></label>
   </div><p class="hint">默认保留源画幅、帧率与尺寸基准，CRF 18 高画质重编码。画幅裁切会移除边缘；留边会缩小有效画面。最终尺寸取偶数。</p></fieldset>
   <fieldset :disabled="busy"><legend>字幕与声音</legend><div class="editor-grid">
    <label>SRT 字幕<select v-model="subtitle"><option value="">不烧录字幕</option><option v-for="a in subtitles" :key="a.id" :value="a.id">{{a.name}}</option></select></label>
    <label>音轨<select v-model="audioMode"><option value="keep">保留原音（无音轨则保持静音）</option><option value="replace">替换为用户音轨</option><option value="mute">移除音轨</option></select></label>
    <label v-if="audioMode==='replace'">替换音频<select v-model="audio" required><option value="">选择已导入音频或视频音轨</option><option v-for="a in audioAssets" :key="a.id" :value="a.id">{{a.name}}</option></select></label>
    <label v-if="audioMode!=='mute'">音量倍率<input v-model.number="volume" type="number" min="0" max="4" step="0.1" required></label>
   </div><p class="hint">SRT 须为 UTF-8，最大 2 MiB。在素材资产中心导入字幕或音轨并记录授权来源。</p></fieldset>
   <div class="actions"><button class="primary" :disabled="busy||!chosen.length">{{busy?'正在提交…':`提交 ${chosen.length} 项剪辑任务`}}</button><button type="button" :disabled="busy" @click="newBatch">开始新批次</button></div>
   <p v-if="error" role="alert" class="error">{{error}}</p><p v-if="message" role="status">{{message}}</p>
  </form>
 </section>
</template>
