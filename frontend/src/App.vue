<script setup lang="ts">
import { NConfigProvider } from 'naive-ui'
import WorkbenchLayout from './layouts/WorkbenchLayout.vue'
import { componentTheme, workbenchTheme } from './styles/theme'
</script>

<template>
  <NConfigProvider :theme="workbenchTheme" :theme-overrides="componentTheme">
    <WorkbenchLayout>
      <RouterView v-slot="{ Component, route }">
        <component :is="Component" :key="route.path + JSON.stringify(route.query)" />
      </RouterView>
    </WorkbenchLayout>
  </NConfigProvider>
</template>
