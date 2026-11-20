<script setup lang="ts">
import ProductionStudio from '../ProductionStudio.vue'
import QueuePanel from '../QueuePanel.vue'
import TaskList from '../components/production/TaskList.vue'
import { useWorkspace } from '../router/workspace'
const { workbench, query, go } = useWorkspace()
</script>
<template>
  <div class="production-desk">
  <ProductionStudio :project-id="workbench.projectId" :initial-run="query('run') || ''"
    :initial-episode="query('episode')"
    @inspect-timeline="(version, run, episode, clip) => go('timeline', { timeline: version, run, episode: String(episode), clip })"
    @open-delivery="run => go('library', { run })" />
  <QueuePanel :project-id="workbench.projectId" />
  </div>
  <TaskList />
</template>
<style scoped>
.production-desk { display:grid; grid-template-columns:minmax(0,1.5fr) minmax(280px,1fr); align-items:start; gap:15px; }
.production-desk > :deep(section) { min-width:0; margin-bottom:15px }
@media(max-width:1080px) { .production-desk { grid-template-columns:1fr; gap:0 } }
</style>
