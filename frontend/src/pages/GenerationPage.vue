<script setup lang="ts">
import GenerationStudio from '../GenerationStudio.vue'
import ImageCandidates from '../components/production/ImageCandidates.vue'
import { useWorkspace } from '../router/workspace'
const { workbench, link, query } = useWorkspace()
</script>
<template>
  <div class="actions">
    <RouterLink v-if="query('plan') && query('shot')" :to="link('guardian',{version:query('plan'),shot:query('shot'),candidate:query('candidate') || undefined})">返回镜头返工</RouterLink>
    <RouterLink :to="link('adaptation')">剧情改编</RouterLink><RouterLink :to="link('voice')">本机配音</RouterLink><RouterLink :to="link('models')">模型与预算</RouterLink>
  </div>
  <ImageCandidates v-if="workbench.projectId" :key="workbench.projectId" :project-id="workbench.projectId"
    :initial-plan="query('plan')" :initial-shot="query('shot')" :initial-task="query('imageTask')" @assets-changed="workbench.loadAssets()" />
  <GenerationStudio :project-id="workbench.projectId" :assets="workbench.assets" :initial-plan="query('plan')"
    :initial-shot="query('shot')" :initial-asset="query('asset')" :initial-candidate="query('candidate')" @assets-changed="workbench.loadAssets()" />
</template>
