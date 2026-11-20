<script setup lang="ts">
import VideoEditor from '../VideoEditor.vue'
import { useWorkspace } from '../router/workspace'
import { useVersionLink } from '../router/useVersionLink'
const { workbench, go, query } = useWorkspace()
const { version, pending, error } = useVersionLink('source', ['script', 'episode', 'storyboard'])
</script>
<template>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <p v-if="pending" class="empty">正在读取剪辑依据…</p>
  <template v-else>
    <p v-if="version" class="actions">生产依据：{{ version.title }} · v{{ version.version }} <button @click="go('video')">清除引用</button></p>
    <VideoEditor :project-id="workbench.projectId" :assets="workbench.assets" :story-version-id="version?.version_id"
      :initial-asset="query('asset')" :initial-subtitle="query('subtitle')" @submitted="workbench.refresh()" />
  </template>
</template>
