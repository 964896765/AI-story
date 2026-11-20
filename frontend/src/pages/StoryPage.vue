<script setup lang="ts">
import StoryStudio from '../StoryStudio.vue'
import { useWorkspace } from '../router/workspace'
const { route, workbench, go } = useWorkspace()
</script>
<template>
  <StoryStudio :project-id="workbench.projectId" :assets="workbench.assets"
    :initial-kind="route.name === 'characters' ? 'character' : route.name === 'storyboard' ? 'storyboard' : 'novel'"
    @assets-changed="workbench.loadAssets()" @production="version => go('video', { source: version.version_id })"
    @adaptation="version => go('adaptation', { source: version.version_id })" />
</template>
