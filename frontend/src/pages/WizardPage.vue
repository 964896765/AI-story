<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight } from 'lucide-vue-next'
import WorkspacePanel from '../components/ui/WorkspacePanel.vue'
import { useWorkspace } from '../router/workspace'
import { phases, suggestedStep, workflowSteps } from '../router/workflow'

const { workbench, link, query, go } = useWorkspace()
const key=`ai-story:wizard:${workbench.projectId}`
function readNotes(): Record<number,string> {
  try { return JSON.parse(localStorage.getItem(key) || '{}') || {} } catch { return {} }
}
const notes=ref(readNotes()), status=ref('')
const index=computed(()=>{
  const requested=Number(query('step') || 1)
  return Number.isInteger(requested) && requested>=1 && requested<=phases.length ? requested-1 : 0
})
const phase=computed(()=>phases[index.value])
const steps=computed(()=>workflowSteps.filter(item=>item.phase===index.value+1))
const note=ref(notes.value[index.value] || '')
const overview=computed(()=>workbench.overview)
const suggestion=computed(()=>overview.value && suggestedStep(overview.value))
const suggestedLink=computed(()=>suggestion.value && link(workflowSteps[suggestion.value.step-1].page,{...suggestion.value.query,flow:suggestion.value.step}))
const observations=computed(()=>{
  if (!overview.value) return []
  const data=overview.value, counts=data.story_counts
  return [
    [`已导入 ${data.asset_count} 项素材`, data.live_authorized?'真实文本调用开关已开启':'真实文本调用关闭',
      data.workflow?.director_plan_id?'已有固定执行计划':'暂无固定执行计划'],
    [`${counts.novel || 0} 份小说`,`${counts.script || 0} 份剧本`,`${counts.episode || 0} 份分集`],
    [`${counts.character || 0} 个角色`,`${counts.scene || 0} 个场景`],
    [`${counts.storyboard || 0} 份分镜`,data.workflow?.approved_series_id?'已有批准计划':'暂无批准计划'],
    [`已采纳 ${data.workflow?.adopted_candidates || 0} 个本机运镜候选`],
    [`${data.render_count} 部已验证成片`,`${data.delivery_count} 份交付包`],
  ][index.value]
})
function save() {
  notes.value[index.value]=note.value
  try { localStorage.setItem(key,JSON.stringify(notes.value)); status.value='已保存此阶段的本机制作备注。' }
  catch { status.value='浏览器无法保存制作备注。' }
}
</script>

<template>
  <div class="wizard-body">
    <section class="wizard-resume">
      <div v-if="!workbench.projectId"><h2>从原创创意或授权小说开始</h2><p>新建项目，在项目说明写下创意或改编目标。保存后可导入原稿并制定计划。</p></div>
      <div v-else-if="suggestion"><h2>建议下一步</h2><p>{{suggestion.label}}。你也可以从下方切换阶段处理其他工作。</p></div>
      <p v-else role="status">{{workbench.overviewError || '正在读取项目进度…'}}</p>
      <RouterLink v-if="!workbench.projectId" :to="link('assets',{create:'1',flow:1})">新建项目 <ArrowRight :size="15" aria-hidden="true" /></RouterLink>
      <RouterLink v-else-if="suggestedLink" :to="suggestedLink">继续制作 <ArrowRight :size="15" aria-hidden="true" /></RouterLink>
    </section>
    <nav class="wizard-steps" aria-label="创作向导阶段">
      <RouterLink v-for="(item,number) in phases" :key="item.title" :aria-current="number===index?'step':undefined" :to="link('wizard',{step:number+1})"><span>{{number+1}}</span>{{item.title}}</RouterLink>
    </nav>
    <div class="wizard-grid">
      <WorkspacePanel :title="phase.title">
        <ol class="workflow-checklist" :start="index*4+1">
          <li v-for="item in steps" :key="item.number">
            <div><strong>{{item.title}}</strong><small v-if="item.state"> · 外部能力{{item.state}}</small>
            <p>{{item.action}}</p><p class="hint">输入 {{item.input}} <span>·</span> 产出 {{item.output}}</p></div>
            <RouterLink v-if="item.page!=='wizard'" :to="link(item.page, item.number===1 && !workbench.projectId ? {create:'1',flow:item.number} : {flow:item.number})">
              打开工作区 <ArrowRight :size="15" aria-hidden="true" />
            </RouterLink>
          </li>
        </ol>
        <button v-if="index<phases.length-1" type="button" class="wizard-next" @click="go('wizard',{step:index+2})">继续下一步 <ArrowRight :size="15" aria-hidden="true" /></button>
      </WorkspacePanel>
      <WorkspacePanel title="项目记录">
        <ul v-if="observations.length" class="wizard-records"><li v-for="item in observations" :key="item">{{item}}</li></ul>
        <p v-else class="hint" role="status">{{workbench.overviewError || (workbench.projectId ? '正在读取项目记录…' : '新建或选择项目后显示实际记录。')}}</p>
        <form v-if="workbench.projectId" class="wizard-note" @submit.prevent="save"><label>本阶段制作备注<textarea v-model="note" maxlength="4000" :placeholder="index===0 ? '集数、单集时长、画风、画幅与试制范围' : '记录要检查的素材或决定'"></textarea></label>
          <button type="submit">保存本机备注</button><p v-if="status" class="hint" role="status">{{status}}</p>
        </form>
      </WorkspacePanel>
    </div>
  </div>
</template>

<style scoped>
.wizard-body { display:grid;gap:14px }
.wizard-steps,.wizard-grid { display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:8px }
.wizard-steps a,.wizard-links a { display:flex;align-items:center;gap:7px;padding:10px 8px;border:1px solid var(--line);border-radius:9px;background:var(--surface-panel);font-size:12px;text-decoration:none;color:var(--ink) }
.wizard-steps a span { display:grid;place-items:center;width:22px;height:22px;border-radius:50%;background:var(--surface-raised);flex:none }
.wizard-steps a[aria-current=step] { border-color:var(--accent);background:var(--accent-surface);color:var(--accent);font-weight:700 }
.wizard-steps a[aria-current=step] span { background:var(--primary-fill);color:#fff }
.wizard-grid { grid-template-columns:minmax(0,2fr) minmax(250px,1fr);gap:14px;align-items:start }
.wizard-resume { display:flex; align-items:center; justify-content:space-between; flex-wrap:wrap; gap:10px; border-inline-start:3px solid var(--accent) }
.wizard-resume :is(h2,p) { margin:0 0 3px }
.wizard-resume a,.workflow-checklist a { display:inline-flex; align-items:center; gap:5px; white-space:nowrap }
.wizard-note { display:grid;gap:9px;margin-top:12px }
.workflow-checklist { margin:0; padding-inline-start:25px }
.workflow-checklist li { padding:9px 0;border-bottom:1px solid var(--line) }
.workflow-checklist li > div { display:inline-block; width:min(100%,calc(100% - 115px)); vertical-align:middle; padding-inline-end:8px }
.workflow-checklist li > div p { margin:4px 0 }
.workflow-checklist li small { color:var(--ink-muted) }
.wizard-records { margin:0;padding:0;list-style:none }
.wizard-records li { display:flex;gap:8px;align-items:center;padding:10px 0;border-bottom:1px solid var(--line) }
.wizard-records svg { color:var(--accent) }
.wizard-next { margin-top:13px;display:inline-flex;gap:6px;align-items:center }
@media(max-width:940px) { .wizard-steps { grid-template-columns:repeat(3,minmax(0,1fr)) } }
@media(max-width:700px) { .wizard-steps { grid-template-columns:repeat(2,minmax(0,1fr)) } .wizard-grid { grid-template-columns:minmax(0,1fr) } .workflow-checklist li > div { width:100% } }
</style>
