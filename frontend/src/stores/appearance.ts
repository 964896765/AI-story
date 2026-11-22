import { ref, watch } from 'vue'

function initialTheme() {
  try { return localStorage.getItem('ai-story:appearance') === 'dark' ? 'dark' : 'light' } catch { return 'light' }
}

export const appearance = ref<'light' | 'dark'>(initialTheme())

watch(appearance, value => {
  document.documentElement.dataset.theme = value
  try { localStorage.setItem('ai-story:appearance', value) } catch { /* optional preference */ }
}, { immediate: true, flush: 'sync' })

export function toggleAppearance() {
  appearance.value = appearance.value === 'light' ? 'dark' : 'light'
}
