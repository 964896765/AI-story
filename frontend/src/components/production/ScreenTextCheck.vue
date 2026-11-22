<script setup lang="ts">
import type { ScreenTextContract } from './GuardianShot.vue'
import type { VisualEvidence } from './VisualCandidateCheck.vue'

export interface ScreenTextReport {
  status:'matched'|'review'|'unavailable'
  reason?:'language_unavailable'|'recognition_failed'
  contract:ScreenTextContract
  adapter:{engine:string;language:string;system_version:string}|null
  samples:(VisualEvidence & {lines:string[]})[]
  findings:{code:'required_not_seen'|'forbidden_seen';term:string;evidence_indices:number[]}[]
  evidence:VisualEvidence[]
}
defineProps<{report:ScreenTextReport}>()
const emit=defineEmits<{evidence:[frame:VisualEvidence]}>()
const labels={matched:'采样符合文字规则',review:'文字发现待人工核验',unavailable:'OCR 不可用，待人工核验'}
const time=(ms:number)=>(ms/1000).toFixed(3)+' 秒'
</script>

<template>
  <section class="screen-check" aria-label="本机画面文字核验">
    <div class="screen-header"><h3>本机画面文字核验</h3><span data-testid="screen-text-status">{{labels[report.status]}}</span></div>
    <p class="hint">Windows OCR · {{report.contract.language}}<template v-if="report.samples.length"> · {{report.samples.length}} 个证据帧</template></p>
    <p v-if="report.reason==='language_unavailable'" class="hint">本机没有所选语言识别器。</p>
    <p v-else-if="report.reason==='recognition_failed'" class="hint">识别未完成，可直接检查证据帧。</p>
    <p v-if="report.contract.required.length"><strong>必现</strong> · {{report.contract.required.join('、')}}</p>
    <p v-if="report.contract.forbidden.length"><strong>禁现</strong> · {{report.contract.forbidden.join('、')}}</p>
    <ul v-if="report.findings.length" class="screen-findings">
      <li v-for="item in report.findings" :key="item.code+item.term">
        {{item.code==='required_not_seen'?'采样未识别到':'采样识别到禁现文字'}}「{{item.term}}」
      </li>
    </ul>
    <details>
      <summary>识别文字与证据</summary>
      <ul>
        <li v-for="frame in report.evidence" :key="frame.index">
          <button type="button" @click="emit('evidence',frame)">定位文字证据 {{time(frame.time_ms)}}</button>
          <span>{{report.samples.find(sample=>sample.index===frame.index)?.lines.filter(Boolean).join(' / ') || (report.status==='unavailable'?'未获得识别结果':'该帧未识别到文字')}}</span>
        </li>
      </ul>
    </details>
  </section>
</template>

<style scoped>
.screen-check { border:1px solid var(--line);background:var(--surface-base);border-radius:10px;padding:12px;margin:12px 0;overflow-wrap:anywhere }
.screen-header { display:flex;justify-content:space-between;gap:6px;flex-wrap:wrap }
.screen-header h3,.screen-check p { margin:0 }
.screen-header h3 { font-size:13px }
.screen-header span,.screen-check li { font-size:12px }
.screen-check p { margin-top:5px }
.screen-check ul { padding:0;list-style:none }
.screen-check li { display:flex;gap:7px;align-items:center;flex-wrap:wrap;margin:5px 0 }
.screen-check li button { padding:4px 8px }
.screen-findings li { color:var(--negative) }
</style>
