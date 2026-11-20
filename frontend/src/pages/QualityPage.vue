<script setup lang="ts">
import TaskList from '../components/production/TaskList.vue'
import { useWorkspace } from '../router/workspace'
const { link } = useWorkspace()
</script>
<template>
  <div class="actions"><RouterLink :to="link('production')">查看整剧质检与返工</RouterLink><RouterLink :to="link('library')">授权与 ZIP 交付</RouterLink></div>
  <TaskList renders-only />
</template>
