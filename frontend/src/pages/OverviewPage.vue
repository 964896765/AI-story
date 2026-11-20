<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, onUnmounted, ref, watch } from 'vue'
import { ArrowDownToLine, ArrowRight, Clapperboard, ClipboardCheck, Film, FolderOpen, Image, Layers3,
  ListChecks, Play, Plus, ScrollText, SquarePen, Upload, Wallet } from 'lucide-vue-next'
import { NButton, NTag } from 'naive-ui'
import { api } from '../services/api'
import { useWorkspace } from '../router/workspace'
import type { Destination } from '../router/navigation'
import type { ProjectOverview, RecentRender } from '../types/workbench'
import WorkspacePanel from '../components/ui/WorkspacePanel.vue'
const OutputPreview = defineAsyncComponent(() => import('../components/ui/OutputPreview.vue'))

const { workbench, link, go } = useWorkspace()
const overview = ref<ProjectOverview | null>(null)
const pending = ref(false), error = ref(''), preview = ref(''), previewTitle = ref('')
const rejectedCover = ref('')
let request: AbortController | undefined
let timer: ReturnType<typeof setInterval> | undefined
const latest = computed(() => overview.value?.latest_run)
const firstOutput = computed(() => overview.value?.recent_renders[0])
const reviews = computed(() => (overview.value?.draft_review_count || 0) + (latest.value?.reviews || 0))
const rework = computed(() => latest.value?.rework || 0)
const totalTasks = computed(() => Object.values(overview.value?.task_counts || {}).reduce((total, count) => total + count, 0))
const stateText: Record<string, string> = { processing: '正在生产', needs_rework: '待返工', needs_review: '待复核', passed: '批次已通过', cancelled: '批次已停止' }
const headlineState = computed(() => latest.value ? stateText[latest.value.status] || '已登记批次' :
  (overview.value?.render_count ? '已有成片' : overview.value?.asset_count ? '项目已建档' : '待导入素材'))
const stageLinks = computed(() => {
  const data = overview.value
  const story = data?.story_counts || {}
  return [
    { label: '项目素材', value: `${data?.asset_count || 0} 项`, icon: FolderOpen, page: 'assets' },
    { label: '剧本与创作', value: `${(story.novel || 0) + (story.script || 0) + (story.episode || 0)} 份`, icon: ScrollText, page: 'story' },
    { label: '分镜', value: `${story.storyboard || 0} 份`, icon: Layers3, page: 'storyboard' },
    { label: '时间轴', value: `${story.timeline || 0} 份`, icon: Film, page: 'timeline' },
    { label: '批次质检', value: latest.value ? `${latest.value.passed} / ${latest.value.episode_count} 集通过` : '暂无批次', icon: ClipboardCheck, page: 'production' },
    { label: '授权交付', value: `${data?.delivery_count || 0} 份`, icon: ArrowDownToLine, page: 'library' },
  ] as const
})
const nextPage = computed<Destination>(() => latest.value ? 'production' : overview.value?.render_count ? 'quality' :
  overview.value?.story_counts.timeline ? 'timeline' : overview.value?.story_counts.storyboard ? 'storyboard' :
    overview.value?.story_counts.script ? 'story' : 'assets')

function money(micros: string, currency: string) {
  const value = BigInt(micros)
  const fraction = (value % 1_000_000n).toString().padStart(6, '0').replace(/0+$/, '').padEnd(2, '0')
  return `${currency === 'CNY' ? '¥' : currency + ' '}${(value / 1_000_000n).toLocaleString('zh-CN')}.${fraction}`
}

async function refresh() {
  if (!workbench.projectId) return
  request?.abort()
  const latestRequest = new AbortController()
  request = latestRequest
  pending.value = !overview.value
  try {
    const result = await api<ProjectOverview>(`/projects/${workbench.projectId}/overview`, { signal: latestRequest.signal })
    if (!latestRequest.signal.aborted) { overview.value = result; error.value = '' }
  } catch (failure) {
    if (!latestRequest.signal.aborted) error.value = String(failure)
  } finally {
    if (request === latestRequest) { pending.value = false; request = undefined }
  }
}

function openOutput(item: RecentRender) {
  previewTitle.value = item.title
  preview.value = item.id
}
function showReviews() { document.getElementById('pending-review')?.scrollIntoView({ block: 'start' }) }

watch(() => workbench.refreshCount, () => { void refresh() })
watch(() => workbench.projectId, () => { overview.value = null; preview.value = ''; void refresh() })
onMounted(() => {
  void refresh()
  timer = setInterval(() => { if (!request && document.visibilityState !== 'hidden') void refresh() }, 15000)
})
onUnmounted(() => { clearInterval(timer); request?.abort() })
</script>

<template>
  <div class="overview">
    <div class="overview-heading">
      <div><h1>项目总览</h1><p>{{ workbench.projects.length }} 个项目</p></div>
      <NButton type="primary" @click="go('assets', { create: '1' })"><template #icon><Plus :size="17" /></template>新建项目</NButton>
    </div>
    <p v-if="error" class="error" role="alert">{{ error }} <button @click="refresh">重新读取</button></p>
    <p v-if="pending" class="empty" role="status">正在读取项目总览…</p>
    <WorkspacePanel v-else-if="!workbench.project" title="开始制作">
      <p class="hint">{{ workbench.projects.length ? '通过顶部项目选择器打开一个项目。' : '新建项目后即可导入素材、建立剧本和查看任务。' }}</p>
    </WorkspacePanel>
    <template v-else-if="overview">
      <div class="project-feature" :class="{ 'has-cover': (overview.cover && rejectedCover !== overview.cover.id) || firstOutput }">
        <div class="feature-copy">
          <div class="feature-label">当前项目 <NTag size="small" :type="latest?.status === 'passed' ? 'success' : latest?.status === 'needs_rework' ? 'warning' : 'info'" round>{{ headlineState }}</NTag></div>
          <h2 data-testid="overview-project">{{ workbench.project.name }}</h2>
          <p v-if="workbench.project.description" class="project-description">{{ workbench.project.description }}</p>
          <div v-if="latest" class="feature-batch"><Clapperboard :size="15" />最近批次 {{ latest.passed }} / {{ latest.episode_count }} 集通过</div>
          <div v-else class="feature-batch"><FolderOpen :size="15" />{{ overview.asset_count }} 项素材 · {{ overview.render_count }} 部已验证成片</div>
          <div class="feature-actions">
            <NButton type="primary" @click="go(nextPage, latest ? { run: latest.id } : {})">继续制作 <ArrowRight :size="15" /></NButton>
            <RouterLink :to="link('assets', { import:'1' })"><Upload :size="15" aria-hidden="true" />导入素材</RouterLink>
          </div>
        </div>
        <figure class="feature-art">
          <img v-if="overview.cover && rejectedCover !== overview.cover.id" :src="`/api/assets/${overview.cover.id}/media`" :alt="overview.cover.name" @error="rejectedCover = overview.cover!.id">
          <video v-else-if="firstOutput" class="feature-video" :src="`/api/tasks/${firstOutput.id}/output#t=0.15`" preload="metadata" muted playsinline aria-label="最近成片画面"></video>
          <div v-else class="cover-empty"><Image :size="26" :stroke-width="1.35" aria-hidden="true" /><span>暂无项目参考图</span><RouterLink :to="link('assets',{import:'1'})">导入自有图片</RouterLink></div>
          <figcaption v-if="overview.cover && rejectedCover !== overview.cover.id">项目参考图</figcaption>
          <figcaption v-else-if="firstOutput">最近成片画面</figcaption>
        </figure>
      </div>
      <div class="signals" aria-label="项目指标">
        <RouterLink class="signal" :to="link('production')">
          <span><ListChecks :size="16" /> 任务记录</span><strong data-testid="task-total">{{ totalTasks }}</strong>
          <small>{{ overview.task_counts.running || 0 }} 执行中 · {{ overview.task_counts.queued || 0 }} 排队 · {{ overview.task_counts.failed || 0 }} 失败</small>
        </RouterLink>
        <button class="signal review-signal" type="button" @click="showReviews">
          <span><ClipboardCheck :size="16" /> 待处理</span><strong data-testid="review-total">{{ reviews + rework }}</strong>
          <small>{{ reviews }} 待审 · {{ rework }} 待返工（最近批次）</small>
        </button>
        <div class="signal cost-signal">
          <span><Wallet :size="16" /> 已记录 API 费用</span>
          <strong data-testid="overview-cost">{{ overview.costs.length ? overview.costs.map(row => money(row.amount_micros, row.currency)).join(' · ') : '¥0.00' }}</strong>
          <small>{{ overview.costs.reduce((total, row) => total + row.unknown, 0) }} 笔费用未知 · {{ overview.live_authorized ? '真实调用已授权' : '真实调用关闭' }}</small>
          <small>真实预算 {{ overview.live_budgets.length ? overview.live_budgets.map(row => money(row.limit_micros, row.currency)).join(' · ') : '¥0.00' }}</small>
        </div>
        <RouterLink class="signal" :to="link('quality')">
          <span><Film :size="16" /> 已验证成片</span><strong data-testid="output-total">{{ overview.render_count }}</strong>
          <small>{{ overview.delivery_count }} 份已生成交付包</small>
        </RouterLink>
      </div>
      <WorkspacePanel title="制作流程">
        <template #action><RouterLink class="panel-cta" :to="link('production')">打开生产队列 <ArrowRight :size="14" /></RouterLink></template>
        <div class="stage-track">
          <RouterLink v-for="stage in stageLinks" :key="stage.page" class="stage-step" :to="link(stage.page, stage.page === 'production' && latest ? { run: latest.id } : {})">
            <span class="step-icon"><component :is="stage.icon" :size="17" :stroke-width="1.6" /></span>
            <span><strong>{{ stage.label }}</strong><small>{{ stage.value }}</small></span>
          </RouterLink>
        </div>
      </WorkspacePanel>
      <div class="overview-details">
        <WorkspacePanel title="最近成片">
          <template #action><RouterLink :to="link('quality')">查看成片 <ArrowRight :size="13" /></RouterLink></template>
          <div v-if="overview.recent_renders.length" class="film-grid">
            <article v-for="item in overview.recent_renders" :key="item.id">
              <button class="film-thumbnail" :aria-label="`预览成片 ${item.title}`" @click="openOutput(item)">
                <video :src="`/api/tasks/${item.id}/output#t=0.15`" preload="metadata" muted playsinline></video><span><Play :size="16" fill="currentColor" /></span>
              </button>
              <div class="film-information">
                <strong :title="item.title">{{ item.title }}</strong>
                <small>{{ item.duration === null ? '时长待读取' : `${item.duration.toFixed(1)} 秒` }} · {{ new Date(item.finished_at).toLocaleDateString('zh-CN') }}</small>
                <small v-if="item.width && item.height" class="film-dimensions">{{ item.width }} × {{ item.height }}</small>
              </div>
            </article>
          </div>
          <p v-else class="panel-empty">当前项目还没有已验证成片。</p>
        </WorkspacePanel>
        <WorkspacePanel id="pending-review" title="待审与返工">
          <div v-if="reviews || rework" class="review-list">
            <RouterLink v-if="latest && (latest.reviews || latest.rework)" :to="link('production', { run: latest.id })">
              <ClipboardCheck :size="18" /><span><strong>最近批次</strong><small>{{ latest.reviews }} 集待复核 · {{ latest.rework }} 集待返工</small></span><ArrowRight :size="14" />
            </RouterLink>
            <RouterLink v-for="item in overview.draft_reviews" :key="item.id" :to="link('adaptation', { call: item.id })">
              <SquarePen :size="18" /><span><strong>{{ item.title }}</strong><small>{{ item.simulated ? '模拟改编 · 待审' : '模型改编 · 待审' }}</small></span><ArrowRight :size="14" />
            </RouterLink>
            <RouterLink v-if="overview.draft_review_count > overview.draft_reviews.length" :to="link('adaptation')">查看其余待审稿</RouterLink>
          </div>
          <p v-else class="panel-empty">暂无待审草稿或最近批次返工。</p>
        </WorkspacePanel>
      </div>
    </template>
    <OutputPreview v-if="preview" v-model="preview" :title="previewTitle" />
  </div>
</template>

<style scoped>
.overview { display:grid; gap:16px }
.overview-heading { display: flex; justify-content: space-between; align-items: center; gap: 14px }
.overview-heading h1 { font-size: 31px; font-weight: 680; line-height: 1.25; letter-spacing: -.7px; margin: 0 0 6px }
.overview-heading p { margin: 0; font-size: 13px; color: var(--ink-muted) }
.project-feature { display:grid; grid-template-columns:minmax(0,1.08fr) minmax(240px,1fr); min-height:254px; position:relative; isolation:isolate; background:linear-gradient(120deg,#1b303a,#131e28); border:1px solid #3c5866; border-radius:13px; overflow:hidden }
.project-feature.has-cover { grid-template-columns:minmax(0,1fr) minmax(0,1fr) }
.feature-copy { padding:clamp(20px,3vw,43px); align-self:center; min-width:0; z-index:1 }
.feature-label { display: flex; align-items: center; flex-wrap: wrap; gap: 9px; font-size: 12px; color: var(--ink-muted) }
.feature-copy h2 { font-size:clamp(27px,3.15vw,50px); letter-spacing:-.035em; line-height:1.18; margin:10px 0; overflow-wrap:anywhere }
.project-description { color: var(--ink-secondary); margin: 0; max-width: 58ch; display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2; overflow: hidden }
.feature-batch { margin-top: 9px; display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--ink-muted) }
.feature-actions { display: flex; align-items: center; flex-wrap: wrap; gap: 13px; margin-top: 18px }
.feature-actions button svg { margin-left:6px }
.feature-actions a,.panel-cta { display:inline-flex; align-items:center; gap:6px; font-size:12px; text-decoration:none }
.feature-art { position:relative; display:grid; place-items:center; min-height:197px; margin:0; overflow:hidden; border-left:1px solid var(--line-soft) }
.project-feature.has-cover .feature-art { background:#152027 }
.feature-art img,.feature-art video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; border-radius: 0 }
.feature-art figcaption { position:absolute; right:12px; bottom:12px; padding:4px 9px; background:#0d171de8; color:#e1f5f4; font-size:11px; border-radius:5px }
.cover-empty { align-self:stretch; width:100%; display:grid; place-content:center; justify-items:center; gap:10px; color:var(--ink-muted); background:repeating-linear-gradient(135deg,#18242e,#18242e 13px,#1c2b36 13px,#1c2b36 14px); font-size:12px }
.cover-empty a { text-decoration:none }
.signals { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); border: 1px solid var(--line); border-radius: var(--radius); background: var(--surface-panel) }
.signal { display: flex; flex-direction: column; gap: 5px; min-width: 0; padding: 14px 17px; text-decoration: none; color: var(--ink); border-right: 1px solid var(--line) }
.signal:last-child { border-right: 0 }
a.signal:hover { background: var(--surface-raised) }
button.review-signal { border: 0; border-right: 1px solid var(--line); border-radius: 0; background: none; color: var(--ink); text-align: left; padding: 14px 17px }
.signal > span { color: var(--ink-secondary); font-size: 13px; display: flex; align-items: center; gap: 8px }
.signal > span svg { color: var(--accent) }
.signal strong { font-size: 27px; line-height: 1.16; font-variant-numeric: tabular-nums; overflow-wrap: anywhere }
.cost-signal strong { font-size: 23px }
.signal small,.stage-step small,.film-grid small,.review-list small { color: var(--ink-muted); font-size: 11px }
.stage-track { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 7px }
.stage-step { display: flex; align-items: center; gap: 8px; padding: 8px 5px; text-decoration: none; color: var(--ink-secondary); min-width: 0; border-radius: 6px }
.stage-step:hover { background: var(--surface-raised) }
.step-icon { display:grid; place-items:center; width:33px; height:33px; flex:0 0 33px; border:1px solid #3b6868; border-radius:7px; color:var(--accent); background:var(--accent-surface) }
.stage-step strong,.stage-step small { display: block }
.stage-step strong { white-space: nowrap; font-size: 12px }
.overview-details { display: grid; grid-template-columns: minmax(0, 1.65fr) minmax(260px, 1fr); gap: 17px; align-items: start }
.overview-details a { display: inline-flex; align-items: center; gap: 5px; text-decoration: none; font-size: 12px }
.film-grid { display: grid; grid-template-columns: repeat(auto-fit,minmax(min(125px,100%),1fr)); gap: 12px }
.film-grid article { min-width: 0 }
.film-grid article:only-child { display: grid; grid-template-columns: minmax(100px, 43%) minmax(0, 1fr); align-items: center; column-gap: 14px }
.film-information { min-width: 0 }
.film-grid strong,.film-grid small { display: block; margin-top: 4px; width: 100%; overflow: hidden; white-space: nowrap; text-overflow: ellipsis }
.film-grid strong { font-size: 12px }
.film-thumbnail { display: block; width: 100%; aspect-ratio: 16/9; position: relative; overflow: hidden; padding: 0 !important; background: #17161e !important }
.film-thumbnail video { display: block; width: 100%; height: 100%; object-fit: cover }
.film-thumbnail span { position: absolute; bottom: 7px; left: 7px; display: grid; place-items: center; width: 29px; height: 29px; border-radius: 7px; background: #171521e8; color: #e7defd }
.panel-empty { margin: 0; padding: 8px 0 5px; font-size: 13px; color: var(--ink-muted) }
.review-list { display: grid; gap: 6px }
.review-list a { color: var(--ink-secondary); padding: 9px 3px; gap: 9px; border-top: 1px solid var(--line-soft) }
.review-list a > span { flex: 1; min-width: 0; overflow-wrap: anywhere }
.review-list a strong,.review-list a small { display: block }
.review-list svg { color: var(--accent); flex: 0 0 auto }
#pending-review { scroll-margin-top: calc(var(--topbar-height) + 13px) }
@media(max-width: 1250px) { .stage-track { grid-template-columns: repeat(3, 1fr) } }
@media(max-width: 1050px) { .signals { grid-template-columns: repeat(2, 1fr) } .signal:nth-child(2) { border-right: 0 } .signal:nth-child(-n+2) { border-bottom: 1px solid var(--line) } }
@media(max-width: 900px) { .overview-details { grid-template-columns: 1fr } .project-feature { grid-template-columns: minmax(0,1fr) minmax(170px,.7fr) } }
@media(max-width: 560px) {
  .overview { gap: 13px } .overview-heading h1 { font-size: 25px }
  .project-feature,.project-feature.has-cover { grid-template-columns:1fr } .feature-art { min-height:145px; border-left:0; border-top:1px solid var(--line) }
  .signal,button.review-signal { padding: 11px } .signal strong { font-size: 22px }
  .stage-track { grid-template-columns: repeat(2, minmax(0,1fr)) }
}
</style>
