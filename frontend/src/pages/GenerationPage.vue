<script setup lang="ts">
import GenerationStudio from '../GenerationStudio.vue'
import { useWorkspace } from '../router/workspace'
const { workbench, link } = useWorkspace()
</script>
<template>
  <div class="actions"><RouterLink :to="link('adaptation')">剧情改编</RouterLink><RouterLink :to="link('voice')">本机配音</RouterLink><RouterLink :to="link('models')">模型与预算</RouterLink></div>
  <GenerationStudio :project-id="workbench.projectId" :assets="workbench.assets" @assets-changed="workbench.loadAssets()" />
</template>
