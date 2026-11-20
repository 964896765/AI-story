import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { api, post } from '../services/api'
import type { Asset, Project } from '../types/workbench'

export const useWorkbench = defineStore('workbench', () => {
  const projects = ref<Project[]>([])
  const projectId = ref('')
  const project = computed(() => projects.value.find(item => item.id === projectId.value))
  const assets = ref<Asset[]>([])
  const initialized = ref(false)
  const health = ref<'checking' | 'ready' | 'unavailable'>('checking')
  const error = ref('')
  const refreshCount = ref(0)
  let generation = 0
  let assetRequest = 0

  async function checkHealth() {
    try {
      await api('/health')
      health.value = 'ready'
    } catch {
      health.value = 'unavailable'
    }
  }

  async function initialize() {
    error.value = ''
    try {
      await Promise.all([checkHealth(), api<Project[]>('/projects').then(items => { projects.value = items })])
      initialized.value = true
    } catch (failure) {
      error.value = String(failure)
    }
  }

  async function loadAssets() {
    if (!projectId.value) return
    const scope = generation
    const request = ++assetRequest
    try {
      const list = await api<Asset[]>(`/projects/${projectId.value}/assets`)
      if (scope === generation && request === assetRequest) assets.value = list
    } catch (failure) {
      if (scope === generation && request === assetRequest) error.value = String(failure)
    }
  }

  function select(id: string) {
    if (projectId.value === id) return
    generation++
    assets.value = []
    error.value = ''
    projectId.value = id
    try { sessionStorage.setItem('ai-story:last-project', id) } catch { /* storage is optional */ }
    void loadAssets()
  }

  function lastProject() {
    try { return sessionStorage.getItem('ai-story:last-project') } catch { return null }
  }

  async function createProject(name: string, description: string) {
    const created = await post<Project>('/projects', { name, description })
    projects.value = [created, ...projects.value.filter(item => item.id !== created.id)]
    return created
  }

  function refresh() {
    error.value = ''
    refreshCount.value++
    if (!initialized.value) void initialize()
    else void Promise.all([checkHealth(), loadAssets()])
  }

  return { projects, projectId, project, assets, initialized, health, error, refreshCount,
    initialize, select, lastProject, loadAssets, createProject, refresh }
})
