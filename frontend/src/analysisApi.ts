export const operationLabels = {
  inspect: '流清单', split: '音视频分轨', remux: '转封装', transcode: 'MP4 转码 / 代理',
  frames: '抽帧', scenes: '自动切镜', subtitles: '软字幕提取', waveform: '波形与静音', ocr: '本机画面文字识别',
  hard_subtitles: '硬字幕时序识别',
  asr: '本机语音转写',
}
export type Operation = keyof typeof operationLabels
export type Interval = { start_us: number; end_us: number }
export type Shot = Interval & { score: number | null; artifact: number | null; origin?: string }
export type Cue = Interval & { text: string; artifact?: number; sample_count?: number; confidence?: number }
export type ReviewCue = Cue & { hidden?: boolean }
export interface SubtitlePreview { task: string; stream: number; baseId: string | null; cues: ReviewCue[] }
export type OcrFrame = { artifact: number; time_us: number; text: string; lines: string[] }
export interface Artifact {
  id: number; name: string; role: string; size_bytes: number; time_us?: number; stream_index?: number
  source_streams?: number[]; media_type: string; width?: number; height?: number
}
export interface Stream {
  index: number; codec_type: string; codec_name: string; language?: string; width?: number; height?: number
  rotation?: number; display_size?: number[]; time_base?: string; source_start_us?: number
  avg_frame_rate?: string; color_transfer?: string
  disposition?: { attached_pic?: number }
}
export interface Result {
  task_id: string; operation: Operation; algorithm: string; reused_from_task_id?: string
  artifacts: Artifact[]; shots?: Shot[]; truncated?: boolean
  media?: { format: { duration?: string; format_name: string }; streams: Stream[] }
  cadence?: Record<string, { status: string; sample_frames: number }>
  subtitle_tracks?: { stream_index: number; language: string | null; status: string; cues: Cue[] }[]
  ocr?: { engine: string; language: string; frames: OcrFrame[] }
  hard_subtitle_scan?: Interval & { interval_us: number; region: 'lower' | 'full' }
  speech?: Interval & { engine: string; language: string; stream_index: number; audio_duration_us: number; status: 'recognized' | 'no_speech' }
  bins?: number[]; silences?: Interval[]; bin_us?: number; duration_us?: number; audio_status?: string
}
export interface Job {
  id: string; status: string; stage: string; progress: number; error: string | null; attempt: number
  cancel_requested: boolean; elapsed_seconds: number; parameters: { operation: Operation; stream?: number }
  output: { reused_from_task_id?: string }
}
export interface Version { version_id: string; title: string; version: number; kind?: string; id?: string }
export const statusLabels: Record<string,string> = {
  queued:'排队中', running:'处理中', succeeded:'已验证', failed:'失败', cancelled:'已取消',
  analysis_hash:'核对源文件', analysis_probe:'探测媒体流', analysis_process:'FFmpeg 处理中',
  analysis_verify:'检查输出', analysis_waveform:'统计音频采样', analysis_publish:'保存产物', analysis_ocr:'Windows 本机识别画面文字',
  analysis_asr:'Windows 本机语音转写',
  analysis_cache:'检查缓存', retry_wait:'等待重试', recovered:'中断恢复', inspecting:'检查输入',
}
export const clock = (us: number) => {
  const ms = Math.max(0, Math.round(us / 1000))
  const seconds = Math.floor(ms / 1000)
  return [Math.floor(seconds / 3600), Math.floor(seconds / 60) % 60, seconds % 60]
    .map(value => String(value).padStart(2, '0')).join(':') + '.' + String(ms % 1000).padStart(3, '0')
}
export const artifactUrl = (task: string, id: number, download = false) =>
  `/api/analysis/tasks/${task}/artifacts/${id}${download ? '?download=true' : ''}`

export async function request<T>(path: string, payload?: object): Promise<T> {
  const response = await fetch('/api' + path, payload ? {
    method: 'POST', headers: { 'Content-Type':'application/json' }, body: JSON.stringify(payload),
  } : undefined)
  const data = await response.json()
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail))
  return data
}
