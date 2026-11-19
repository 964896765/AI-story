<script setup lang="ts">
import { computed, ref, watchEffect } from 'vue'
import type { Result } from './analysisApi'
import { clock } from './analysisApi'
const props = defineProps<{ result: Result; playhead: number }>()
const emit = defineEmits<{ seek: [time: number] }>()
const canvas = ref<HTMLCanvasElement | null>(null)
const duration = computed(() => props.result.duration_us || 0)

watchEffect(() => {
  const surface = canvas.value
  const bins = props.result.bins
  const ctx = surface?.getContext('2d')
  if (!surface || !ctx || !duration.value || !bins?.length) return
  const {width,height} = surface
  ctx.fillStyle = '#101720'
  ctx.fillRect(0,0,width,height)
  ctx.fillStyle = '#563d35'
  for (const interval of props.result.silences || []) {
    ctx.fillRect(interval.start_us/duration.value*width, 0, (interval.end_us-interval.start_us)/duration.value*width, height)
  }
  ctx.fillStyle = '#80c8dd'
  const bar = (props.result.bin_us || 1) * width / duration.value
  bins.forEach((peak,i) => {
    const amplitude = Math.max(1,peak*height)
    ctx.fillRect(i*bar,(height-amplitude)/2,Math.max(1,bar-1),amplitude)
  })
  ctx.fillStyle = '#d8e8fc'
  ctx.fillRect(Math.min(width-1,props.playhead/duration.value*width),0,2,height)
})
</script>
<template>
  <p v-if="result.audio_status === 'no_audio'" class="hint">此素材没有音轨。</p>
  <template v-else-if="duration">
    <canvas ref="canvas" width="1100" height="110" class="waveform" role="img"
      aria-label="音频峰值波形，橙色区域为静音，使用下方滑块定位"></canvas>
    <label>波形定位 · {{ clock(playhead) }}
      <input type="range" min="0" :max="duration" step="10000" :value="Math.min(playhead,duration)"
        @input="emit('seek',Number(($event.target as HTMLInputElement).value))">
    </label>
    <details v-if="result.silences?.length">
      <summary>静音区间 · {{ result.silences.length }}</summary>
      <div class="silences">
        <button v-for="(interval,index) in result.silences" :key="index" @click="emit('seek',interval.start_us)">
          {{ clock(interval.start_us) }} – {{ clock(interval.end_us) }}
        </button>
      </div>
    </details>
    <p v-else class="hint">当前阈值下未测到静音区间。</p>
  </template>
</template>
<style scoped>
.waveform { width:100%; height:110px; border:1px solid #394655; border-radius:6px; display:block; margin:12px 0 }
.silences { max-height:200px; overflow:auto; display:grid; gap:6px; margin-top:12px }
details { margin:14px 0 0; padding:12px }
input[type=range] { width:100%; accent-color:#90cde2 }
</style>
