<script setup lang="ts">
import MediaAnalysis from '../MediaAnalysis.vue'
import { useWorkspace } from '../router/workspace'
const { workbench, query, go } = useWorkspace()
</script>
<template>
  <MediaAnalysis :project-id="workbench.projectId" :assets="workbench.assets" :initial-asset-id="query('asset') || ''"
    @assets-changed="workbench.loadAssets()" @adaptation="version => go('adaptation', { source: version.version_id })" />
</template>
