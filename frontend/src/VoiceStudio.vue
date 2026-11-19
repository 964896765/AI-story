<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { clock, request, statusLabels } from './analysisApi'

interface Voice { name:string; locale:string }
interface Edition { version_id:string; title:string; version:number; content:{shots:{dialogue:string;speaker_version_id?:string}[]} | null }
interface Binding { character_version_id:string; title:string; voice:string; rate:number; authorization:string }
interface Job {
  id:string;status:string;stage:string;error:string|null;storyboard_version_id:string
  output:{duration_ms?:number;cues?:{text:string;voice:string;start_ms:number;end_ms:number;shot_number:number}[]}
}
const props=defineProps<{projectId:string}>()
const emit=defineEmits<{assetsChanged:[]}>()
const voices=ref<Voice[]>([]), boards=ref<Edition[]>([]), storyboard=ref(''), bindings=ref<Binding[]>([])
const jobs=ref<Job[]>([]), selectedId=ref(''), title=ref(''), note=ref('')
const error=ref(''), message=ref(''), busy=ref(false), missingSpeaker=ref(false)
const selected=computed(()=>jobs.value.find(item=>item.id===selectedId.value))
const root=`/voice/projects/${props.projectId}/tasks`
const keys=new Map<string,string>()
const stages:Record<string,string>={voice_synthesis:'本地语音合成',voice_align:'音频与字幕对齐',voice_verify:'验证音轨和字幕',voice_publish:'保存产物'}
let timer:ReturnType<typeof setInterval>|undefined

async function run(action:()=>Promise<void>){
  busy.value=true
  error.value=''
  message.value=''
  try{await action()}catch(failure){error.value=String(failure)}finally{busy.value=false}
}
async function refresh(){
  if(props.projectId)jobs.value=await request<Job[]>(root)
}
async function load(){
  if(!props.projectId)return
  const [status,items]=await Promise.all([
    request<{voices:Voice[]}>('/voice/capabilities'),
    request<{items:Edition[]}>(`/projects/${props.projectId}/story/entities?kind=storyboard`),
  ])
  voices.value=status.voices
  boards.value=items.items
  await refresh()
}
watch(storyboard,()=>{
  bindings.value=[]
  missingSpeaker.value=false
  const id=storyboard.value
  if(!id)return
  void run(async()=>{
    const board=await request<Edition>('/story/versions/'+id)
    const shots=board.content?.shots.filter(shot=>shot.dialogue.trim()) || []
    const ids=[...new Set(shots.map(shot=>shot.speaker_version_id).filter((value):value is string=>!!value))]
    const speakers=await Promise.all(ids.map(key=>request<Edition>('/story/versions/'+key)))
    if(storyboard.value!==id)return
    missingSpeaker.value=shots.some(shot=>!shot.speaker_version_id)
    bindings.value=speakers.map(speaker=>({character_version_id:speaker.version_id,title:speaker.title,voice:'',rate:0,authorization:''}))
  })
})
async function submit(){
  await run(async()=>{
    const body={storyboard_version_id:storyboard.value,bindings:bindings.value.map(({title,...binding})=>binding)}
    const signature=JSON.stringify(body)
    if(!keys.has(signature))keys.set(signature,crypto.randomUUID())
    const job=await request<Job>(root,{...body,idempotency_key:keys.get(signature)})
    keys.delete(signature)
    selectedId.value=job.id
    title.value='';note.value=''
    await refresh()
    message.value='配音任务已排队'
  })
}
function file(name:string,download=false){return `/api/voice/tasks/${selectedId.value}/files/${name}${download?'?download=true':''}`}
async function accept(){
  await run(async()=>{
    await request('/voice/tasks/'+selectedId.value+'/select',{title:title.value,note:note.value})
    emit('assetsChanged')
    message.value='已采纳音轨和 SRT 字幕，可在剪辑页选择。'
  })
}
onMounted(()=>{
  void run(load)
  timer=setInterval(()=>{if(!busy.value)void refresh().catch(failure=>{error.value=String(failure)})},3000)
})
onUnmounted(()=>clearInterval(timer))
</script>

<template>
  <p v-if="!projectId" class="empty">选择项目并准备已保存的分镜。</p>
  <div v-else class="voice-workbench">
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="message" role="status">{{ message }}</p>
    <div class="workspace">
      <section>
        <h2>本机配音</h2>
        <p class="hint">使用已安装的 Windows 离线音色，语音和对白保存在本机。音源分离和云端音色待接入。</p>
        <p v-if="!voices.length" class="hint">未检测到可用的离线系统音色。</p>
        <form class="create" @submit.prevent="submit">
          <label>固定分镜<select v-model="storyboard" required :disabled="busy">
            <option value="">选择带对白的分镜</option><option v-for="board in boards" :key="board.version_id" :value="board.version_id">{{ board.title }} · v{{ board.version }}</option>
          </select></label>
          <p v-if="missingSpeaker" class="error">存在未绑定固定说话者的对白。请在漫剧定制中补齐分镜。</p>
          <p v-else-if="storyboard && !bindings.length" class="hint">此分镜没有待合成的对白。</p>
          <fieldset v-for="binding in bindings" :key="binding.character_version_id">
            <legend>{{ binding.title }}</legend>
            <label>离线音色<select v-model="binding.voice" required>
              <option value="">选择音色</option><option v-for="voice in voices" :key="voice.name" :value="voice.name">{{ voice.name }} · {{ voice.locale }}</option>
            </select></label>
            <label>语速<input v-model.number="binding.rate" type="number" min="-5" max="5" required></label>
            <label>使用授权说明<textarea v-model="binding.authorization" minlength="4" maxlength="2000" required></textarea></label>
          </fieldset>
          <button class="primary" :disabled="busy || !voices.length || !bindings.length || missingSpeaker">生成配音和字幕</button>
        </form>
      </section>
      <section>
        <h2>试听与采纳</h2>
        <p v-if="!selected" class="hint">选择已完成的配音任务。</p>
        <p v-else-if="selected.status!=='succeeded'">{{ stages[selected.stage] || statusLabels[selected.status] || selected.status }} {{ selected.error || '' }}</p>
        <template v-else>
          <audio :key="selected.id" controls :src="file('dialogue.wav')"></audio>
          <div class="actions downloads"><a :href="file('dialogue.wav',true)">WAV</a><a :href="file('dialogue.srt',true)">SRT</a><a :href="file('dialogue.vtt',true)">VTT</a></div>
          <details>
            <summary>字幕时间 · {{ selected.output.cues?.length || 0 }} 条</summary>
            <div v-for="(cue,index) in selected.output.cues" :key="index">
              <span class="mono">{{ clock(cue.start_ms*1000) }} – {{ clock(cue.end_ms*1000) }} · 镜头 {{ cue.shot_number }}</span>
              <p>{{ cue.text }}</p>
            </div>
          </details>
          <form class="create" @submit.prevent="accept">
            <label>素材名称<input v-model="title" required maxlength="180"></label>
            <label>采纳说明<textarea v-model="note" required maxlength="2000"></textarea></label>
            <button :disabled="busy || !title.trim() || !note.trim()">采纳音轨和字幕</button>
          </form>
        </template>
      </section>
    </div>
    <section>
      <h2>配音任务</h2>
      <p v-if="!jobs.length" class="hint">暂无任务。</p>
      <div class="version-list"><button v-for="job in jobs" :key="job.id" :aria-pressed="selectedId===job.id"
        @click="selectedId=job.id;title='';note=''">
        {{ statusLabels[job.status] || job.status }} · {{ boards.find(board=>board.version_id===job.storyboard_version_id)?.title || job.id.slice(0,8) }}
      </button></div>
    </section>
  </div>
</template>

<style scoped>
.voice-workbench { display:grid;gap:18px }
.voice-workbench fieldset { margin:0 }
.voice-workbench fieldset label { margin:8px 0 }
.downloads { margin:16px 0 }
</style>
