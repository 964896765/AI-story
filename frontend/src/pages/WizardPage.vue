<script setup lang="ts">
import { computed, ref } from 'vue'
import { ArrowRight, Check } from 'lucide-vue-next'
import WorkspacePanel from '../components/ui/WorkspacePanel.vue'
import { useWorkspace } from '../router/workspace'
import type { Destination } from '../router/navigation'

const { workbench, link, query, go } = useWorkspace()
const phases = [
  {title:'立项与预算',goal:'建立项目，确认原始素材与用途，登记可用预算。',pages:[['assets','导入项目素材'],['models','核对预算']]},
  {title:'剧本与故事',goal:'固定小说或剧本来源，保存分集和故事正史。',pages:[['story','编辑小说与剧本'],['adaptation','审核剧情改编'],['bible','编辑故事圣经']]},
  {title:'人物场景',goal:'保存角色身份、服装、场景及授权参考图。',pages:[['characters','打开角色与场景'],['assets','核对参考素材']]},
  {title:'镜头规划',goal:'编排镜头，核对人物首尾状态和固定版本。',pages:[['storyboard','编辑分镜'],['guardian','查看连续性与证据']]},
  {title:'模型生成',goal:'选择锁定镜头，比较候选并确认本机配音。',pages:[['generation','打开生成候选'],['voice','打开配音和字幕']]},
  {title:'剪辑交付',goal:'固定时间轴，执行成片质检，核对授权后打包。',pages:[['timeline','打开多轨时间轴'],['production','查看生产批次'],['library','授权与交付']]},
] as const satisfies readonly {title:string;goal:string;pages:readonly (readonly [Destination,string])[]}[]
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
const note=ref(notes.value[index.value] || '')
const overview=computed(()=>workbench.overview)
const observations=computed(()=>{
  if (!overview.value) return []
  const data=overview.value, counts=data.story_counts
  return [
    [`已导入 ${data.asset_count} 项素材`, data.live_authorized?'付费调用已授权':'付费调用关闭'],
    [`${counts.novel || 0} 份小说`,`${counts.script || 0} 份剧本`,`${counts.episode || 0} 份分集`],
    [`${counts.character || 0} 个角色`,`${counts.scene || 0} 个场景`],
    [`${counts.storyboard || 0} 份分镜`,`${counts.story_bible || 0} 份故事圣经`],
    [`${counts.generation_plan || 0} 份已保存模型输入计划`],
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
  <p v-if="!workbench.projectId" class="empty">请选择项目或先新建项目。 <RouterLink :to="link('assets',{create:'1'})">新建项目</RouterLink></p>
  <div v-else class="wizard-body">
    <nav class="wizard-steps" aria-label="创作向导阶段">
      <RouterLink v-for="(item,number) in phases" :key="item.title" :aria-current="number===index?'step':undefined" :to="link('wizard',{step:number+1})"><span>{{number+1}}</span>{{item.title}}</RouterLink>
    </nav>
    <div class="wizard-grid">
      <WorkspacePanel :title="phase.title">
        <p>{{phase.goal}}</p>
        <form class="wizard-note" @submit.prevent="save"><label>本阶段制作备注<textarea v-model="note" maxlength="4000" placeholder="记录要检查的素材或决定"></textarea></label>
          <button type="submit">保存本机备注</button><p v-if="status" class="hint" role="status">{{status}}</p>
        </form>
      </WorkspacePanel>
      <WorkspacePanel title="项目记录">
        <ul v-if="observations.length" class="wizard-records"><li v-for="item in observations" :key="item"><Check :size="16" aria-hidden="true" />{{item}}</li></ul>
        <p v-else class="hint" role="status">{{workbench.overviewError || '正在读取项目记录…'}}</p>
      </WorkspacePanel>
      <WorkspacePanel title="进入实际操作">
        <div class="wizard-links"><RouterLink v-for="[page,label] in phase.pages" :key="page" :to="link(page)">{{label}} <ArrowRight :size="15" aria-hidden="true" /></RouterLink></div>
        <button v-if="index<phases.length-1" type="button" class="primary wizard-next" @click="go('wizard',{step:index+2})">继续下一步 <ArrowRight :size="15" aria-hidden="true" /></button>
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
.wizard-grid { grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;align-items:start }
.wizard-note,.wizard-links { display:grid;gap:9px }
.wizard-links a { justify-content:space-between;color:var(--accent) }
.wizard-records { margin:0;padding:0;list-style:none }
.wizard-records li { display:flex;gap:8px;align-items:center;padding:10px 0;border-bottom:1px solid var(--line) }
.wizard-records svg { color:var(--accent) }
.wizard-next { margin-top:13px;display:inline-flex;gap:6px;align-items:center }
@media(max-width:940px) { .wizard-steps { grid-template-columns:repeat(3,minmax(0,1fr)) } }
@media(max-width:700px) { .wizard-steps { grid-template-columns:repeat(2,minmax(0,1fr)) } .wizard-grid { grid-template-columns:minmax(0,1fr) } }
</style>
