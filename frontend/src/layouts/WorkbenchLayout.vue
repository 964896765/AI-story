<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { Aperture, ChevronDown, ChevronRight, Menu, RefreshCw, X } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { destinations, navigation, workspaces, type Destination } from '../router/navigation'
import { useWorkspace } from '../router/workspace'

const { route, workbench, link } = useWorkspace()
const router = useRouter()
const menuOpen = ref(false)
const menuTrigger = ref<HTMLButtonElement | null>(null)
const sidebar = ref<HTMLElement | null>(null)
const name = computed(() => route.name as Destination)
const group = computed(() => workspaces.find(item => item.pages.includes(name.value)))
const title = computed(() => name.value === 'overview' ? '项目总览' : group.value?.label || String(route.meta.title))
const statusText = computed(() => workbench.health === 'ready' && workbench.initialized ? '服务就绪' :
  workbench.health === 'unavailable' ? '服务未就绪' : '检查服务中')

watch([() => route.query.project, () => workbench.initialized], ([requested, initialized]) => {
  if (!initialized) return
  const valid = (id: unknown): id is string => typeof id === 'string' && workbench.projects.some(item => item.id === id)
  const prior = workbench.lastProject()
  const resolved = typeof requested === 'string' ? (valid(requested) ? requested : '') :
    valid(prior) ? prior : workbench.projects[0]?.id || ''
  workbench.select(resolved)
}, { immediate: true, flush: 'sync' })

watch(() => route.fullPath, () => { closeMenu() })
watch(title, value => { document.title = `${value} · AI Story` }, { immediate: true })

function switchProject(event: Event) {
  const project = (event.target as HTMLSelectElement).value
  void router.push({ name: name.value, query: { project } })
}

async function openMenu() {
  menuOpen.value = true
  await nextTick()
  sidebar.value?.querySelector<HTMLElement>('.nav-active, nav a')?.focus()
}

function closeMenu() {
  if (!menuOpen.value) return
  menuOpen.value = false
  menuTrigger.value?.focus()
}

onMounted(() => { void workbench.initialize() })
</script>

<template>
  <div class="app-shell" @keydown.esc="closeMenu">
    <a class="skip-link" href="#workspace-main">跳到工作区</a>
    <button v-if="menuOpen" type="button" class="mobile-scrim" aria-label="关闭导航" @click="closeMenu"></button>
    <aside ref="sidebar" class="app-sidebar" :class="{ 'is-open': menuOpen }" id="workbench-nav">
      <RouterLink class="app-brand" :to="link('overview')">
        <span class="brand-mark"><Aperture :size="22" aria-hidden="true" /></span>
        <span><strong>AI Story</strong><small>漫剧制作工作台</small></span>
      </RouterLink>
      <button class="icon-button mobile-close" type="button" aria-label="关闭导航" @click="closeMenu"><X :size="18" /></button>
      <nav aria-label="工作区">
        <div v-for="section in navigation" :key="section.label" class="nav-group">
          <p>{{ section.label }}</p>
          <RouterLink v-for="item in section.links" :key="item.label" class="nav-item"
            :class="{ 'nav-active': group?.label === item.label }" :to="link(item.pages[0])" :data-workspace="item.label">
            <component :is="item.icon" :size="17" :stroke-width="1.7" aria-hidden="true" />
            <span>{{ item.label }}</span><ChevronRight v-if="group?.label === item.label" class="nav-arrow" :size="13" aria-hidden="true" />
          </RouterLink>
        </div>
      </nav>
      <div class="sidebar-footer"><span class="connection-dot" :class="workbench.health"></span><span>本机工作区</span><span class="app-version">V3.0</span></div>
    </aside>
    <div class="app-main">
      <div class="app-topbar">
        <div class="breadcrumb">
          <button ref="menuTrigger" type="button" class="icon-button mobile-menu" aria-label="打开导航" aria-controls="workbench-nav"
            :aria-expanded="menuOpen" @click="menuOpen ? closeMenu() : openMenu()"><Menu :size="20" /></button>
          <RouterLink :to="link('overview')">工作台</RouterLink><ChevronRight :size="14" aria-hidden="true" /><span>{{ title }}</span>
        </div>
        <div class="topbar-controls">
          <label class="project-picker">当前项目<select :value="workbench.projectId" :disabled="!workbench.initialized" @change="switchProject">
            <option value="">选择项目</option><option v-for="project in workbench.projects" :key="project.id" :value="project.id">{{ project.name }}</option>
          </select><ChevronDown :size="14" aria-hidden="true" /></label>
          <span class="connection" role="status"><span class="connection-dot" :class="workbench.health"></span>{{ statusText }}</span>
          <button type="button" class="icon-button" aria-label="刷新状态" title="刷新状态" @click="workbench.refresh()"><RefreshCw :size="16" /></button>
        </div>
      </div>
      <main id="workspace-main" class="workspace-main" tabindex="-1">
        <div v-if="group && group.pages.length > 1" class="route-tabs" aria-label="工作区页面">
          <RouterLink v-for="page in group.pages" :key="page" :to="link(page)" :data-page="page">{{ destinations[page].label }}</RouterLink>
        </div>
        <h1 v-if="name !== 'overview'" class="workspace-title">{{ route.meta.title }}</h1>
        <p v-if="workbench.error" class="error" role="alert">{{ workbench.error }} <button @click="workbench.error = ''">关闭</button></p>
        <p v-else-if="workbench.initialized && route.query.project && !workbench.projectId" class="error" role="alert">链接中的项目不可用，请选择现有项目。</p>
        <slot v-if="workbench.initialized" />
        <p v-else-if="!workbench.error" class="empty" role="status">正在读取项目…</p>
      </main>
    </div>
  </div>
</template>
