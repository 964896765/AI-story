<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowRight, ClipboardCheck, PackageCheck, ShieldAlert } from 'lucide-vue-next'
import { request, statusLabels } from './analysisApi'
import SpecReference from './components/production/SpecReference.vue'
import type { ProductionSpecRef } from './types/productionSpec'

interface Work {id:string;title:string;origin:string;tags:string[];archived:boolean;episodes?:{number:number;title:string;asset_id:string;name:string;sha256:string}[]}
interface Rights {id:string;revision:number;status:string;holder:string;expires_at:string|null;scope:{regions:string[];platforms:string[];commercial:boolean};evidence:string}
interface Batch {id:string;plan_version_id:string;status:string;episode_count:number;created_at:string}
interface Package {id:string;status:string;stage:string;parameters:{title:string;platform:string;region:string};sha256:string|null;error:string|null;guardian_frame_count:number|null}
interface Readiness {
  production_spec?:ProductionSpecRef
  production_spec_issue?:string
  run_id:string;ready:boolean;rights_checked:boolean;source_count:number|null;authorized_sources:number|null
  passed_episodes:number;episode_count:number;authorization_revision:string|null
  blockers:{asset_id:string;name:string;reason:string}[]
  pending_episodes:{number:number;status:string;issue_count:number}[]
  dialogue_rechecks:number[]
}
const props=defineProps<{projectId:string;assets:{id:string;name:string}[];initialRun?:string}>()
const emit=defineEmits<{openRun:[id:string,episode?:number];openOperations:[id:string]}>()
const works=ref<Work[]>([]), work=ref<Work|null>(null), grants=ref<Rights[]>([]), runs=ref<Batch[]>([]), packages=ref<Package[]>([])
const query=ref(''), tag=ref(''), total=ref(0), offset=ref(0), workTitle=ref(''), origin=ref(''), tags=ref('')
const episodes=ref<{number:number;title:string;asset_id:string}[]>([])
const asset=ref(''), holder=ref(''), evidence=ref(''), grantStatus=ref('pending'), grantType=ref('owned')
const commercial=ref(false), allowedPlatforms=ref(''), regions=ref(''), expires=ref('')
const runId=ref(''), packageTitle=ref(''), platform=ref(''), region=ref('CN')
const linkedRun=ref<Batch|null>(null), linkedError=ref('')
const readiness=ref<Readiness|null>(null), checkedTarget=ref('')
const packageSection=ref<HTMLElement|null>(null), rightsSection=ref<HTMLElement|null>(null)
const error=ref(''), notice=ref(''), busy=ref(false), keys=new Map<string,string>()
const stage:Record<string,string>={delivery_pack:'打包成片及清单',delivery_verify:'核对文件哈希',delivery_publish:'保存交付包'}
const scope=`/projects/${props.projectId}`
const library='/library'+scope+'/works', delivery='/delivery'+scope+'/packages'
const target=computed(()=>({run_id:runId.value,platform:platform.value.trim(),region:region.value.toUpperCase().trim()}))
const targetKey=computed(()=>JSON.stringify(target.value))
const validTarget=computed(()=>!!target.value.run_id && /^[a-z0-9_-]{1,40}$/.test(target.value.platform) && /^(?:[A-Z]{2}|WORLD)$/.test(target.value.region))
const lastCheck=computed(()=>checkedTarget.value===targetKey.value ? readiness.value : null)
const runChoices=computed(()=>linkedRun.value?.status==='passed' && !runs.value.some(run=>run.id===linkedRun.value?.id)
  ? [linkedRun.value,...runs.value] : runs.value)
const episodeLabels:Record<string,string>={processing:'处理中',needs_review:'待人工复核',needs_rework:'需返工',cancelled:'已取消'}
const videoAssets=computed(()=>props.assets.filter(item=>/\.(mp4|mov|mkv|webm|avi)$/i.test(item.name)))
let timer:ReturnType<typeof setInterval>|undefined
function key(body:object){const hash=JSON.stringify(body);if(!keys.has(hash))keys.set(hash,crypto.randomUUID());return keys.get(hash)!}
const split=(value:string)=>value.trim().split(/[\s,，]+/).filter(Boolean)
async function execute(action:()=>Promise<void>){
  busy.value=true;error.value='';notice.value=''
  try{await action()}catch(failure){error.value=String(failure)}finally{busy.value=false}
}
async function list(){
  if(!props.projectId)return
  const search=new URLSearchParams({q:query.value,tag:tag.value,offset:String(offset.value),limit:'30'})
  const result=await request<{items:Work[];total:number}>(library+'?'+search)
  works.value=result.items;total.value=result.total
}
async function refresh(){
  if(!props.projectId)return
  const [production,deliverables]=await Promise.all([request<Batch[]>('/production'+scope+'/runs'),request<Package[]>(delivery)])
  runs.value=production.filter(item=>item.status==='passed')
  packages.value=deliverables
}
async function restoreRun(){
  if(!props.initialRun) return
  try {
    linkedRun.value=await request<Batch>(`/production${scope}/runs/${encodeURIComponent(props.initialRun)}`)
    if(linkedRun.value.status==='passed') runId.value=linkedRun.value.id
    await nextTick()
    packageSection.value?.scrollIntoView({block:'start'})
    packageSection.value?.focus({preventScroll:true})
  } catch (failure) {
    linkedError.value=String(failure)
  }
}
async function check() {
  if (!validTarget.value) return null
  const requested=target.value
  const signature=targetKey.value
  const query=new URLSearchParams({platform:requested.platform,region:requested.region})
  const report=await request<Readiness>(`/delivery${scope}/runs/${requested.run_id}/readiness?${query}`)
  if (signature!==targetKey.value) return null
  readiness.value=report
  checkedTarget.value=signature
  return report
}
async function reviewAsset(id:string) {
  asset.value=id
  await nextTick()
  rightsSection.value?.scrollIntoView({block:'start'})
  rightsSection.value?.querySelector('select')?.focus({preventScroll:true})
}
async function loadRight(){
  const id=asset.value
  grants.value=[]
  if(id){const current=await request<Rights[]>('/library/assets/'+id+'/rights');if(id===asset.value)grants.value=current}
}
watch(asset,()=>void execute(loadRight))
async function register(){
  await execute(async()=>{
    const body={title:workTitle.value,origin:origin.value,tags:split(tags.value),episodes:episodes.value}
    work.value=await request<Work>(library,{...body,idempotency_key:key(body)})
    await list()
    notice.value='已登记作品与分集来源'
  })
}
async function saveRights(){
  await execute(async()=>{
    const id=asset.value
    const body={status:grantStatus.value,source_type:grantType.value,holder:holder.value,evidence:evidence.value,commercial:commercial.value,
      regions:split(regions.value.toUpperCase()),platforms:split(allowedPlatforms.value),expires_at:expires.value?new Date(expires.value).toISOString():null}
    await request('/library/assets/'+id+'/rights',{...body,idempotency_key:key({...body,id})})
    await loadRight()
    if (lastCheck.value) {
      try { await check() } catch (failure) { readiness.value=null; error.value=String(failure) }
    }
    notice.value='已追加授权版本'
  })
}
async function submit(){
  await execute(async()=>{
    const preflight=await check()
    if (!preflight?.ready) return
    const body={...target.value,title:packageTitle.value}
    await request(delivery,{...body,idempotency_key:key({...body,rights:preflight.authorization_revision})})
    await refresh()
    notice.value='交付任务已排队'
  })
}
onMounted(()=>{
  if (!props.projectId) return
  void execute(async()=>{await Promise.all([list(),refresh(),restoreRun()])})
  timer=setInterval(()=>{if(!busy.value)void refresh().catch(failure=>{error.value=String(failure)})},4000)
})
onUnmounted(()=>clearInterval(timer))
</script>

<template>
  <p v-if="!projectId" class="empty">选择项目以查阅资源、授权和交付包。</p>
  <div v-else class="library">
    <p v-if="error" class="error" role="alert">{{ error }}</p>
    <p v-if="notice" role="status">{{ notice }}</p>
    <div class="workspace">
      <section>
        <h2>作品资源库</h2>
        <form class="actions" @submit.prevent="execute(async()=>{offset=0;await list()})">
          <label>作品名搜索<input v-model="query" maxlength="200"></label>
          <label>标签过滤<input v-model="tag" maxlength="60"></label>
          <button :disabled="busy">查询</button>
        </form>
        <p class="hint">{{ total }} 部作品</p>
        <div class="version-list">
          <button v-for="item in works" :key="item.id" :aria-pressed="work?.id===item.id" :disabled="busy"
            @click="execute(async()=>{work=await request<Work>('/library/works/'+item.id)})">{{ item.title }}</button>
        </div>
        <div v-if="total>30" class="actions pages">
          <button :disabled="busy || !offset" @click="execute(async()=>{offset-=30;await list()})">上一页</button>
          <button :disabled="busy || offset+30>=total" @click="execute(async()=>{offset+=30;await list()})">下一页</button>
        </div>
        <div v-if="work" class="record">
          <h3>{{ work.title }}</h3><p>{{ work.origin }}</p><p>{{ work.tags.join('、') }}</p>
          <ul><li v-for="episode in work.episodes" :key="episode.number">
            第 {{ episode.number }} 集 · {{ episode.title }} · {{ episode.name }}
            <button @click="asset=episode.asset_id">查看授权</button>
          </li></ul>
          <button v-if="!work.archived" :disabled="busy" @click="execute(async()=>{await request('/library/works/'+work!.id+'/archive',{});work=null;await list()})">归档作品记录</button>
        </div>
        <details class="record">
          <summary>登记整剧与分集来源</summary>
          <form class="form-grid" @submit.prevent="register">
            <label>作品名称<input v-model="workTitle" required maxlength="200"></label>
            <label>来源说明<textarea v-model="origin" required maxlength="4000"></textarea></label>
            <label>标签（逗号分隔）<input v-model="tags"></label>
            <fieldset v-for="(episode,index) in episodes" :key="index">
              <legend>分集素材</legend>
              <label>集号<input v-model.number="episode.number" required type="number" min="1" max="1000"></label>
              <label>集名<input v-model="episode.title" required maxlength="200"></label>
              <label>来源文件<select v-model="episode.asset_id" required><option value="">选择已导入素材</option>
                <option v-for="item in videoAssets" :key="item.id" :value="item.id">{{ item.name }}</option>
              </select></label>
              <button type="button" @click="episodes.splice(index,1)">移除此集</button>
            </fieldset>
            <button type="button" :disabled="episodes.length>=300"
              @click="episodes.push({number:Math.max(0,...episodes.map(item=>item.number))+1,title:'',asset_id:''})">添加分集</button>
            <button class="primary" :disabled="busy || !episodes.length">登记作品资源</button>
          </form>
        </details>
      </section>
      <section ref="rightsSection" class="rights-panel">
        <h2>素材授权</h2>
        <label>授权素材<select v-model="asset" :disabled="busy"><option value="">选择项目素材</option>
          <option v-for="item in assets" :key="item.id" :value="item.id">{{ item.name }}</option>
        </select></label>
        <p v-if="asset && !grants.length" class="hint">此素材待核验授权用途。</p>
        <details v-if="grants.length" class="record">
          <summary>授权历史 · 最新 v{{ grants[0].revision }}</summary>
          <article v-for="grant in grants" :key="grant.id" class="record">
            <strong>v{{ grant.revision }} · {{ {approved:'已确认',pending:'待核验',revoked:'已撤回'}[grant.status] || grant.status }}</strong>
            <p>{{ grant.holder }} · {{ grant.scope.regions.join('、') }} · {{ grant.scope.platforms.join('、') }}</p>
            <p v-if="grant.expires_at">有效至 {{ new Date(grant.expires_at).toLocaleString('zh-CN') }}</p><p>{{ grant.evidence }}</p>
          </article>
        </details>
        <form v-if="asset" class="form-grid" @submit.prevent="saveRights">
          <div class="editor-grid">
            <label>权利来源<select v-model="grantType"><option value="owned">自有</option><option value="licensed">获得授权</option></select></label>
            <label>核验状态<select v-model="grantStatus"><option value="pending">待核验</option><option value="approved">人工确认</option><option value="revoked">撤回</option></select></label>
          </div>
          <label>权利方<input v-model="holder" required maxlength="300"></label>
          <label>授权或核验证据<textarea v-model="evidence" required minlength="6" maxlength="8000"></textarea></label>
          <label class="check"><input v-model="commercial" type="checkbox">包含商用交付</label>
          <label>平台标识（逗号分隔）<input v-model="allowedPlatforms" placeholder="例如 wechat_channels"></label>
          <label>地域（两位大写代号）<input v-model="regions" placeholder="例如 CN"></label>
          <label>到期时间（本机时间）<input v-model="expires" type="datetime-local"></label>
          <button :disabled="busy">保存授权版本</button>
        </form>
      </section>
    </div>
    <section ref="packageSection" class="package-panel" tabindex="-1">
      <h2><PackageCheck :size="19" aria-hidden="true" />整剧交付</h2>
      <p v-if="linkedError" class="error" role="alert">{{linkedError}}</p>
      <div v-if="linkedRun" class="linked-run actions">
        <span>来自生产批次 {{linkedRun.id.slice(0,8)}} · {{linkedRun.episode_count}} 集 · {{linkedRun.status==='passed' ? '质检通过' : '须先通过质检'}}</span>
        <button type="button" @click="emit('openRun',linkedRun.id)">查看固定批次</button>
      </div>
      <form class="form-grid" @submit.prevent="submit">
        <label>通过质检的批次<select v-model="runId" required><option value="">选择已通过批次</option>
          <option v-for="run in runChoices" :key="run.id" :value="run.id">{{ run.episode_count }} 集 · {{ new Date(run.created_at).toLocaleString('zh-CN') }} · {{ run.id.slice(0,8) }}</option>
        </select></label>
        <div class="editor-grid">
          <label>交付包名称<input v-model="packageTitle" required maxlength="180"></label>
          <label>目标平台标识<input v-model="platform" required pattern="[a-z0-9_\-]+" maxlength="40"></label>
          <label>目标地域<input v-model="region" required maxlength="5"></label>
        </div>
        <div class="actions">
          <button type="button" :disabled="busy || !validTarget" @click="execute(async()=>{await check()})"><ClipboardCheck :size="15" aria-hidden="true" />检查交付条件</button>
          <button class="primary" :disabled="busy || !validTarget">核对授权并创建交付包</button>
        </div>
      </form>
      <div v-if="lastCheck" class="delivery-readiness" :class="{ blocked:!lastCheck.ready }" aria-live="polite">
        <div class="actions">
          <component :is="lastCheck.ready ? ClipboardCheck : ShieldAlert" :size="18" aria-hidden="true" />
          <strong>{{lastCheck.production_spec_issue || (lastCheck.ready ? '质检与当前授权通过' : lastCheck.rights_checked ? '交付授权尚未通过' : lastCheck.dialogue_rechecks.length ? '分集需要对白复检' : '整剧质检尚未通过')}}</strong>
        </div>
        <p>{{lastCheck.passed_episodes}} / {{lastCheck.episode_count}} 集通过
          <template v-if="lastCheck.rights_checked"> · {{lastCheck.authorized_sources}} / {{lastCheck.source_count}} 项素材授权覆盖目标范围</template></p>
        <SpecReference :project-id="projectId" :version-id="lastCheck.production_spec?.id" />
        <ul v-if="lastCheck.blockers.length">
          <li v-for="blocker in lastCheck.blockers" :key="blocker.asset_id">
            <span><strong>{{blocker.name}}</strong> · {{blocker.reason}}</span>
            <button type="button" @click="reviewAsset(blocker.asset_id)">核对这项授权</button>
          </li>
        </ul>
        <ul v-if="lastCheck.pending_episodes.length">
          <li v-for="episode in lastCheck.pending_episodes" :key="episode.number">
            <span>第 {{episode.number}} 集 · {{episodeLabels[episode.status] || episode.status}} · {{episode.issue_count}} 项发现</span>
            <button type="button" @click="emit('openRun',lastCheck.run_id,episode.number)">查看分集质检</button>
          </li>
        </ul>
        <ul v-if="lastCheck.dialogue_rechecks.length">
          <li v-for="episode in lastCheck.dialogue_rechecks" :key="episode">
            <span>第 {{episode}} 集 · 请使用当前规则复检</span>
            <button type="button" @click="emit('openRun',lastCheck.run_id,episode)">打开批次</button>
          </li>
        </ul>
        <p v-if="lastCheck.ready" class="hint">提交、打包、下载均会再次校验对应授权与输出。</p>
      </div>
      <article v-for="item in packages" :key="item.id" class="task">
        <div><strong>{{ item.parameters.title }}</strong><p>{{ statusLabels[item.status] || item.status }} · {{ stage[item.stage] || item.stage }}</p>
          <p v-if="item.guardian_frame_count">含 {{ item.guardian_frame_count }} 张 Guardian 审核证据帧</p>
          <p v-if="item.sha256" class="mono">SHA-256 {{ item.sha256 }}</p><p v-if="item.error" class="error">{{ item.error }}</p></div>
        <button v-if="item.status==='failed'" type="button" :disabled="busy"
          @click="execute(async()=>{await request('/tasks/'+item.id+'/retry',{}); await refresh()})">重试交付</button>
        <a v-if="item.status==='succeeded'" :href="`/api/delivery/packages/${item.id}/file`">下载已验证 ZIP</a>
        <button v-if="item.status==='succeeded'" type="button" class="handoff-button" @click="emit('openOperations',item.id)">打开人工发行 <ArrowRight :size="14" aria-hidden="true" /></button>
      </article>
    </section>
  </div>
</template>

<style scoped>
.library,.form-grid { display:grid; gap:15px }
.library section { min-width:0 }
.form-grid { margin:14px 0 }
.record,.pages { margin:14px 0 }
.library fieldset label { margin:7px 0 }
.package-panel,.rights-panel { scroll-margin-top:calc(var(--topbar-height) + 12px) }
.package-panel h2,.handoff-button,.package-panel button svg { vertical-align:middle }
.package-panel h2,.handoff-button { display:flex; align-items:center; gap:8px }
.package-panel h2 svg { color:var(--accent) }
.linked-run,.delivery-readiness { padding:12px; border:1px solid var(--line); border-radius:8px; background:var(--accent-surface); overflow-wrap:anywhere }
.delivery-readiness { color:var(--positive); margin-bottom:13px }
.delivery-readiness.blocked { border-color:var(--warning); background:color-mix(in srgb,var(--warning) 10%,var(--surface-panel)); color:var(--warning) }
.delivery-readiness p { margin:7px 0 0; color:var(--ink-secondary) }
.delivery-readiness ul { padding-left:0; margin:10px 0 0; list-style:none }
.delivery-readiness li { display:flex; flex-wrap:wrap; gap:8px; justify-content:space-between; align-items:center; padding:7px 0; border-top:1px solid var(--line-soft) }
</style>
