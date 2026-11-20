<script setup lang="ts">
import LibraryDelivery from '../LibraryDelivery.vue'
import { useWorkspace } from '../router/workspace'
const { workbench, query, go } = useWorkspace()
</script>
<template>
  <LibraryDelivery :project-id="workbench.projectId" :assets="workbench.assets" :initial-run="query('run')"
    @open-run="(run,episode) => go('production', { run, episode: episode ? String(episode) : undefined })"
    @open-operations="id => go('operations', { package: id })" />
</template>
