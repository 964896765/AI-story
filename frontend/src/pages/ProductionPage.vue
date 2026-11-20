<script setup lang="ts">
import ProductionStudio from '../ProductionStudio.vue'
import QueuePanel from '../QueuePanel.vue'
import TaskList from '../components/production/TaskList.vue'
import { useWorkspace } from '../router/workspace'
const { workbench, query, go } = useWorkspace()
</script>
<template>
  <ProductionStudio :project-id="workbench.projectId" :initial-run="query('run') || ''"
    @inspect-timeline="(version, run, clip) => go('timeline', { timeline: version, run, clip })" />
  <QueuePanel :project-id="workbench.projectId" />
  <TaskList />
</template>
