<script setup lang="ts">
export interface VisualEvidence {
  index:number
  time_ms:number
  sha256:string
}

export interface VisualReport {
  status:'blocked'|'review'|'clear'
  rule_version:string
  checked_frames:number
  black_frames:number
  omitted_findings:number
  findings:{code:string;severity:'warning'|'error';start_ms:number;end_ms:number;evidence:VisualEvidence}[]
}

defineProps<{report?:VisualReport}>()
const emit=defineEmits<{evidence:[frame:VisualEvidence]}>()
const title={blocked:'技术检查阻断',review:'技术检查发现待复核',clear:'所测指标未检出异常'}
const checks:Record<string,string>={black_output:'全程近黑',black_segment:'持续近黑',low_motion:'画面持续低变化'}
const seconds=(value:number)=>(value/1000).toFixed(3)
</script>

<template>
  <section class="visual-check" aria-label="本机视觉技术检查">
    <div class="visual-heading">
      <h3>本机视觉技术检查</h3>
      <span v-if="report" :class="{'error':report.status==='blocked'}" data-testid="visual-check-status">{{title[report.status]}}</span>
    </div>
    <template v-if="report">
      <p class="hint">{{report.checked_frames}} 帧已解码 · {{report.black_frames}} 帧达到近黑阈值</p>
      <ul v-if="report.findings.length">
        <li v-for="item in report.findings" :key="item.code+item.start_ms">
          <span>{{checks[item.code] || item.code}} · {{seconds(item.start_ms)}}–{{seconds(item.end_ms)}} 秒</span>
          <button type="button" @click="emit('evidence',item.evidence)">定位证据</button>
        </li>
      </ul>
      <p v-if="report.omitted_findings" class="hint">另有 {{report.omitted_findings}} 段超出报告展示上限。</p>
      <p class="hint">角色、服装、道具和场景请对照参考图审核。</p>
    </template>
    <p v-else class="hint">此候选没有逐帧技术检查记录。</p>
  </section>
</template>

<style scoped>
.visual-check { border:1px solid var(--line);background:var(--surface-base);border-radius:10px;padding:12px;margin:12px 0 }
.visual-heading,.visual-check li { display:flex;align-items:center;justify-content:space-between;gap:6px;flex-wrap:wrap }
.visual-check h3,.visual-check p { margin:0 }
.visual-check h3 { font-size:13px }
.visual-heading span,.visual-check li { font-size:12px }
.visual-check ul { list-style:none;padding:0;margin:6px 0 }
.visual-check li { padding:6px 0;border-top:1px solid var(--line) }
.visual-check li button { padding:4px 8px }
.visual-check p { margin-top:5px }
</style>
