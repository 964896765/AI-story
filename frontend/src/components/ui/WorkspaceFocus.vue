<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ArrowLeft, ArrowRight, Crosshair } from 'lucide-vue-next'
import type { LocationQueryRaw } from 'vue-router'
import { useWorkspace } from '../../router/workspace'
import type { Destination } from '../../router/navigation'
import { focusKeys } from '../../router/productionFocus'
import { api } from '../../services/api'
import type { ProductionSpecRef } from '../../types/productionSpec'

interface EpisodeSummary {number:number; title:string}
interface Focus {
  plan:{id:string;title:string;version:number;historical:boolean}
  run_id:string|null
  production_spec:ProductionSpecRef|null
  episodes:EpisodeSummary[]
  episode:(EpisodeSummary & {storyboard_version_id:string;episode_version_id:string})|null
  shot:string|null
  shots:{id:string;number:number;description:string;contract_sha256:string|null}[]
}

const {route,query,workbench,link,go}=useWorkspace()
const explicit=computed(()=>focusKeys.some(key=>query(key)))
const focus=ref<Focus|null>(null), error=ref(''), loading=ref(false), revision=ref(0)
const project=computed(()=>workbench.projectId)
const params=computed(()=>{
  if(explicit.value) return {plan:query('focusPlan'),episode:query('focusEpisode'),shot:query('focusShot'),run:query('focusRun')}
  if(route.name==='production' && query('run'))return {plan:'',episode:query('episode'),shot:'',run:query('run')}
  return {plan:workbench.overview?.workflow?.approved_series_id || '',episode:'',shot:'',run:''}
})
const endpoint=computed(()=>{
  if(!project.value || (!explicit.value && !params.value.plan && !params.value.run))return ''
  const search=new URLSearchParams(Object.entries(params.value).filter(([,value])=>value))
  return `/projects/${encodeURIComponent(project.value)}/workspace-context?${search}`
})

watch([endpoint,revision,()=>workbench.refreshCount],async([path],_,onCleanup)=>{
  focus.value=null;error.value='';loading.value=!!path
  if(!path)return
  const controller=new AbortController()
  onCleanup(()=>controller.abort())
  try {
    const result=await api<Focus>(path,{signal:controller.signal})
    if(!controller.signal.aborted) focus.value=result
  } catch(failure) {
    if(!controller.signal.aborted)error.value=String(failure)
  } finally {
    if(!controller.signal.aborted)loading.value=false
  }
},{immediate:true,flush:'sync'})

const targetShot=computed(()=>focus.value?.shots.find(shot=>shot.id===focus.value?.shot))
const episodeLabel=computed(()=>focus.value?.episode ? `第 ${focus.value.episode.number} 集` : '')
const contextQuery=computed<LocationQueryRaw>(()=>({
  focusPlan:focus.value?.plan.id,focusEpisode:focus.value?.episode?.number,focusShot:focus.value?.shot || undefined,
  focusRun:focus.value?.run_id || undefined,
}))
const guardian=computed(()=>link('guardian',{...contextQuery.value,version:focus.value?.plan.id,
  shot:focus.value?.shot || undefined,episode:focus.value?.episode?.number}))
const storyboard=computed(()=>link('storyboard',{...contextQuery.value,version:focus.value?.episode?.storyboard_version_id,
  shot:focus.value?.shot || undefined}))
const production=computed(()=>link('production',{...contextQuery.value,run:focus.value?.run_id || undefined,
  episode:focus.value?.episode?.number}))

function select(episode?:string, shot?:string) {
  if(!focus.value)return
  void go(route.name as Destination,{...route.query,...contextQuery.value,focusEpisode:episode || undefined,focusShot:shot || undefined})
}

function clear() {
  const query:LocationQueryRaw={...route.query}
  for(const key of focusKeys)query[key]=undefined
  void go(route.name as Destination,query)
}
</script>

<template>
  <section v-if="endpoint" class="workspace-focus" aria-label="制作定位">
    <p v-if="loading" role="status">正在核对制作定位…</p>
    <div v-else-if="error" class="focus-actions">
      <p class="error" role="alert">{{error}}</p>
      <button type="button" @click="revision++">重新核对定位</button>
      <button v-if="explicit" type="button" @click="clear">清除制作定位</button>
    </div>
    <template v-else-if="focus">
      <div class="focus-state">
        <Crosshair :size="15" aria-hidden="true" /><strong>制作定位</strong>
        <span class="focus-plan" :title="focus.plan.title">{{focus.plan.title}} · v{{focus.plan.version}}</span>
        <span v-if="focus.plan.historical" class="focus-history">历史批准版</span>
        <RouterLink v-if="focus.production_spec" :to="link('wizard',{...contextQuery,step:1,spec:focus.production_spec.id})">固定规格 v{{focus.production_spec.version}}</RouterLink>
        <span v-else class="hint">历史计划未登记固定规格</span>
      </div>
      <div class="focus-actions">
        <label class="focus-select">制作分集<select :value="focus.episode?.number || ''" @change="select(($event.target as HTMLSelectElement).value)">
          <option value="">选择分集</option>
          <option v-for="item in focus.episodes" :key="item.number" :value="item.number">第 {{item.number}} 集 · {{item.title}}</option>
        </select></label>
        <label v-if="focus.episode" class="focus-select">制作镜头<select :value="focus.shot || ''"
          @change="select(String(focus.episode.number),($event.target as HTMLSelectElement).value)">
          <option value="">全分集</option>
          <option v-for="item in focus.shots" :key="item.id" :value="item.id">镜头 {{item.number}} · {{item.description}}</option>
        </select></label>
        <RouterLink v-if="focus.episode && (route.name!=='guardian' || query('version')!==focus.plan.id || query('shot')!==(focus.shot || '') || query('episode')!==String(focus.episode.number))" :to="guardian" class="focus-link">
          {{route.name==='overview' && targetShot ? '继续当前镜头' : '打开镜头审核'}} <ArrowRight :size="14" aria-hidden="true" />
        </RouterLink>
        <RouterLink v-if="focus.episode && (route.name!=='storyboard' || query('version')!==focus.episode.storyboard_version_id || query('shot')!==(focus.shot || ''))" :to="storyboard">打开本集固定分镜</RouterLink>
        <RouterLink v-if="focus.run_id && route.name!=='production'" :to="production" class="focus-link">
          <ArrowLeft :size="14" aria-hidden="true" />返回原批次{{episodeLabel ? ` · ${episodeLabel}` : ''}}
        </RouterLink>
        <button v-if="explicit" type="button" class="focus-clear" @click="clear">清除制作定位</button>
      </div>
    </template>
  </section>
</template>

<style scoped>
.workspace-focus {display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px 16px;
  padding:9px 12px;margin:0 0 12px;border:1px solid var(--line);border-radius:var(--radius);background:var(--surface-panel);font-size:12px}
.workspace-focus p {margin:0}
.focus-state,.focus-actions,.focus-select,.focus-link {display:flex;align-items:center;gap:7px;min-width:0}
.focus-state,.focus-actions {flex-wrap:wrap}
.focus-plan {max-width:30ch;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--ink-muted)}
.focus-history {color:var(--ink-muted)}
.focus-select select {width:clamp(100px,12vw,190px);text-overflow:ellipsis}
.focus-clear {font-size:inherit}
@media(max-width:600px){.focus-actions{width:100%}.focus-select{width:100%;justify-content:space-between}.focus-select select{width:64%}}
</style>
