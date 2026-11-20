<script setup lang="ts">
import MediaAnalysis from '../MediaAnalysis.vue'
import { useWorkspace } from '../router/workspace'
import { useRouter } from 'vue-router'

const { workbench, query, go, link } = useWorkspace()
const router = useRouter()
function reviewLink(asset: string, task: string, time: number, proxy: string) {
  return router.resolve(link('analysis', { asset, task: task || undefined, at: String(time),
    preview: proxy || undefined })).href
}
</script>
<template>
  <MediaAnalysis :project-id="workbench.projectId" :assets="workbench.assets" :initial-asset-id="query('asset') || ''"
    :initial-task-id="query('task')" :initial-time="query('at')" :initial-proxy="query('preview')"
    :review-link="reviewLink"
    @assets-changed="workbench.loadAssets()" @adaptation="version => go('adaptation', { source: version.version_id })"
    @edit-video="(asset, subtitle) => go('video', { asset, subtitle })" />
</template>
