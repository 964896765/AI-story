export interface Project {
  id: string
  name: string
  description: string
  budget_cents: number
  created_at: string
}

export interface Asset {
  id: string
  name: string
  size_bytes: number
  authorization: string
  sha256: string
  media_info: Record<string, unknown>
}

export interface VersionRef {
  version_id: string
  title: string
  version: number
}

export interface Task {
  id: string
  asset_id: string | null
  kind: string
  status: string
  stage: string
  progress: number
  elapsed_seconds: number
  attempt: number
  error: string | null
  error_code: string | null
  cancel_requested: boolean
  next_run_at: string
  story_version_id: string | null
  batch_id: string | null
  parameters: Record<string, unknown>
  output: { width?: number; height?: number; duration?: number; size_bytes?: number; has_audio?: boolean }
}

export interface RecentRender {
  id: string
  title: string
  finished_at: string
  duration: number | null
  width: number | null
  height: number | null
}

export interface ProjectOverview {
  asset_count: number
  cover: { id: string; name: string } | null
  task_counts: Record<string, number>
  story_counts: Record<string, number>
  workflow?: { approved_series_id: string | null; director_plan_id: string | null; adopted_candidates: number; adaptation_source_id: string | null;
    production_spec?:{id:string;version:number}|null }
  render_count: number
  delivery_count: number
  recent_renders: RecentRender[]
  draft_review_count: number
  draft_reviews: { id: string; title: string; simulated: boolean }[]
  latest_run: { id: string; status: string; passed: number; episode_count: number; reviews: number; rework: number;
    attention_episodes?: {number:number;status:string;issue_count:number}[] } | null
  latest_delivery?: {id:string;run_id:string;status:string;title:string|null} | null
  costs: { currency: string; amount_micros: string; unknown: number }[]
  live_authorized: boolean
  live_budgets: { currency: string; limit_micros: string; reserved_micros: string; halted: boolean }[]
}
