<script setup lang="ts">
import { darkTheme, NConfigProvider } from 'naive-ui'
import WorkbenchLayout from './layouts/WorkbenchLayout.vue'
import { componentThemes } from './styles/theme'
import { appearance } from './stores/appearance'
import { workspaceViewKey } from './router/productionFocus'
</script>

<template>
  <NConfigProvider :theme="appearance==='dark' ? darkTheme : null" :theme-overrides="componentThemes[appearance]">
    <WorkbenchLayout>
      <RouterView v-slot="{ Component, route }">
        <component :is="Component" :key="workspaceViewKey(route.path,route.query)" />
      </RouterView>
    </WorkbenchLayout>
  </NConfigProvider>
</template>
