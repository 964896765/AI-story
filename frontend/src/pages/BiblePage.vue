<script setup lang="ts">
import SeriesStudio from '../SeriesStudio.vue'
import { useWorkbench } from '../stores/workbench'
const workbench = useWorkbench()
</script>
<template><SeriesStudio :project-id="workbench.projectId" /></template>
