import { useRoute, useRouter, type LocationQueryRaw } from 'vue-router'
import { useWorkbench } from '../stores/workbench'
import type { Destination } from './navigation'
import { focusQuery } from './productionFocus'

export function useWorkspace() {
  const route = useRoute()
  const router = useRouter()
  const workbench = useWorkbench()
  const query = (name: string) => typeof route.query[name] === 'string' ? route.query[name] : ''
  const link = (name: Destination, params: LocationQueryRaw = {}) => {
    const project = workbench.projectId || (route.query.project === '' ? '' : undefined)
    const sameProject = params.project === undefined || params.project === project
    const focus = sameProject ? focusQuery(route.query) : {}
    const plan = name === 'guardian' || name === 'bible' ? params.version : name === 'generation' ? params.plan : undefined
    const differentPlan = Boolean(plan && plan !== focus.focusPlan)
    const differentRun = name === 'production' && Boolean(params.run && params.run !== focus.focusRun)
    return {name, query:{project, ...(!differentPlan && !differentRun ? focus : {}), ...params}}
  }
  const go = (name: Destination, params?: LocationQueryRaw) => router.push(link(name, params))
  return { route, workbench, query, link, go }
}
