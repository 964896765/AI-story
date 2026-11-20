<script setup lang="ts">
import { NModal } from 'naive-ui'
const taskId = defineModel<string>({ required: true })
defineProps<{ title?: string }>()
</script>
<template>
  <NModal :show="Boolean(taskId)" @update:show="value => { if (!value) taskId = '' }"
    preset="card" :title="title || '已验证成片预览'" :style="{ width: 'min(900px, calc(100vw - 26px))' }">
    <video v-if="taskId" :key="taskId" class="output-modal-video" controls playsinline preload="metadata" :src="`/api/tasks/${taskId}/output`"></video>
    <template #footer>
      <div class="actions"><a :href="`/api/tasks/${taskId}/output?download=true`">下载成片</a><span class="hint">播放取决于浏览器的编码支持。</span></div>
    </template>
  </NModal>
</template>
<style scoped>
.output-modal-video { display: block; width: 100%; max-height: 65vh; background: #121216; border-radius: 6px }
</style>
