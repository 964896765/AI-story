<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { request } from './analysisApi'
import GuardianRules from './components/production/GuardianRules.vue'

interface Canon {
  facts:Record<string,string>; props:Record<string,string>; character_version_ids:string[]; scene_version_ids:string[]
  style:{description:string;reference_asset_ids:string[]}
}

type EntityKind = 'script' | 'episode' | 'storyboard' | 'character' | 'scene' | 'story_bible'
interface Boundary {
  character_version_id: string; scene_version_id: string | null; wardrobe: string; prop_state: string; condition: string
}
interface Episode {
  episode_version_id: string; storyboard_version_id: string; target_duration_ms: number
  opener: Boundary[]; closer: Boundary[]; bridge_note: string
}
interface Bible {
  script_version_id: string; theme: string; world: string; rules: string; timeline: string; episodes: Episode[]
  threads: {label:string; setup_episode:number; payoff_episode:number|null}[]
  guardian?:Canon|null
}
interface Edition {
  id:string; kind:EntityKind; title:string; version_id:string; version:number; current_version:number
  content: null | Bible | { source_version_id?:string; number?:number }
}
interface Report {
  approved: boolean; ready_for_review: boolean
  issues: {code:string; episode:number; detail:string; severity:string; shot:string|null}[]
  episodes: {number:number; title:string; episode_version_id:string; planned_duration_ms:number; target_duration_ms:number;
    shots:{shot_id:string;description:string;number:number;start_ms:number;duration_ms:number}[]}[]
}
const props = defineProps<{ projectId:string; assets:{id:string;name:string}[]; initialVersion?:string }>()
const imageAssets = computed(()=>props.assets.filter(asset=>/\.(png|jpe?g|webp)$/i.test(asset.name)))
const kinds: EntityKind[] = ['script','episode','storyboard','character','scene','story_bible']
const collections = reactive<Record<EntityKind,Edition[]>>({script:[],episode:[],storyboard:[],character:[],scene:[],story_bible:[]})
const path = `/projects/${props.projectId}/story/entities`
const history = ref<Edition[]>([]), selected = ref<Edition|null>(null), report = ref<Report|null>(null)
const title = ref(''), reviewNote = ref(''), saved = ref(''), error = ref(''), info = ref(''), busy = ref(false)
const referenceKind = ref<EntityKind>('script'), manualVersion = ref(''), manualRefs = ref<Edition[]>([])
const keys = new Map<string,string>()
const defaults = ():Bible => ({script_version_id:'',theme:'',world:'',rules:'',timeline:'',episodes:[],threads:[],guardian:null})
const plan=reactive(defaults())
const dirty=computed(()=>saved.value!==JSON.stringify([title.value,plan]))
const boundaries=[{id:'opener',name:'开场状态'},{id:'closer',name:'收尾状态'}] as const

function options(kind: EntityKind, selectedIds: (string|null)[] = []) {
  const items = [...collections[kind],...manualRefs.value.filter(item=>item.kind===kind)]
  const versions = new Map(items.map(item=>[item.version_id,item]))
  for (const id of selectedIds) {
    if (id && !versions.has(id)) versions.set(id,{id,kind,title:'固定历史版本 '+id,version_id:id,version:0,current_version:0,content:null})
  }
  return [...versions.values()]
}
function label(edition: Edition) {
  return edition.title + (edition.version ? ` · v${edition.version}` : '')
}
function key(body: object) {
  const signature=JSON.stringify(body)
  if (!keys.has(signature)) keys.set(signature,crypto.randomUUID())
  return keys.get(signature)!
}
async function run(action:()=>Promise<void>) {
  busy.value=true
  error.value=''
  info.value=''
  try { await action() } catch (failure) { error.value=String(failure) } finally { busy.value=false }
}
async function list() {
  if (!props.projectId) return
  const rows=await Promise.all(kinds.map(kind=>request<{items:Edition[]}>(path+'?kind='+kind)))
  for (const [index,kind] of kinds.entries()) collections[kind]=rows[index].items
}
function fresh() {
  title.value=''
  selected.value=null
  history.value=[]
  report.value=null
  saved.value=''
  Object.assign(plan,defaults())
}
async function open(edition: Edition) {
  const data=edition.content ? edition : await request<Edition>('/story/versions/'+edition.version_id)
  selected.value=data
  title.value=data.title
  Object.assign(plan,defaults(),data.content as Bible)
  saved.value=JSON.stringify([title.value,plan])
  const [result,versions] = await Promise.all([
    request<Report>('/series/versions/'+data.version_id+'/continuity'),
    request<Edition[]>('/story/entities/'+data.id+'/versions'),
  ])
  report.value=result
  history.value=versions
  reviewNote.value=''
}
async function save() {
  await run(async()=>{
    const editing=selected.value
    const base=editing ? `/story/entities/${editing.id}/versions` : path
    const body={title:title.value,content:plan,...(editing?{expected_version:editing.current_version}:{kind:'story_bible'})}
    const saved=await request<Edition>(base,{...body,idempotency_key:key(body)})
    await list()
    await open(saved)
    info.value=`故事圣经 v${saved.version} 已保存`
  })
}
async function approve() {
  const current=selected.value
  if (!current || dirty.value || current.version!==current.current_version) return
  await run(async()=>{
    const body={expected_version:current.version,note:reviewNote.value}
    const approved=await request<Edition>(`/series/entities/${current.id}/approve`,{...body,idempotency_key:key({...body,id:current.id})})
    await list()
    await open(approved)
    info.value=`已批准固定版本 v${approved.version}`
  })
}
async function includeVersion() {
  const id=manualVersion.value.trim()
  await run(async()=>{
    const edition=await request<Edition>('/story/versions/'+encodeURIComponent(id))
    if ((edition as Edition & {project_id:string}).project_id!==props.projectId || edition.kind!==referenceKind.value)
      throw new Error('历史版本必须属于当前项目，且类型必须匹配')
    if (!manualRefs.value.some(item=>item.version_id===id)) manualRefs.value.push(edition)
    manualVersion.value=''
    info.value='固定版本已加入可选引用'
  })
}
function addEpisode() {
  plan.episodes.push({episode_version_id:'',storyboard_version_id:'',target_duration_ms:3000,opener:[],closer:[],bridge_note:''})
}
function addState(list: Boundary[]) {
  list.push({character_version_id:'',scene_version_id:null,wardrobe:'',prop_state:'',condition:''})
}
onMounted(()=>void run(async()=>{
  await list()
  if (props.initialVersion) {
    const item=await request<Edition & {project_id:string}>('/story/versions/'+encodeURIComponent(props.initialVersion))
    if (item.kind!=='story_bible' || item.project_id!==props.projectId) throw new Error('此版本不属于当前项目的故事圣经')
    await open(item)
  }
}))
</script>

<template>
  <p v-if="!projectId" class="empty">选择项目以编辑故事圣经。</p>
  <div v-else class="series">
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="info" role="status">{{ info }}</p>
    <div class="story-layout">
      <section class="story-library">
        <h2>故事圣经</h2>
        <button :disabled="busy" @click="fresh">新建故事圣经</button>
        <button v-for="edition in collections.story_bible" :key="edition.id" :disabled="busy"
          :aria-pressed="selected?.id===edition.id" @click="run(()=>open(edition))">{{ label(edition) }}</button>
        <details v-if="history.length">
          <summary>历史版本</summary>
          <div class="version-list">
            <button v-for="edition in history" :key="edition.version_id" :disabled="busy"
              @click="run(()=>open(edition))">v{{ edition.version }}</button>
          </div>
        </details>
        <details>
          <summary>引用历史版本</summary>
          <label>素材类型<select v-model="referenceKind"><option value="script">剧本</option><option value="episode">分集</option>
            <option value="storyboard">分镜</option><option value="character">角色</option><option value="scene">场景</option></select></label>
          <label>固定版本 ID<input v-model="manualVersion" maxlength="36"></label>
          <button :disabled="busy || !manualVersion.trim()" @click="includeVersion">加入可选引用</button>
        </details>
      </section>
      <section>
        <form class="series-form" @submit.prevent="save">
          <label>故事圣经标题<input v-model="title" required maxlength="200"></label>
          <label>固定总剧本<select v-model="plan.script_version_id" required>
            <option value="">选择剧本版本</option>
            <option v-for="edition in options('script',[plan.script_version_id])" :key="edition.version_id" :value="edition.version_id">{{ label(edition) }}</option>
          </select></label>
          <div class="editor-grid">
            <label>主题<textarea v-model="plan.theme" required maxlength="2000"></textarea></label>
            <label>世界观<textarea v-model="plan.world" required maxlength="8000"></textarea></label>
            <label>叙事规则<textarea v-model="plan.rules" maxlength="8000"></textarea></label>
            <label>主线时间轴<textarea v-model="plan.timeline" maxlength="8000"></textarea></label>
          </div>
          <details :open="!!plan.guardian" class="guardian-canon">
            <summary>Guardian 正史与风格锁</summary>
            <button v-if="!plan.guardian" type="button" @click="plan.guardian={facts:{},props:{},character_version_ids:[],scene_version_ids:[],style:{description:'',reference_asset_ids:[]}}">启用 Guardian 制作约束</button>
            <template v-else>
              <GuardianRules v-model="plan.guardian.facts" label="剧情事实" prefix="fact" :limit="100" />
              <GuardianRules v-model="plan.guardian.props" label="道具" prefix="prop" :limit="100" />
              <div class="editor-grid">
                <label>固定角色版本<select v-model="plan.guardian.character_version_ids" multiple>
                  <option v-for="edition in options('character',plan.guardian.character_version_ids)" :key="edition.version_id" :value="edition.version_id">{{ label(edition) }}</option>
                </select></label>
                <label>固定场景版本<select v-model="plan.guardian.scene_version_ids" multiple required>
                  <option v-for="edition in options('scene',plan.guardian.scene_version_ids)" :key="edition.version_id" :value="edition.version_id">{{ label(edition) }}</option>
                </select></label>
              </div>
              <label>全剧美术风格<textarea v-model="plan.guardian.style.description" maxlength="1000" required></textarea></label>
              <label>风格参考图<select v-model="plan.guardian.style.reference_asset_ids" multiple>
                <option v-for="asset in imageAssets" :key="asset.id" :value="asset.id">{{ asset.name }}</option>
                <option v-for="id in plan.guardian.style.reference_asset_ids.filter(id=>!imageAssets.some(asset=>asset.id===id))" :key="id" :value="id">{{ id }}</option>
              </select></label>
              <button type="button" @click="plan.guardian=null">移除本草稿的 Guardian 约束</button>
            </template>
          </details>
          <fieldset v-for="(episode,index) in plan.episodes" :key="index">
            <legend>第 {{ index+1 }} 集</legend>
            <div class="editor-grid">
              <label>固定分集<select v-model="episode.episode_version_id" required><option value="">选择分集</option>
                <option v-for="edition in options('episode',[episode.episode_version_id])" :key="edition.version_id" :value="edition.version_id">{{ label(edition) }}</option>
              </select></label>
              <label>固定分镜<select v-model="episode.storyboard_version_id" required><option value="">选择分镜</option>
                <option v-for="edition in options('storyboard',[episode.storyboard_version_id])" :key="edition.version_id" :value="edition.version_id">{{ label(edition) }}</option>
              </select></label>
              <label>目标时长（毫秒）<input v-model.number="episode.target_duration_ms" required type="number" min="200" max="86400000"></label>
            </div>
            <details v-for="boundary in boundaries" :key="boundary.id">
              <summary>{{ boundary.name }}</summary>
              <fieldset v-for="(state,i) in episode[boundary.id]" :key="i">
                <legend>角色 {{ i+1 }}</legend>
                <div class="editor-grid">
                  <label>固定角色<select v-model="state.character_version_id" required><option value="">选择角色</option>
                    <option v-for="edition in options('character',[state.character_version_id])" :key="edition.version_id" :value="edition.version_id">{{ label(edition) }}</option>
                  </select></label>
                  <label>固定场景<select v-model="state.scene_version_id"><option :value="null">未指定</option>
                    <option v-for="edition in options('scene',[state.scene_version_id])" :key="edition.version_id" :value="edition.version_id">{{ label(edition) }}</option>
                  </select></label>
                  <label>服装<input v-model="state.wardrobe" maxlength="200"></label>
                  <label>道具状态<input v-model="state.prop_state" maxlength="300"></label>
                  <label>人物状态<input v-model="state.condition" maxlength="300"></label>
                </div>
                <button type="button" @click="episode[boundary.id].splice(i,1)">移除状态</button>
              </fieldset>
              <button type="button" :disabled="episode[boundary.id].length>=16" @click="addState(episode[boundary.id])">添加角色状态</button>
            </details>
            <label v-if="index">与上集衔接说明<textarea v-model="episode.bridge_note" maxlength="1200"></textarea></label>
            <button type="button" @click="plan.episodes.splice(index,1)">移除此集</button>
          </fieldset>
          <button type="button" :disabled="plan.episodes.length>=60" @click="addEpisode">添加分集计划</button>
          <details>
            <summary>伏笔与回收</summary>
            <fieldset v-for="(thread,index) in plan.threads" :key="index">
              <legend>伏笔 {{ index+1 }}</legend>
              <div class="editor-grid">
                <label>伏笔<input v-model="thread.label" required maxlength="200"></label>
                <label>埋设集数<input v-model.number="thread.setup_episode" required type="number" min="1" max="1000"></label>
                <label>回收集数<input :value="thread.payoff_episode ?? ''" type="number" min="1" max="1000"
                  @input="thread.payoff_episode=($event.target as HTMLInputElement).value==='' ? null : Number(($event.target as HTMLInputElement).value)"></label>
              </div>
              <button type="button" @click="plan.threads.splice(index,1)">移除伏笔</button>
            </fieldset>
            <button type="button" :disabled="plan.threads.length>=100" @click="plan.threads.push({label:'',setup_episode:1,payoff_episode:null})">添加伏笔</button>
          </details>
          <button class="primary" :disabled="busy || !plan.episodes.length || !dirty">保存并校验</button>
        </form>
      </section>
    </div>
    <section v-if="report">
      <h2>连续性审核</h2>
      <p v-if="dirty" class="hint">以下结果对应上一次保存的版本。</p>
      <p v-if="report.approved">固定版本已批准。</p>
      <p v-else-if="report.ready_for_review">规则检查已完成，可以人工审核。</p>
      <ul v-if="report.issues.length">
        <li v-for="(issue,i) in report.issues" :key="i" :class="{failed:issue.severity==='error'}">
          {{ issue.episode ? `第 ${issue.episode} 集` : '全剧' }} · {{ issue.severity==='error'?'待修正':'人工复核' }} · {{ issue.detail }}
        </li>
      </ul>
      <details v-for="episode in report.episodes" :key="episode.episode_version_id">
        <summary>第 {{ episode.number }} 集 · {{ episode.title }} · {{ episode.planned_duration_ms/1000 }} 秒</summary>
        <ol><li v-for="shot in episode.shots" :key="shot.shot_id">{{ shot.start_ms/1000 }} 秒 · {{ shot.description }} <code>{{ shot.shot_id }}</code></li></ol>
      </details>
      <div v-if="report.ready_for_review && !report.approved && selected?.version===selected?.current_version" class="series-form">
        <label>审核说明<textarea v-model="reviewNote" maxlength="4000"></textarea></label>
        <button :disabled="busy || dirty || !reviewNote.trim()" @click="approve">批准固定制作计划</button>
      </div>
      <RouterLink v-if="plan.guardian && selected" :to="{name:'guardian',query:{project:projectId,version:selected.version_id}}">打开 Guardian 质检工作台</RouterLink>
    </section>
  </div>
</template>

<style scoped>
.series,.series-form { display:grid; gap:14px }
.series details,.series fieldset { margin:0 0 10px }
.series .editor-grid { margin:12px 0 }
.series label { margin:7px 0 }
.series li { margin-bottom:8px }
.series code { overflow-wrap:anywhere; color:var(--ink-muted) }
</style>
