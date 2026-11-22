<script setup lang="ts">
import SeriesStudio from '../SeriesStudio.vue'
import { useWorkspace } from '../router/workspace'
const { workbench, query } = useWorkspace()
</script>
<template><SeriesStudio :key="workbench.projectId" :project-id="workbench.projectId" :assets="workbench.assets" :initial-version="query('version')" /></template>
