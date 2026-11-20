<script setup lang="ts">
import VoiceStudio from '../VoiceStudio.vue'
import { useWorkbench } from '../stores/workbench'
const workbench = useWorkbench()
</script>
<template><VoiceStudio :project-id="workbench.projectId" @assets-changed="workbench.loadAssets()" /></template>
