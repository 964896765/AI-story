import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { destinations, type Destination } from './navigation'

const views: Record<Destination, RouteRecordRaw['component']> = {
  overview: () => import('../pages/OverviewPage.vue'),
  assets: () => import('../pages/AssetsPage.vue'),
  analysis: () => import('../pages/AnalysisPage.vue'),
  story: () => import('../pages/StoryPage.vue'),
  adaptation: () => import('../pages/AdaptationPage.vue'),
  characters: () => import('../pages/StoryPage.vue'),
  storyboard: () => import('../pages/StoryPage.vue'),
  bible: () => import('../pages/BiblePage.vue'),
  generation: () => import('../pages/GenerationPage.vue'),
  voice: () => import('../pages/VoicePage.vue'),
  timeline: () => import('../pages/TimelinePage.vue'),
  video: () => import('../pages/VideoPage.vue'),
  production: () => import('../pages/ProductionPage.vue'),
  quality: () => import('../pages/QualityPage.vue'),
  library: () => import('../pages/LibraryPage.vue'),
  operations: () => import('../pages/OperationsPage.vue'),
  system: () => import('../SystemStudio.vue'),
  models: () => import('../pages/AdaptationPage.vue'),
}

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    ...Object.entries(destinations).map(([name, entry]) => ({
      name, path: entry.path, component: views[name as Destination]!, meta: { title: entry.label },
    })),
    { path: '/:pathMatch(.*)*', redirect: { name: 'overview' } },
  ],
  scrollBehavior(to, from, previous) {
    if (previous) return previous
    return to.path !== from.path ? { top: 0 } : undefined
  },
})
