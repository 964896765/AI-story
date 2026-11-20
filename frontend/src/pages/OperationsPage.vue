<script setup lang="ts">
import OperationsStudio from '../OperationsStudio.vue'
import { useWorkbench } from '../stores/workbench'
const workbench = useWorkbench()
</script>
<template><OperationsStudio :project-id="workbench.projectId" /></template>
