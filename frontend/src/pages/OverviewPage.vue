<script setup lang="ts">
import { computed, defineAsyncComponent, ref, watch } from 'vue'
import type { LocationQueryRaw } from 'vue-router'
import { ArrowRight, Check, ClipboardCheck, Film, Image, Play, Plus, SquarePen, Upload } from 'lucide-vue-next'
import { useWorkspace } from '../router/workspace'
import type { Destination } from '../router/navigation'
import type { RecentRender } from '../types/workbench'
import WorkspacePanel from '../components/ui/WorkspacePanel.vue'
const OutputPreview = defineAsyncComponent(() => import('../components/ui/OutputPreview.vue'))

const { workbench, link, go } = useWorkspace()
const overview = computed(() => workbench.overview)
const latest = computed(() => overview.value?.latest_run)
const firstOutput = computed(() => overview.value?.recent_renders[0])
const preview = ref(''), previewTitle = ref(''), rejectedCover = ref('')
const reviews = computed(() => (overview.value?.draft_review_count || 0) + (latest.value?.reviews || 0))
const rework = computed(() => latest.value?.rework || 0)
const totalTasks = computed(() => Object.values(overview.value?.task_counts || {}).reduce((sum, count) => sum+count,0))
const stateText:Record<string,string> = { processing:'正在生产', needs_rework:'待返工', needs_review:'待复核', passed:'批次已通过', cancelled:'批次已停止' }
const headlineState = computed(() => latest.value ? stateText[latest.value.status] || '已登记批次' : overview.value?.render_count ? '已有成片' : overview.value?.asset_count ? '项目已建档' : '待导入素材')
const flow = computed(() => {
  const story = overview.value?.story_counts || {}
  return [
    { label:'立项与预算', info:`${overview.value?.asset_count || 0} 项素材`, ready:!!overview.value?.asset_count, page:'assets' },
    { label:'剧本与故事', info:`${(story.novel || 0)+(story.script || 0)+(story.episode || 0)} 份文本`, ready:!!story.script, page:'story' },
    { label:'人物场景', info:`${(story.character || 0)+(story.scene || 0)} 项角色和场景`, ready:!!(story.character || story.scene), page:'characters' },
    { label:'镜头规划', info:`${story.storyboard || 0} 份分镜`, ready:!!story.storyboard, page:'storyboard' },
    { label:'模型生成', info:overview.value?.live_authorized?'真实调用已授权':'本机候选与配音', ready:!!story.generation_plan, page:'generation' },
    { label:'剪辑交付', info:`${overview.value?.delivery_count || 0} 份已验证交付包`, ready:!!overview.value?.delivery_count, page:'library' },
  ] as const
})
const nextStep = computed<{ page:Destination; label:string; query?:LocationQueryRaw }>(() => {
  const batch = latest.value
  if (batch) {
    const delivery = overview.value?.latest_delivery
    if (batch.status==='passed') {
      if (delivery?.status==='succeeded') return {page:'operations',label:'打开人工发行',query:{package:delivery.id}}
      return {page:'library',label:delivery && ['queued','running'].includes(delivery.status)?'查看交付任务':'核对授权与交付',query:{run:batch.id}}
    }
    const first = batch.attention_episodes?.[0]
    return {page:'production',label:first?'查看待处理分集':'查看生产批次',query:first?{run:batch.id,episode:String(first.number)}:{run:batch.id}}
  }
  const draft = overview.value?.draft_reviews[0]
  if (draft) return {page:'adaptation',label:'审核改编稿',query:{call:draft.id}}
  const story = overview.value?.story_counts || {}
  const page = overview.value?.render_count?'quality':story.timeline?'timeline':story.storyboard?'storyboard':story.script?'story':'assets'
  return {page,label:'继续制作'}
})

function money(micros:string,currency:string) {
  const value = BigInt(micros)
  const absolute = value<0n ? -value : value
  const fraction = (absolute%1_000_000n).toString().padStart(6,'0').replace(/0+$/,'').padEnd(2,'0')
  return `${value<0n?'-':''}${currency==='CNY'?'¥':currency+' '}${(absolute/1_000_000n).toLocaleString('zh-CN')}.${fraction}`
}
function openOutput(item:RecentRender) { preview.value=item.id; previewTitle.value=item.title }
function showReviews() { document.getElementById('pending-review')?.scrollIntoView({block:'start'}) }
watch(() => workbench.projectId, () => { preview.value=''; rejectedCover.value='' })
</script>

<template>
  <div class="overview">
    <header class="overview-heading">
      <div><h1>项目总览</h1><p>查看全剧进度、待审核事项和已入账费用。</p></div>
      <button type="button" class="primary prism-action" @click="go('assets',{create:'1'})"><Plus :size="16" aria-hidden="true" />新建项目</button>
    </header>
    <p v-if="workbench.overviewError" class="error" role="alert">{{workbench.overviewError}} <button @click="workbench.refreshOverview()">重新读取</button></p>
    <p v-if="workbench.overviewPending" class="empty" role="status">正在读取项目总览…</p>
    <WorkspacePanel v-else-if="!workbench.project" title="开始制作">
      <p class="hint">{{workbench.projects.length?'在顶部选择项目。':'新建项目后即可导入素材和建立剧本。'}}</p>
    </WorkspacePanel>
    <template v-else-if="overview">
      <div class="project-feature" :class="{'has-cover':(overview.cover && rejectedCover!==overview.cover.id) || firstOutput}">
        <div class="feature-copy">
          <div class="feature-label">当前制作 <span>{{headlineState}}</span></div>
          <h2 data-testid="overview-project">{{workbench.project.name}}</h2>
          <p class="project-description">{{workbench.project.description || `${overview.asset_count} 项素材 · ${overview.render_count} 部已验证成片`}}</p>
          <p v-if="latest" class="feature-batch">最近批次 {{latest.passed}} / {{latest.episode_count}} 集通过</p>
          <div class="feature-actions">
            <button type="button" class="prism-action hero-action" @click="go(nextStep.page,nextStep.query)">{{nextStep.label}} <ArrowRight :size="15" aria-hidden="true" /></button>
            <RouterLink :to="link('assets',{import:'1'})"><Upload :size="15" aria-hidden="true" />导入素材</RouterLink>
          </div>
        </div>
        <figure v-if="(overview.cover && rejectedCover!==overview.cover.id) || firstOutput" class="feature-art">
          <img v-if="overview.cover && rejectedCover!==overview.cover.id" :src="`/api/assets/${overview.cover.id}/media`" :alt="overview.cover.name" @error="rejectedCover=overview.cover!.id">
          <video v-else-if="firstOutput" :src="`/api/tasks/${firstOutput.id}/output#t=0.15`" class="feature-video" preload="metadata" muted playsinline aria-label="最近成片画面"></video>
        </figure>
      </div>

      <div class="signals" aria-label="项目指标">
        <RouterLink class="signal" :to="link('bible')"><span>分集计划</span><strong>{{latest?.episode_count ?? overview.story_counts.episode ?? 0}}</strong><small>{{latest?`${latest.passed} 集通过`:'已登记分集'}}</small></RouterLink>
        <button class="signal" type="button" @click="showReviews"><span>待处理审核</span><strong data-testid="review-total">{{reviews+rework}}</strong><small>{{reviews}} 待审 · {{rework}} 待返工</small></button>
        <RouterLink class="signal" :to="link('production')"><span>生产任务</span><strong data-testid="task-total">{{totalTasks}}</strong><small>{{overview.task_counts.running || 0}} 执行中 · {{overview.task_counts.queued || 0}} 排队 · {{overview.task_counts.failed || 0}} 失败</small></RouterLink>
        <RouterLink class="signal" :to="link('models')"><span>已入账 API 费用</span><strong data-testid="overview-cost">{{overview.costs.length?overview.costs.map(row=>money(row.amount_micros,row.currency)).join(' · '):'¥0.00'}}</strong><small>{{overview.costs.reduce((sum,row)=>sum+row.unknown,0)}} 笔费用未知 · {{overview.live_authorized?'真实调用已授权':'真实调用关闭'}}</small></RouterLink>
      </div>

      <div class="overview-details">
        <WorkspacePanel title="六段生产流程">
          <div class="stage-track">
            <RouterLink v-for="(stage,index) in flow" :key="stage.page" class="stage-step" :to="link(stage.page)">
              <span class="step-icon" :class="{ready:stage.ready}"><Check v-if="stage.ready" :size="14" aria-hidden="true" /><template v-else>{{index+1}}</template></span>
              <span><strong>{{stage.label}}</strong><small>{{stage.info}}</small></span>
            </RouterLink>
          </div>
          <RouterLink class="panel-cta" :to="link('wizard')">进入创作向导 <ArrowRight :size="14" aria-hidden="true" /></RouterLink>
        </WorkspacePanel>

        <WorkspacePanel id="pending-review" title="需要你处理">
          <div v-if="reviews || rework" class="review-list">
            <RouterLink v-if="latest && (latest.reviews || latest.rework)" :to="link('production',{run:latest.id})"><ClipboardCheck :size="16" /><span><strong>最近批次</strong><small>{{latest.reviews}} 集待复核 · {{latest.rework}} 集待返工</small></span><ArrowRight :size="14" /></RouterLink>
            <RouterLink v-for="episode in latest?.attention_episodes || []" :key="episode.number" :to="link('production',{run:latest!.id,episode:String(episode.number)})"><Film :size="16" /><span><strong>第 {{episode.number}} 集</strong><small>{{episode.status==='needs_rework'?'需返工':'待人工复核'}} · {{episode.issue_count}} 项发现</small></span><ArrowRight :size="14" /></RouterLink>
            <RouterLink v-for="draft in overview.draft_reviews" :key="draft.id" :to="link('adaptation',{call:draft.id})"><SquarePen :size="16" /><span><strong>{{draft.title}}</strong><small>{{draft.simulated?'模拟改编':'模型改编'}} · 待审</small></span><ArrowRight :size="14" /></RouterLink>
            <RouterLink v-if="overview.draft_review_count>overview.draft_reviews.length" :to="link('adaptation')">查看其余待审稿</RouterLink>
          </div>
          <p v-else class="panel-empty">暂无待审草稿或待返工分集。</p>
          <RouterLink class="panel-cta" :to="link('guardian')">进入质量审核 <ArrowRight :size="14" aria-hidden="true" /></RouterLink>
        </WorkspacePanel>

        <WorkspacePanel title="最近成片与版本">
          <template #action><RouterLink :to="link('quality')"><span data-testid="output-total">{{overview.render_count}}</span> 部</RouterLink></template>
          <div v-if="firstOutput" class="recent-output">
            <button class="film-thumbnail" :aria-label="`预览成片 ${firstOutput.title}`" @click="openOutput(firstOutput)">
              <video :src="`/api/tasks/${firstOutput.id}/output#t=0.15`" preload="metadata" muted playsinline></video><span><Play :size="16" fill="currentColor" /></span>
            </button>
            <strong>{{firstOutput.title}}</strong>
            <small>{{firstOutput.duration===null?'时长待读取':`${firstOutput.duration.toFixed(1)} 秒`}}<template v-if="firstOutput.width && firstOutput.height"> · {{firstOutput.width}} × {{firstOutput.height}}</template></small>
          </div>
          <div v-else class="panel-empty recent-empty"><Image :size="23" aria-hidden="true" />当前项目还没有已验证成片。</div>
          <RouterLink class="panel-cta" :to="link('timeline')">打开剪辑工作台 <ArrowRight :size="14" aria-hidden="true" /></RouterLink>
        </WorkspacePanel>
      </div>
    </template>
    <OutputPreview v-if="preview" v-model="preview" :title="previewTitle" />
  </div>
</template>

<style scoped>
.overview { display:grid;gap:15px }
.overview-heading { display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:7px }
.overview-heading h1 { font-size:25px;letter-spacing:-.035em;margin:0 0 6px }
.overview-heading p { color:var(--ink-muted);font-size:12px;margin:0 }
.prism-action,.feature-actions a,.panel-cta { display:inline-flex;align-items:center;gap:7px;text-decoration:none }
.project-feature { position:relative;isolation:isolate;display:grid;min-height:165px;overflow:hidden;border-radius:17px;background:linear-gradient(115deg,#1d3157,#3c4c89 58%,#6164a9);color:#fff }
.project-feature::before,.project-feature::after { content:'';position:absolute;border:1px solid #ffffff20;border-radius:50%;pointer-events:none }
.project-feature::before { width:300px;height:300px;right:-90px;top:-120px }
.project-feature::after { width:200px;height:200px;right:45px;bottom:-150px }
.project-feature.has-cover { grid-template-columns:minmax(0,1fr) minmax(260px,.66fr) }
.feature-copy { padding:25px 30px;min-width:0;z-index:1 }
.feature-label { display:flex;align-items:center;gap:10px;color:#dce5ff;font-size:11px }
.feature-label span { padding:2px 8px;border:1px solid #ffffff48;border-radius:99px }
.feature-copy h2 { font-size:clamp(22px,2.15vw,32px);margin:7px 0;overflow-wrap:anywhere;line-height:1.25 }
.feature-copy p { color:#e1e7ff;font-size:12px;max-width:75ch;margin:4px 0 }
.project-description { display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;overflow:hidden }
.feature-actions { display:flex;align-items:center;gap:13px;flex-wrap:wrap;margin-top:13px }
.feature-actions .hero-action { background:#fff;border-color:#fff;color:#334a94 }
.feature-actions a { color:#e3eaff;font-size:12px }
.feature-art { margin:0;min-width:0;position:relative;min-height:165px;max-height:235px;overflow:hidden }
.feature-art::after { content:'';position:absolute;inset:0;background:linear-gradient(90deg,#454e8c55,transparent 34%);pointer-events:none }
.feature-art img,.feature-art video { width:100%;height:100%;position:absolute;inset:0;object-fit:cover;border-radius:0 }
.signals { display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px }
.signals .signal { display:grid;align-content:start;gap:6px;text-align:left;color:var(--ink);min-width:0;min-height:105px;padding:16px 19px;background:var(--surface-panel);border:1px solid var(--line);border-radius:var(--radius);box-shadow:var(--shadow);text-decoration:none;font-weight:400;overflow-wrap:anywhere }
.signal:hover { border-color:var(--accent) }
.signal span,.signal small { color:var(--ink-muted);font-size:11px }
.signal strong { font-size:27px;line-height:1.2;letter-spacing:-.03em;font-variant-numeric:tabular-nums }
.overview-details { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;align-items:start }
.stage-step,.review-list a { display:flex;align-items:center;gap:10px;min-width:0;padding:9px 0;border-bottom:1px solid var(--line);color:var(--ink);text-decoration:none }
.stage-step:hover,.review-list a:hover { color:var(--accent) }
.stage-step strong,.review-list strong { display:block;font-size:12px }
.stage-step small,.review-list small,.recent-output small { display:block;color:var(--ink-muted);font-size:11px;margin-top:2px }
.step-icon { width:28px;height:28px;display:grid;place-items:center;flex:none;border:1px solid var(--line);border-radius:50%;background:var(--surface-raised);color:var(--ink-muted);font-size:11px }
.step-icon.ready { color:var(--positive);background:color-mix(in srgb,var(--positive) 13%,var(--surface-panel));border-color:transparent }
.review-list a span { flex:1;min-width:0;overflow-wrap:anywhere }
.review-list svg { flex:none;color:var(--accent) }
.panel-cta { width:fit-content;color:var(--accent);background:var(--accent-surface);border-radius:8px;font-size:12px;font-weight:650;padding:7px 10px;margin-top:12px }
.panel-empty { font-size:12px;color:var(--ink-muted);margin:0 }
.recent-empty { display:flex;align-items:center;min-height:90px;gap:7px }
.film-thumbnail { width:100%;aspect-ratio:16/9;position:relative;display:block;padding:0 !important;overflow:hidden;margin-bottom:8px }
.film-thumbnail video { display:block;object-fit:cover;border-radius:8px;height:100% }
.film-thumbnail span { position:absolute;bottom:8px;left:8px;padding:6px;background:#172237bb;color:#fff;border-radius:7px }
#pending-review { scroll-margin-top:75px }
@media(max-width:1024px) { .signals { grid-template-columns:repeat(2,minmax(0,1fr)) } }
@media(max-width:700px) {
  .overview-heading h1 { font-size:22px }
  .overview-details { grid-template-columns:minmax(0,1fr) }
  .project-feature.has-cover { grid-template-columns:minmax(0,1fr) }
  .feature-copy { padding:20px }
  .feature-art { min-height:120px }
  .signals { gap:8px }
  .signals .signal { padding:12px }
}
</style>
