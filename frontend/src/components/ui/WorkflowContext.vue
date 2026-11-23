<script setup lang="ts">
import { computed } from 'vue'
import { ArrowRight } from 'lucide-vue-next'
import type { Destination } from '../../router/navigation'
import { workflowSteps } from '../../router/workflow'
import { useWorkspace } from '../../router/workspace'

const props=defineProps<{page:Destination}>()
const {query,link,workbench}=useWorkspace()
const spec=computed(()=>workbench.overview?.workflow?.production_spec)
const aliases:Partial<Record<Destination,number>>={analysis:5,video:22,quality:23,operations:24,system:3}
const defaultStep:Partial<Record<Destination,number>>={guardian:21,bible:9,generation:18,story:5}
const current=computed(()=>{
  const pointed=workflowSteps.find(step=>step.number===Number(query('flow')) && step.page===props.page)
  const usual=defaultStep[props.page] || aliases[props.page]
  return pointed || (usual ? workflowSteps[usual-1] : workflowSteps.find(step=>step.page===props.page))
})
</script>

<template>
  <aside v-if="current && page!=='wizard'" class="workflow-context" aria-label="制作流程提示">
      <div class="context-content">
        <strong>第 {{current.phase}} 阶段 · {{current.title}}</strong>
        <span>需要 {{current.input}} <span class="divider">·</span> 产出 {{current.output}}</span>
      </div>
      <div class="context-links">
        <RouterLink v-if="spec" :to="link('wizard',{step:1,spec:spec.id})">项目当前规格 v{{spec.version}}</RouterLink>
        <RouterLink :to="link('wizard',{step:current.phase})">查看本阶段步骤 <ArrowRight :size="14" aria-hidden="true" /></RouterLink>
      </div>
  </aside>
</template>

<style scoped>
.workflow-context { display:flex;justify-content:space-between;align-items:center;gap:8px 16px;flex-wrap:wrap;margin:0 0 12px;
  padding:9px 12px;border:1px solid var(--line);border-radius:8px;border-inline-start:3px solid var(--accent);
  background:var(--surface-panel);font-size:12px }
.context-content { display:flex;align-items:baseline;gap:4px 12px;flex-wrap:wrap }
.context-content > span,.divider { color:var(--ink-muted) }
.workflow-context a { display:inline-flex;align-items:center;gap:4px }
.context-links { display:flex;flex-wrap:wrap;gap:12px }
</style>
