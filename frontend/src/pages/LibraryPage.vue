<script setup lang="ts">
import LibraryDelivery from '../LibraryDelivery.vue'
import { useWorkbench } from '../stores/workbench'
const workbench = useWorkbench()
</script>
<template><LibraryDelivery :project-id="workbench.projectId" :assets="workbench.assets" /></template>
