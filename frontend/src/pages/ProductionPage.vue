<script setup lang="ts">
import ProductionStudio from '../ProductionStudio.vue'
import QueuePanel from '../QueuePanel.vue'
import TaskList from '../components/production/TaskList.vue'
import { useWorkspace } from '../router/workspace'
import { computed } from 'vue'
import WorkspacePanel from '../components/ui/WorkspacePanel.vue'
const { workbench, query, go, link } = useWorkspace()
const latest=computed(()=>workbench.overview?.latest_run)
const counts=computed(()=>workbench.overview?.task_counts)
const jobs=computed(()=>counts.value && Object.values(counts.value).reduce((sum,count)=>sum+count,0))
</script>
<template>
  <div v-if="workbench.overview" class="schedule-metrics" aria-label="生产指标">
    <div><span>总任务</span><strong>{{jobs}}</strong></div>
    <div><span>执行中</span><strong>{{counts?.running || 0}}</strong></div>
    <div><span>等待领取</span><strong>{{counts?.queued || 0}}</strong></div>
    <div><span>待审核与返工</span><strong>{{(latest?.reviews || 0)+(latest?.rework || 0)}}</strong></div>
  </div>
  <div class="production-desk">
    <WorkspacePanel title="生产依赖关系" class="dependency-panel">
      <ol><li><RouterLink :to="link('bible')">批准固定制作计划</RouterLink></li>
        <li><RouterLink :to="link('generation')">生成与审核候选</RouterLink></li>
        <li><RouterLink :to="link('voice')">配音与字幕</RouterLink></li>
        <li><a href="#series-production">渲染、质检与交付</a></li></ol>
      <p v-if="latest" class="hint">最近批次已有 {{latest.passed}} / {{latest.episode_count}} 集通过。</p>
    </WorkspacePanel>
    <TaskList />
    <QueuePanel :project-id="workbench.projectId" />
  </div>
  <ProductionStudio :project-id="workbench.projectId" :initial-run="query('run') || ''"
    id="series-production"
    :initial-episode="query('episode')"
    @inspect-timeline="(version, run, episode, clip) => go('timeline', { timeline: version, run, episode: String(episode), clip })"
    @open-delivery="run => go('library', { run })" />
</template>
<style scoped>
.production-desk { display:grid;grid-template-columns:minmax(160px,.65fr) minmax(300px,1.65fr) minmax(200px,.82fr);align-items:start;gap:14px;margin:0 0 15px }
.production-desk > :deep(section) { min-width:0;margin:0 }
.schedule-metrics { display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin-bottom:14px }
.schedule-metrics>div { padding:14px 18px;border:1px solid var(--line);background:var(--surface-panel);border-radius:14px;box-shadow:var(--shadow) }
.schedule-metrics span { color:var(--ink-muted);font-size:12px }
.schedule-metrics strong { display:block;font-size:25px;font-variant-numeric:tabular-nums }
.dependency-panel ol { padding-left:22px }
.dependency-panel li { padding:8px 0;border-bottom:1px solid var(--line) }
#series-production { scroll-margin-top:70px }
@media(max-width:1080px) { .production-desk { grid-template-columns:minmax(0,1.65fr) minmax(190px,.8fr) } .dependency-panel { grid-column:1/-1 } }
@media(max-width:700px) { .production-desk { grid-template-columns:minmax(0,1fr) } .schedule-metrics { grid-template-columns:repeat(2,minmax(0,1fr)) } }
</style>
