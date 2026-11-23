import type { LocationQuery, LocationQueryRaw } from 'vue-router'

export const focusKeys = ['focusPlan', 'focusEpisode', 'focusShot', 'focusRun'] as const

export function focusQuery(query: LocationQuery) {
  const values: LocationQueryRaw = {}
  for (const key of focusKeys) {
    if (typeof query[key] === 'string' && query[key]) values[key] = query[key]
  }
  return values
}

export function workspaceViewKey(path: string, query: LocationQuery) {
  const local = Object.entries(query).filter(([key]) => !focusKeys.some(focus => focus === key))
  return path + JSON.stringify(local.sort(([left],[right]) => left.localeCompare(right)))
}
