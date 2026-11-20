<script setup lang="ts">
import TaskList from '../components/production/TaskList.vue'
import { useWorkspace } from '../router/workspace'
import { ArrowUpRight, ClipboardCheck, PackageCheck } from 'lucide-vue-next'
const { link } = useWorkspace()
</script>
<template>
  <div class="delivery-tools">
    <RouterLink :to="link('production')"><ClipboardCheck :size="23" aria-hidden="true" /><span><strong>查看整剧质检与返工</strong><small>检查分集告警、固定时间轴和返工记录</small></span><ArrowUpRight :size="16" aria-hidden="true" /></RouterLink>
    <RouterLink :to="link('library')"><PackageCheck :size="23" aria-hidden="true" /><span><strong>授权与 ZIP 交付</strong><small>核对素材授权，管理交付包</small></span><ArrowUpRight :size="16" aria-hidden="true" /></RouterLink>
  </div>
  <TaskList renders-only />
</template>
<style scoped>
.delivery-tools { display:grid; grid-template-columns:repeat(auto-fit,minmax(min(280px,100%),1fr)); gap:12px; margin-bottom:16px }
.delivery-tools a { display:grid; grid-template-columns:24px minmax(0,1fr) 16px; align-items:center; gap:12px; background:#14252d; border:1px solid #36505c; padding:15px; border-radius:9px; text-decoration:none }
.delivery-tools a:hover { background:var(--accent-surface) }
.delivery-tools small { display:block; color:var(--ink-muted); margin-top:4px }
</style>
