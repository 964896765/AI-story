<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight, Check, ClipboardCheck } from 'lucide-vue-next'
import WorkspacePanel from '../components/ui/WorkspacePanel.vue'
import { useWorkspace } from '../router/workspace'
import type { Destination } from '../router/navigation'

const { workbench, link, go } = useWorkspace()
const workflows = {
  revision:{label:'剧情与版本审核',page:'adaptation',steps:['选择小说或剧本的固定版本','核对改编目标和预算','审核候选改编稿并保存新版本']},
  repair:{label:'镜头质检与返工',page:'guardian',steps:['检查已批准的故事圣经和镜头合同','定位证据，比较受影响的镜头','重新审批变更后处理候选']},
  render:{label:'剪辑与生产',page:'timeline',steps:['打开固定时间轴和素材','核对音轨、字幕和画幅','提交本机渲染并检查成片']},
  release:{label:'授权与交付',page:'library',steps:['选择已经完成技术质检的整剧批次','核对素材权利、平台和地域','生成并校验交付包']},
} as const satisfies Record<string,{label:string;page:Destination;steps:readonly string[]}>
type Workflow = keyof typeof workflows
interface Plan { intent:Workflow; instruction:string; confirmed:boolean }
const storageKey = `ai-story:director:${workbench.projectId}`

function readPlan(): Plan|null {
  try {
    const value=JSON.parse(localStorage.getItem(storageKey) || 'null')
    return value && Object.hasOwn(workflows,value.intent) && typeof value.instruction==='string' ? value : null
  } catch { return null }
}
const plan=ref<Plan|null>(readPlan())
const instruction=ref(plan.value?.instruction || ''), target=ref<Workflow>(plan.value?.intent || 'repair')
const status=ref('')
const focus=computed(()=>plan.value ? workflows[plan.value.intent] : null)
const batch=computed(()=>workbench.overview?.latest_run)
const routeParams=computed(()=>plan.value?.intent==='release' && batch.value?.status==='passed' ? {run:batch.value.id} : {})
const unchanged=computed(()=>plan.value?.instruction===instruction.value.trim() && plan.value?.intent===target.value)

function persist(value: Plan) {
  plan.value=value
  try { localStorage.setItem(storageKey,JSON.stringify(value)); status.value=value.confirmed?'已在本机保存确认记录。':'已在本机保存执行计划。' }
  catch { status.value='浏览器存储不可用，本次计划保存在当前页面。' }
}
function prepare() {
  const text=instruction.value.trim()
  if (!text || !workbench.projectId) return
  persist({intent:target.value,instruction:text,confirmed:false})
}
async function handoff() {
  if (!plan.value || !focus.value || !unchanged.value) return
  persist({...plan.value,confirmed:true})
  await go(focus.value.page,routeParams.value)
}
</script>

<template>
  <p v-if="!workbench.projectId" class="empty">请选择一个项目后制定执行计划。</p>
  <div v-else class="director-grid">
    <WorkspacePanel title="导演对话">
      <div v-if="plan" class="dialogue"><div><strong>制作指令</strong><p>{{plan.instruction}}</p></div><div><strong>执行计划已准备</strong><p>{{focus?.label}} · {{plan.confirmed?'已确认交接':'待确认'}}</p></div></div>
      <p v-else class="hint">输入制作指令并选择要交接的工作流。</p>
      <form class="director-form" @submit.prevent="prepare">
        <label>制作指令<textarea v-model="instruction" required maxlength="4000" placeholder="例如修正第二集的镜头服装，保留其他镜头"></textarea></label>
        <label>工作流<select v-model="target"><option v-for="(item,key) in workflows" :key="key" :value="key">{{item.label}}</option></select></label>
        <button type="submit" class="primary" :disabled="!instruction.trim()">生成执行计划</button>
      </form>
    </WorkspacePanel>
    <WorkspacePanel title="执行计划">
      <template v-if="plan && focus">
        <div class="director-note"><ClipboardCheck :size="17" aria-hidden="true" /><strong>{{focus.label}}</strong><span>{{ plan.confirmed?'已确认':'待确认' }}</span></div>
        <ol class="director-steps"><li v-for="step in focus.steps" :key="step">{{step}}</li></ol>
        <p class="hint" v-if="!unchanged">指令已有修改，请先更新执行计划。</p>
        <div class="actions">
          <RouterLink v-if="plan.intent==='repair'" :to="link('guardian')">查看影响分析</RouterLink>
          <button class="primary director-cta" type="button" :disabled="!unchanged" @click="handoff"><Check :size="15" aria-hidden="true" />确认并打开工作区 <ArrowRight :size="14" aria-hidden="true" /></button>
        </div>
      </template>
      <p v-else class="empty">提交制作指令后可核对执行步骤。</p>
      <p v-if="status" class="hint" role="status">{{status}}</p>
    </WorkspacePanel>
    <WorkspacePanel title="项目约束与预算">
      <dl class="director-facts">
        <div><dt>当前项目</dt><dd>{{workbench.project?.name}}</dd></div>
        <div><dt>故事圣经</dt><dd>{{workbench.overview ? (workbench.overview.story_counts.story_bible || 0) : '待读取'}}</dd></div>
        <div><dt>最近批次</dt><dd>{{batch?`${batch.passed} / ${batch.episode_count} 集通过`:'暂无'}}</dd></div>
        <div><dt>付费调用授权</dt><dd>{{workbench.overview ? (workbench.overview.live_authorized?'已授权':'关闭'):'待读取'}}</dd></div>
        <div><dt>本次交接调用费用</dt><dd>¥0.00</dd></div>
      </dl>
      <RouterLink :to="link('models')">查看模型与预算</RouterLink>
      <p class="director-note director-mode">本地计划根据所选工作流整理。生成、审批与交付在各自工作区确认。</p>
    </WorkspacePanel>
  </div>
</template>

<style scoped>
.director-grid { display:grid;grid-template-columns:minmax(210px,.95fr) minmax(260px,1.28fr) minmax(185px,.85fr);gap:14px;align-items:start }
.dialogue,.director-form { display:grid;gap:10px }
.dialogue { margin-bottom:13px }
.dialogue>div,.director-note { background:var(--surface-raised);border:1px solid var(--line);border-radius:11px;padding:12px;font-size:12px }
.dialogue>div:first-child { background:var(--accent-surface);margin-left:16px }
.dialogue p { margin:4px 0 0;white-space:pre-wrap }
.director-note { display:flex;align-items:center;gap:7px;background:var(--accent-surface);color:var(--ink) }
.director-note span { margin-left:auto;color:var(--accent);font-size:11px }
.director-mode { margin:11px 0 0 }
.director-steps { padding-left:22px;margin:9px 0 14px }
.director-steps li { padding:11px 0;border-bottom:1px solid var(--line);font-size:12px }
.director-cta { display:inline-flex;gap:6px;align-items:center }
.director-facts { margin:0 0 12px }
.director-facts div { display:grid;grid-template-columns:.85fr 1fr;gap:8px;padding:8px 0;border-bottom:1px solid var(--line);font-size:12px }
.director-facts dt { color:var(--ink-muted) }
.director-facts dd { margin:0;text-align:right;overflow-wrap:anywhere }
@media(max-width:1100px) { .director-grid { grid-template-columns:repeat(2,minmax(0,1fr)) } }
@media(max-width:700px) { .director-grid { grid-template-columns:minmax(0,1fr) } }
</style>
