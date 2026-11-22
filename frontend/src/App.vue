<script setup lang="ts">
import { darkTheme, NConfigProvider } from 'naive-ui'
import WorkbenchLayout from './layouts/WorkbenchLayout.vue'
import { componentThemes } from './styles/theme'
import { appearance } from './stores/appearance'
</script>

<template>
  <NConfigProvider :theme="appearance==='dark' ? darkTheme : null" :theme-overrides="componentThemes[appearance]">
    <WorkbenchLayout>
      <RouterView v-slot="{ Component, route }">
        <component :is="Component" :key="route.path + JSON.stringify(route.query)" />
      </RouterView>
    </WorkbenchLayout>
  </NConfigProvider>
</template>
