import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({mode}) => {
  const env = loadEnv(mode, '.', 'AI_STORY_QA_')
  const apiPort = env.AI_STORY_QA_API_PORT || '18000'
  if (!/^\d{1,5}$/.test(apiPort) || Number(apiPort) > 65535) throw new Error('Invalid loopback API port')
  return {
    plugins: [vue()],
    server: { host: '127.0.0.1', port: 15173, strictPort: true, proxy: { '/api': `http://127.0.0.1:${apiPort}` } },
  }
})
