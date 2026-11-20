<script setup lang="ts">
defineProps<{ title: string }>()
</script>
<template>
  <section class="overview-section workspace-panel">
    <div class="panel-heading"><h2>{{ title }}</h2><slot name="action" /></div>
    <slot />
  </section>
</template>
<style scoped>
.workspace-panel { min-width: 0; border: 1px solid var(--line); border-radius: var(--radius); padding: 17px; background: var(--surface-panel) }
.panel-heading { display: flex; align-items: baseline; justify-content: space-between; gap: 12px; margin-bottom: 14px }
.panel-heading h2 { margin: 0; font-size: 16px }
</style>
