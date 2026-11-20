<script setup lang="ts">
import TextAdaptation from '../TextAdaptation.vue'
import { useWorkspace } from '../router/workspace'
import { useVersionLink } from '../router/useVersionLink'
const { route, workbench, query, go } = useWorkspace()
const { version, pending, error } = useVersionLink('source', ['novel', 'script', 'episode'])
</script>
<template>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="pending" class="empty">正在读取固定原稿…</p>
  <TextAdaptation v-else :project-id="workbench.projectId" :source="version" :initial-call="query('call') || ''" :settings-only="route.name === 'models'"
    @source-picker="go('story')" @production="saved => go('video', { source: saved.version_id })" />
</template>
