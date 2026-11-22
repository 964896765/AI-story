<script setup lang="ts">
import GenerationStudio from '../GenerationStudio.vue'
import { useWorkspace } from '../router/workspace'
const { workbench, link, query } = useWorkspace()
</script>
<template>
  <div class="actions"><RouterLink :to="link('adaptation')">剧情改编</RouterLink><RouterLink :to="link('voice')">本机配音</RouterLink><RouterLink :to="link('models')">模型与预算</RouterLink></div>
  <GenerationStudio :project-id="workbench.projectId" :assets="workbench.assets" :initial-plan="query('plan')"
    :initial-shot="query('shot')" :initial-asset="query('asset')" @assets-changed="workbench.loadAssets()" />
</template>
