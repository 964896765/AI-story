<script setup lang="ts">
import OperationsStudio from '../OperationsStudio.vue'
import { useWorkspace } from '../router/workspace'
const { workbench, query, go } = useWorkspace()
</script>
<template>
  <OperationsStudio :project-id="workbench.projectId" :initial-package="query('package')"
    @back-to-delivery="run => go('library', { run })" />
</template>
