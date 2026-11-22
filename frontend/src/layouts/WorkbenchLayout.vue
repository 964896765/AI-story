<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowUpRight, Bell, ChevronDown, Diamond, Menu, Moon, PanelLeftClose, PanelLeftOpen, RefreshCw, Search, Sun, X } from 'lucide-vue-next'
import { useRouter } from 'vue-router'
import { destinations, navigation, workspaces, type Destination } from '../router/navigation'
import { useWorkspace } from '../router/workspace'
import { appearance, toggleAppearance } from '../stores/appearance'

const { route, workbench, link } = useWorkspace()
const router = useRouter()
const menuOpen = ref(false)
const menuTrigger = ref<HTMLButtonElement | null>(null)
const sidebar = ref<HTMLElement | null>(null)
const navigator = ref<HTMLDialogElement|null>(null)
const notifications = ref<HTMLDialogElement|null>(null)
const commandInput = ref<HTMLInputElement|null>(null)
const commandQuery = ref('')
const compact = ref(false)
const name = computed(() => route.name as Destination)
const group = computed(() => workspaces.find(item => item.pages.includes(name.value)))
const title = computed(() => name.value === 'overview' ? '项目总览' : group.value?.label || String(route.meta.title))
const descriptions: Partial<Record<Destination,string>> = {
  director:'整理制作指令，确认执行范围后交接到对应工作区。',
  wizard:'从立项到交付，逐步核对制作条件。',
  assets:'查找、预览和导入项目素材，随时核对授权来源。',
  analysis:'在同一时间轴核对镜头、字幕、波形和画面文字。',
  story:'整理剧本和分集，比较版本后再交给制作。',
  adaptation:'固定原稿和模型配置，逐稿审核后保存新版本。',
  characters:'管理角色、场景和固定参考。',
  storyboard:'编辑镜头描述、时长和角色场景引用。',
  bible:'核对角色、道具和跨集状态。',
  generation:'比较本地生成候选，预览并采纳合适的片段。',
  voice:'试听本机配音，校对字幕再纳入制作。',
  timeline:'编辑剪辑点与轨道，保存版本后渲染。',
  video:'批量设置裁剪、画幅、字幕和音轨。',
  production:'查看批次、运行中的任务和失败原因，按需返工。',
  quality:'预览和下载经过技术验证的成片。',
  guardian:'按镜头检查质量证据、版本和交付条件。',
  library:'核对素材授权，整理和下载交付文件。',
  operations:'管理发行记录、推广文件和结算。',
  system:'检查数据库、视频工具与后台进程。',
  models:'配置文本供应商和项目预算，查看用量记录。',
}
const commandResults = computed(() => workspaces.flatMap(workspace => workspace.pages.map(page => ({
  page, label:destinations[page].label, group:workspace.label, icon:workspace.icon,
}))).filter(item => {
  const value = commandQuery.value.trim().toLocaleLowerCase()
  return (item.label + item.group + destinations[item.page].path).toLocaleLowerCase().includes(value)
}))
const statusText = computed(() => workbench.health === 'ready' && workbench.initialized ? '服务就绪' :
  workbench.health === 'unavailable' ? '服务未就绪' : '检查服务中')
const attention = computed(() => (workbench.overview?.draft_review_count || 0) +
  (workbench.overview?.latest_run?.reviews || 0) + (workbench.overview?.latest_run?.rework || 0))
const batch = computed(()=>workbench.overview?.latest_run)
let overviewPoll: ReturnType<typeof setInterval>|undefined

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

function toggleCompact() {
  compact.value = !compact.value
  try { localStorage.setItem('ai-story:compact-navigation', String(compact.value)) } catch { /* optional */ }
}

async function openNavigator() {
  if (!navigator.value || navigator.value.open) return
  commandQuery.value = ''
  navigator.value.showModal()
  await nextTick()
  commandInput.value?.focus()
}

async function openCommand(page: Destination) {
  navigator.value?.close()
  await router.push(link(page))
  document.getElementById('workspace-main')?.focus()
}

function keyboard(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === 'k') {
    event.preventDefault()
    void openNavigator()
  }
}

onMounted(() => {
  try { compact.value = localStorage.getItem('ai-story:compact-navigation') === 'true' } catch { /* optional */ }
  window.addEventListener('keydown',keyboard)
  void workbench.initialize()
  overviewPoll = setInterval(() => { if (document.visibilityState==='visible') void workbench.refreshOverview() }, 15000)
})
onUnmounted(() => { window.removeEventListener('keydown',keyboard); clearInterval(overviewPoll) })
</script>

<template>
  <div class="app-shell" :class="{ 'is-compact': compact }" @keydown.esc="closeMenu">
    <a class="skip-link" href="#workspace-main">跳到工作区</a>
    <button v-if="menuOpen" type="button" class="mobile-scrim" aria-label="关闭导航" @click="closeMenu"></button>
    <aside ref="sidebar" class="app-sidebar" :class="{ 'is-open': menuOpen }" id="workbench-nav">
      <RouterLink class="app-brand" :to="link('overview')">
        <span class="brand-mark"><Diamond :size="21" :stroke-width="1.7" aria-hidden="true" /></span>
        <span class="brand-text"><strong>AI STORY</strong><small>PRISM STUDIO · V3.0</small></span>
      </RouterLink>
      <button class="icon-button mobile-close" type="button" aria-label="关闭导航" @click="closeMenu"><X :size="18" /></button>
      <nav aria-label="工作区">
        <div v-for="section in navigation" :key="section.label" class="nav-group">
          <p>{{ section.label }}</p>
          <RouterLink v-for="item in section.links" :key="item.label" class="nav-item"
            :class="{ 'nav-active': group?.label === item.label }" :to="link(item.pages[0])" :data-workspace="item.label"
            :aria-label="item.label" :title="item.label">
            <component :is="item.icon" :size="17" :stroke-width="1.7" aria-hidden="true" />
            <span class="nav-label">{{ item.label }}</span>
          </RouterLink>
        </div>
      </nav>
      <div class="sidebar-footer"><div class="workspace-label"><strong><span class="connection-dot" :class="workbench.health"></span> 本机工作空间</strong><small>{{ statusText }}</small></div>
        <button class="icon-button compact-nav" type="button" :aria-label="compact ? '展开侧栏' : '收起侧栏'" :title="compact ? '展开侧栏' : '收起侧栏'" @click="toggleCompact">
          <PanelLeftOpen v-if="compact" :size="15" aria-hidden="true" /><PanelLeftClose v-else :size="15" aria-hidden="true" />
        </button>
      </div>
    </aside>
    <div class="app-main">
      <div class="app-topbar">
        <div class="breadcrumb">
          <button ref="menuTrigger" type="button" class="icon-button mobile-menu" aria-label="打开导航" aria-controls="workbench-nav"
            :aria-expanded="menuOpen" @click="menuOpen ? closeMenu() : openMenu()"><Menu :size="20" /></button>
          <RouterLink :to="link('overview')">工作空间 /</RouterLink><strong>{{ title }}</strong>
          <label class="project-picker">当前项目<select aria-label="当前项目" :value="workbench.projectId" :disabled="!workbench.initialized" @change="switchProject">
            <option value="">选择项目</option><option v-for="project in workbench.projects" :key="project.id" :value="project.id">{{ project.name }}</option>
          </select><ChevronDown :size="14" aria-hidden="true" /></label>
        </div>
        <div class="topbar-controls">
          <button type="button" class="command-trigger" aria-label="搜索工作区" title="全局搜索 (Ctrl+K)" @click="openNavigator">
            <Search :size="16" aria-hidden="true" /><span>全局搜索</span><kbd>Ctrl K</kbd>
          </button>
          <button v-if="attention" type="button" class="review-shortcut" @click="notifications?.showModal()">待处理 {{attention}}</button>
          <button type="button" class="icon-button" aria-label="切换主题" :title="appearance==='light'?'切换深色主题':'切换浅色主题'" @click="toggleAppearance">
            <Moon v-if="appearance==='light'" :size="17" aria-hidden="true" /><Sun v-else :size="17" aria-hidden="true" />
          </button>
          <button type="button" class="icon-button notice-button" aria-label="通知" @click="notifications?.showModal()"><Bell :size="17" aria-hidden="true" /></button>
          <button type="button" class="icon-button refresh-button" aria-label="刷新状态" title="刷新状态" @click="workbench.refresh()"><RefreshCw :size="16" /></button>
        </div>
      </div>
      <main id="workspace-main" class="workspace-main" tabindex="-1">
        <header v-if="name !== 'overview'" class="workspace-masthead">
          <div class="workspace-heading">
            <div><h1 class="workspace-title">{{ route.meta.title }}</h1><p v-if="descriptions[name]">{{ descriptions[name] }}</p></div>
          </div>
          <div v-if="group && group.pages.length > 1" class="route-tabs" aria-label="工作区页面">
            <RouterLink v-for="page in group.pages" :key="page" :to="link(page)" :data-page="page">{{ destinations[page].label }}</RouterLink>
          </div>
        </header>
        <p v-if="workbench.error" class="error" role="alert">{{ workbench.error }} <button @click="workbench.error = ''">关闭</button></p>
        <p v-else-if="workbench.initialized && route.query.project && !workbench.projectId" class="error" role="alert">链接中的项目不可用，请选择现有项目。</p>
        <slot v-if="workbench.initialized" />
        <p v-else-if="!workbench.error" class="empty" role="status">正在读取项目…</p>
      </main>
      <footer class="workbench-status"><span role="status"><span class="connection-dot" :class="workbench.health"></span> {{statusText}}</span>
        <span v-if="workbench.project">{{workbench.project.name}}</span><span v-if="batch">最近批次 {{batch.passed}} / {{batch.episode_count}} 集通过</span>
        <span v-if="workbench.overview" class="status-cost">付费调用 {{workbench.overview.live_authorized?'已授权':'关闭'}}</span></footer>
    </div>
    <dialog ref="notifications" class="workspace-command" aria-labelledby="notifications-title">
      <header><h2 id="notifications-title">项目通知</h2><button type="button" class="icon-button" aria-label="关闭通知" @click="notifications?.close()"><X :size="16" /></button></header>
      <p v-if="!workbench.projectId" class="empty">请先选择项目。</p>
      <p v-else-if="workbench.overviewPending" role="status">正在读取项目待办…</p>
      <p v-else-if="workbench.overviewError" class="error" role="alert">{{workbench.overviewError}}</p>
      <p v-else-if="!attention" class="empty">没有待审核或待返工项目。</p>
      <div v-else class="notification-list">
        <RouterLink v-for="episode in batch?.attention_episodes || []" :key="episode.number" :to="link('production',{run:batch?.id,episode:String(episode.number)})" @click="notifications?.close()">
          第 {{episode.number}} 集 · {{episode.status==='needs_rework'?'需返工':'待复核'}}</RouterLink>
        <RouterLink v-for="item in workbench.overview?.draft_reviews || []" :key="item.id" :to="link('adaptation',{call:item.id})" @click="notifications?.close()">{{item.title}} · 改编待审核</RouterLink>
      </div>
    </dialog>
    <dialog ref="navigator" class="workspace-command" aria-labelledby="workspace-command-title">
      <header><h2 id="workspace-command-title">前往工作区</h2><button type="button" class="icon-button" aria-label="关闭搜索" @click="navigator?.close()"><X :size="16" aria-hidden="true" /></button></header>
      <form @submit.prevent="commandResults[0] && openCommand(commandResults[0].page)">
        <label>搜索页面<input ref="commandInput" v-model="commandQuery" type="search" placeholder="输入名称，例如 多轨时间轴" autocomplete="off"></label>
      </form>
      <p v-if="!commandResults.length" class="empty">没有匹配的工作区。</p>
      <div v-else class="command-list">
        <button v-for="item in commandResults" :key="item.page" type="button" @click="openCommand(item.page)">
          <component :is="item.icon" :size="16" aria-hidden="true" /><span>{{ item.label }}</span>
          <small>{{ item.group }}</small><ArrowUpRight :size="14" aria-hidden="true" />
        </button>
      </div>
    </dialog>
  </div>
</template>
