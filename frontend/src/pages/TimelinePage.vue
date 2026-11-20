<script setup lang="ts">
import TimelineStudio from '../TimelineStudio.vue'
import { useWorkspace } from '../router/workspace'
import { useVersionLink } from '../router/useVersionLink'
const { workbench, query, go } = useWorkspace()
const { version, pending, error } = useVersionLink('timeline', ['timeline'])
</script>
<template>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="pending" class="empty">正在读取固定时间轴…</p>
  <TimelineStudio v-else :project-id="workbench.projectId" :assets="workbench.assets" :initial-version="version?.version_id"
    :initial-clip="version ? query('clip') || '' : ''" :can-return="!!(version && query('run'))"
    @return-to-production="go('production', { run: query('run') })" />
</template>
