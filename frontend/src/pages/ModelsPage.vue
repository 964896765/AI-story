<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ArrowRight, Cable, Cpu, ShieldCheck } from 'lucide-vue-next'
import TextAdaptation from '../TextAdaptation.vue'
import { useWorkspace } from '../router/workspace'
import { api, post } from '../services/api'

const { workbench, query, link, go } = useWorkspace()
const catalog = [
  ['codex','Codex','工程维护','为后续官方 Codex 集成记录模型偏好，本机仅检查命令是否可发现。'],
  ['openai-image','OpenAI 图片','角色与关键帧','保存图片适配器的预备配置。'],
  ['tongyi-image','通义万相图片','角色与关键帧','保存图片适配器的预备配置。'],
  ['wan-video','通义万相视频','动态镜头','保存视频适配器的预备配置。'],
  ['hailuo-video','MiniMax 海螺','动态镜头','保存视频适配器的预备配置。'],
  ['seedance','火山 Seedance','动态镜头','保存视频适配器的预备配置。'],
  ['kling','可灵','动态镜头','保存视频适配器的预备配置。'],
  ['cloud-tts','云端语音','配音','保存云端音色供应商的预备配置。'],
  ['visual-review','视觉质检模型','候选审核','保存视觉检验供应商的预备配置。'],
] as const
type Connector = typeof catalog[number][0]
interface Draft { model:string; base_url:string; secret_env:string; region:string }
interface Registry { codex_cli_detected:boolean; drafts:Partial<Record<Connector,Draft>> }
const registry=ref<Registry|null>(null), failure=ref(''), notice=ref(''), saving=ref(false)
const textStatus=ref<{live_authorized:boolean;default_live_budget_micros:number}|null>(null)
const initial=catalog.find(([id])=>id===query('connector'))
const selected=ref<Connector>(initial?.[0] || 'codex')
const info=computed(()=>catalog.find(([id])=>id===selected.value)!)
const form=reactive<Draft>({model:'',base_url:'',region:'',secret_env:''})
function open(id:Connector) {
  selected.value=id
  failure.value=''; notice.value=''
  Object.assign(form, {model:'',base_url:'',region:'',secret_env:''}, registry.value?.drafts[id])
}
async function load() {
  try {
    const [connections,text]=await Promise.all([api<Registry>('/models/connections'),
      api<{live_authorized:boolean;default_live_budget_micros:number}>('/text/status')])
    registry.value=connections
    textStatus.value=text
    open(selected.value)
  } catch (error) { failure.value=String(error) }
}
async function save() {
  saving.value=true; failure.value=''; notice.value=''
  try {
    const reply=await post<{settings:Draft}>('/models/connections/'+selected.value,{...form,model:form.model.trim()})
    if(registry.value) registry.value.drafts[selected.value]=reply.settings
    Object.assign(form,reply.settings)
    notice.value='配置草稿已保存，等待执行适配器接入。'
  } catch (error) { failure.value=String(error) }
  finally { saving.value=false }
}
onMounted(load)
</script>

<template>
  <div class="model-console">
    <section class="model-summary">
      <div><ShieldCheck :size="20" aria-hidden="true" /><span><strong>{{textStatus ? (textStatus.live_authorized ? '文本调用开关已开启' : '真实文本调用关闭') : '文本开关状态待读取'}}</strong><small>文本额度和用量在下方单独管理</small></span></div>
      <div><Cpu :size="20" aria-hidden="true" /><span><strong>{{workbench.health==='ready' ? '本机服务就绪' : '本机服务待确认'}}</strong><small>FFmpeg 运镜、系统配音与技术质检</small></span></div>
      <div><Cable :size="20" aria-hidden="true" /><span><strong>外部生成与 Codex 待接入</strong><small>可提前保存配置草稿</small></span></div>
      <a href="#text-model-settings">配置文本与额度 <ArrowRight :size="15" aria-hidden="true" /></a>
    </section>
    <section class="model-config">
      <div>
        <h2>模型接入</h2>
        <div class="connector-list" aria-label="供应商与执行器">
          <button v-for="[id,title,role] in catalog" :key="id" type="button" :aria-pressed="id===selected" :disabled="!registry || saving" @click="open(id)">
            <span><strong>{{title}}</strong><small>{{role}}</small></span><small>{{registry?.drafts[id] ? '已保存草稿' : '待配置'}}</small>
          </button>
        </div>
      </div>
      <div class="connector-details">
        <h2>{{info[1]}}</h2>
        <p>{{info[3]}}</p>
        <p v-if="failure" role="alert" class="error">{{failure}}</p>
        <button v-if="!registry && failure" type="button" @click="load">重读接入设置</button>
        <p v-else-if="!registry" role="status">正在读取本机配置…</p>
        <template v-else>
          <p v-if="selected==='codex'" class="hint">本机命令{{registry.codex_cli_detected ? '已检测到' : '未检测到'}} · 账号能力未核验 · 生产创作 Agent 使用单独的模型与审批流程。</p>
          <p v-else class="hint">执行适配器待接入 · 实际费率未知。适配后仍须完成授权、报价和预算检查。</p>
          <form class="create" @submit.prevent="save">
            <label>{{selected==='codex' ? 'Codex 首选模型 ID' : '供应商模型 ID'}}<input v-model.trim="form.model" required maxlength="160"></label>
            <template v-if="selected!=='codex'">
              <label>供应商 Base URL<input v-model.trim="form.base_url" type="url" maxlength="500" placeholder="从供应商控制台获取 HTTPS 地址"></label>
              <label>区域或站点代号<input v-model.trim="form.region" maxlength="64" placeholder="按供应商控制台填写"></label>
              <label>密钥环境变量名称<input v-model.trim="form.secret_env" maxlength="128" pattern="[A-Z][A-Z0-9_]*_API_KEY" placeholder="填写变量名，例如 AI_STORY_VIDEO_API_KEY"></label>
            </template>
            <button type="submit" class="primary" :disabled="saving">{{saving ? '保存中…' : '保存配置草稿'}}</button>
          </form>
          <p v-if="notice" role="status">{{notice}}</p>
        </template>
      </div>
    </section>
    <div id="text-model-settings">
      <TextAdaptation v-if="workbench.projectId" :project-id="workbench.projectId" :source="null" settings-only
        @source-picker="go('story')" @production="saved => go('video', { source: saved.version_id })" />
      <section v-else><h2>文本模型与项目预算</h2><p>选择项目后配置文本供应商和预算。</p><RouterLink :to="link('assets',{create:'1'})">新建项目</RouterLink></section>
    </div>
  </div>
</template>

<style scoped>
.model-console { display:grid; gap:14px }
.model-summary { display:flex; flex-wrap:wrap; align-items:center; justify-content:space-between; gap:12px }
.model-summary div,.model-summary a,.connector-list button { display:flex; align-items:center; gap:9px }
.model-summary small,.connector-list small { display:block; color:var(--ink-muted); margin-top:3px }
.model-summary svg { color:var(--accent); flex:none }
.model-config { display:grid; grid-template-columns:minmax(230px,.8fr) minmax(0,1.2fr); gap:18px; align-items:start }
.connector-list { display:grid; gap:4px }
.connector-list button { justify-content:space-between; text-align:left; min-width:0 }
.connector-list button[aria-pressed=true] { color:var(--accent); border-color:var(--accent); background:var(--accent-surface) }
.connector-details { min-width:0; border-inline-start:1px solid var(--line); padding-inline-start:18px }
#text-model-settings { scroll-margin-top:calc(var(--topbar-height) + 10px) }
@media(max-width:740px) {
  .model-config { grid-template-columns:minmax(0,1fr) }
  .connector-list { grid-template-columns:repeat(2,minmax(0,1fr)) }
  .connector-details { border-inline-start:0; border-top:1px solid var(--line); padding:14px 0 0 }
}
@media(max-width:420px) { .connector-list button { flex-wrap:wrap } }
</style>
