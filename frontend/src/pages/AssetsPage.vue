<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { NButton } from 'naive-ui'
import { FolderOpen, Upload } from 'lucide-vue-next'
import { useWorkspace } from '../router/workspace'
import { api, post } from '../services/api'
import type { Asset } from '../types/workbench'

const { workbench, query, go } = useWorkspace()
const title = ref(''), description = ref(''), authorization = ref(''), preview = ref('')
const busy = ref(false), error = ref('')
const media = /\.(mp4|mov|mkv|webm|avi|wav|mp3)$/i
const image = /\.(png|jpe?g|webp)$/i
const current = computed(() => workbench.assets.find(asset => asset.id === preview.value))
let refreshTimer: ReturnType<typeof setInterval> | undefined

async function action(operation: () => Promise<void>) {
  busy.value = true
  error.value = ''
  try { await operation() } catch (failure) { error.value = String(failure) } finally { busy.value = false }
}

function create() {
  void action(async () => {
    const project = await workbench.createProject(title.value, description.value)
    await go('assets', { project: project.id })
  })
}

async function upload(event: Event) {
  const input = event.target as HTMLInputElement
  const files = Array.from(input.files || [])
  const project = workbench.projectId
  const rights = authorization.value.trim()
  await action(async () => {
    if (!rights) throw new Error('请先填写授权来源')
    try {
      for (const file of files) {
        const form = new FormData()
        form.append('file', file)
        form.append('authorization', rights)
        await api(`/projects/${project}/assets`, { method: 'POST', body: form })
      }
    } finally { await workbench.loadAssets() }
  })
  input.value = ''
}

function probe(asset: Asset) {
  void action(async () => {
    await post(`/projects/${workbench.projectId}/tasks`, { asset_id: asset.id, idempotency_key: `probe:${asset.id}:v1` })
    workbench.refresh()
  })
}

onMounted(() => {
  refreshTimer = setInterval(() => {
    if (!busy.value && document.visibilityState !== 'hidden') void workbench.loadAssets()
  }, 15_000)
})
onUnmounted(() => clearInterval(refreshTimer))
</script>

<template>
  <p v-if="error" class="error" role="alert">{{ error }}</p>
  <details :open="!workbench.projects.length || query('create') === '1'">
    <summary>新建项目</summary>
    <form class="create" @submit.prevent="create">
      <label>项目名称<input v-model="title" required maxlength="200" placeholder="输入项目名称"></label>
      <label>项目说明<textarea v-model="description" maxlength="20000" placeholder="故事方向、授权范围或制作要求"></textarea></label>
      <NButton type="primary" attr-type="submit" :loading="busy" :disabled="!title.trim()">创建项目</NButton>
    </form>
  </details>
  <div v-if="workbench.projectId" class="workspace">
    <section>
      <h2>原始素材 <span>{{ workbench.assets.length }} 个</span></h2>
      <label>授权来源<textarea v-model="authorization" maxlength="10000" placeholder="记录自有素材声明或授权方、协议编号及使用范围"></textarea></label>
      <label class="upload">导入视频 / 音频 / 字幕 / 文本 / 图片<input type="file" multiple accept=".mp4,.mov,.mkv,.webm,.avi,.wav,.mp3,.srt,.txt,.png,.jpg,.jpeg,.webp"
        :disabled="busy || !authorization.trim()" @change="upload"></label>
      <p class="hint">媒体每文件 2 GiB，SRT/TXT 2 MiB，参考图片 20 MiB。</p>
      <p v-if="!workbench.assets.length" class="empty">尚无素材。填写授权来源后可导入文件。</p>
      <article v-for="asset in workbench.assets" :key="asset.id" class="asset">
        <div><strong>{{ asset.name }}</strong><p>{{ (asset.size_bytes / 1024 ** 2).toFixed(2) }} MB · {{ Object.keys(asset.media_info).length ? '已解析' : '待解析' }}</p><p>{{ asset.authorization }}</p></div>
        <div class="actions">
          <button :disabled="/\.(srt|txt)$/i.test(asset.name)" @click="preview = asset.id">预览</button>
          <button :disabled="busy || !media.test(asset.name)" @click="probe(asset)">读取媒体信息</button>
          <button v-if="media.test(asset.name)" :disabled="busy" @click="go('analysis', { asset: asset.id })">智能解析</button>
        </div>
      </article>
    </section>
    <section class="preview">
      <h2>素材预览</h2>
      <img v-if="current && image.test(current.name)" class="reference-preview" :src="`/api/assets/${current.id}/media`" :alt="current.name">
      <audio v-else-if="current && /\.(wav|mp3)$/i.test(current.name)" :key="current.id" controls preload="metadata" :src="`/api/assets/${current.id}/media`"></audio>
      <video v-else-if="current" :key="current.id" controls preload="metadata" :src="`/api/assets/${current.id}/media`"></video>
      <div v-else class="empty screen"><FolderOpen :size="20" /><span>选择素材开始预览</span></div>
      <p class="hint">浏览器无法播放的编码可在智能二创中转为 MP4。</p>
    </section>
  </div>
  <p v-else class="empty"><Upload :size="18" aria-hidden="true" /> 创建或选择一个项目，开始管理授权素材。</p>
</template>
