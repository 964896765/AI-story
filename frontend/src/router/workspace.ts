import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { useWorkbench } from '../stores/workbench'
import type { Destination } from './navigation'

export function useWorkspace() {
  const route = useRoute()
  const router = useRouter()
  const workbench = useWorkbench()
  const query = (name: string) => typeof route.query[name] === 'string' ? route.query[name] : ''
  const link = (name: Destination, params: LocationQueryRaw = {}) => ({
    name, query: { project: workbench.projectId || (route.query.project === '' ? '' : undefined), ...params },
  })
  const go = (name: Destination, params?: LocationQueryRaw) => router.push(link(name, params))
  return { route, workbench, query, link, go }
}
