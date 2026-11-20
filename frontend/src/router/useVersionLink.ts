import { computed, ref, watch } from 'vue'
import { api } from '../services/api'
import type { VersionRef } from '../types/workbench'
import { useWorkspace } from './workspace'

export function useVersionLink(parameter: string, allowedKinds: readonly string[]) {
  const { workbench, query } = useWorkspace()
  const versionId = computed(() => query(parameter) || '')
  const version = ref<VersionRef | null>(null)
  const pending = ref(false)
  const error = ref('')

  watch([() => workbench.projectId, versionId], async ([projectId, id], _, onCleanup) => {
    version.value = null
    error.value = ''
    pending.value = Boolean(projectId && id)
    if (!projectId || !id) return
    const controller = new AbortController()
    onCleanup(() => controller.abort())
    try {
      const record = await api<VersionRef & { project_id: string; kind: string }>(`/story/versions/${encodeURIComponent(id)}`, { signal: controller.signal })
      if (controller.signal.aborted) return
      if (record.project_id !== projectId || !allowedKinds.includes(record.kind)) throw new Error('链接中的固定版本不属于当前项目或工作区。')
      version.value = record
    } catch (failure) {
      if (!controller.signal.aborted) error.value = String(failure)
    } finally {
      if (!controller.signal.aborted) pending.value = false
    }
  }, { immediate: true })

  return { version, pending, error }
}
