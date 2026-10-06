/**
 * 与后端契约一一对应的类型定义。
 *
 * ★ 这份文件是「重复定义契约」的**唯一例外**，而且是刻意的：
 * 后端刻意不给分析结果建 Pydantic 模型（见 api/schemas.py 的说明），
 * 而前端如果没有类型，图表字段名写错只会在运行时静默变成 undefined ——
 * 那正是最难查的一类 bug。
 *
 * 所以：**字段名以 `backend/app/services/dashboard.py` 与
 * `analytics/aggregator.py :: to_dict()` 为准**，改后端返回结构时必须同步这里。
 */

/** 统计口径：见 README「指标口径」一节 */
export interface SkillStat {
  canonical: string
  category: string
  /** 提到该技能的 JD 条数 */
  count: number
  /** count / 样本总数 */
  coverage: number
  required_count: number
  preferred_count: number
  /** 标为硬性要求的占比 */
  required_ratio: number
  /** 硬性要求 × 1.0 + 加分项 × 0.4，主排序依据 */
  weighted_score: number
  /** 提到它的岗位（source_job_id），用于「点技能回溯原文」 */
  job_ids: string[]
  /** 去重后的原文证据句（最多 3 条） */
  examples: string[]
}

/** 学历 / 专业 / 经验 / 加分项等偏好统计 */
export interface PreferenceStat {
  label: string
  count: number
  coverage: number
  examples: string[]
}

export type GapTier = 'must' | 'should' | 'nice'

export interface GapItem extends SkillStat {
  tier: GapTier
  tier_label: string
}

export interface GapReport {
  /** 我的技能覆盖了市场多少「要求权重」 */
  coverage_score: number
  market_weight: number
  covered_weight: number
  /** R ∩ M：优势项 */
  have: SkillStat[]
  /** R − M：学习清单（已按 必学 → 建议学 → 加分项 排序） */
  must_learn: GapItem[]
  should_learn: GapItem[]
  nice_to_have: GapItem[]
  /** M − R：该方向用不上，可暂缓投入 */
  marginal: string[]
}

export interface JobBrief {
  job_id: number
  profile_id: number
  /** 采集源里的岗位 id，聚合统计用的就是这个 */
  id: string
  source: string
  title: string
  company: string
  city: string
  url: string
  status: string
}

export interface DirectionReport {
  sample_quality?: {
    company_count: number
    source_counts: Record<string, number>
    preliminary: boolean
    note: string
  }
  direction_id: number
  title: string
  /** AI 估计的匹配度，仅作排序参考 */
  match_score: number
  reason: string
  keywords: string[]
  total_jobs: number
  ok_jobs: number
  failed_jobs: number
  languages: SkillStat[]
  hard_skills: SkillStat[]
  domain_knowledge: SkillStat[]
  soft_skills: SkillStat[]
  education: PreferenceStat[]
  majors: PreferenceStat[]
  experience: PreferenceStat[]
  seniority: PreferenceStat[]
  certificates: PreferenceStat[]
  preferred_qualifications: PreferenceStat[]
  gap: GapReport
  jobs: JobBrief[]
}

/** GET /api/sessions/{id} —— 完整看板 */
export interface SessionReport {
  session_id: number
  created_at: string
  status: string
  city: string
  provider: string
  model: string
  input_skills: string[]
  canonical_skills: string[]
  total_jobs: number
  directions: DirectionReport[]
}

export interface SessionBrief {
  session_id: number
  created_at: string
  status: string
  city: string
  provider: string
  model: string
  input_skills: string[]
  job_count: number
  direction_count: number
}

/** 抽取出的单个技能（含证据句） */
export interface SkillItem {
  name: string
  category: string
  /** true=硬性要求, false=加分项 */
  required: boolean
  /** 原文依据，必须是原文子串 —— 前端高亮就靠它 */
  evidence: string
  confidence: number
}

export interface JDProfile {
  job_title: string
  seniority: string
  education: string
  major: string[]
  experience_years: string
  programming_languages: SkillItem[]
  hard_skills: SkillItem[]
  domain_knowledge: SkillItem[]
  soft_skills: SkillItem[]
  certificates: string[]
  preferred_qualifications: string[]
  responsibilities: string[]
  summary: string
}

/** GET /api/jobs/{id} */
export interface JobDetail {
  job_id: number
  source: string
  source_job_id: string
  title: string
  company: string
  city: string
  url: string
  raw_text: string
  fetched_at: string
  session_id: number | null
  direction_id: number | null
  model: string | null
  extraction_status: string | null
  cache_hit: boolean
  profile: JDProfile | null
}

export interface HealthInfo {
  status: string
  version: string
  provider: string
  model: string
  cache_enabled: boolean
  prompt_version: string
  database: string
  llm_ready: boolean
  detail: string
}

export interface LLMSettings {
  provider: 'mock' | 'openai'
  base_url: string
  model: string
  strong_model: string
  temperature: number
  timeout: number
  max_retries: number
  api_key_configured: boolean
  api_key_hint: string
}

export interface LLMSettingsInput {
  provider: 'mock' | 'openai'
  base_url: string
  model: string
  strong_model: string
  api_key?: string
  clear_api_key?: boolean
  temperature: number
  timeout: number
  max_retries: number
}

export interface DirectionOption {
  directions: string[]
  total_jobs: number
  source: string
  live_sources_enabled: boolean
  sample_source_enabled: boolean
}

/** POST /api/skills/normalize */
export interface NormalizedSkill {
  raw: string
  canonical: string
  category: string
  /** 是否命中词表。未命中会以「自身为规范名」被登记，词表随使用变准 */
  known: boolean
}

export interface TaskStarted {
  task_id: string
  kind: string
  status: string
  events_url: string
  poll_url: string
}

export interface DirectionSummary {
  title: string
  match_score: number
  reason: string
  keywords: string[]
  total_jobs: number
  ok_jobs: number
  failed_jobs: number
  coverage_score: number
}

export interface AnalysisSummary {
  session_id: number
  provider: string
  model: string
  duration_sec: number
  total_jobs: number
  input_skills: string[]
  canonical_skills: string[]
  directions: DirectionSummary[]
}

export interface ProgressEvent {
  stage: string
  message: string
  at: string
  current?: number
  total?: number
  direction?: string
}

export interface TaskState {
  task_id: string
  kind: string
  status: 'pending' | 'running' | 'done' | 'failed' | 'canceled' | string
  created_at: string
  started_at: string
  finished_at: string
  event_count: number
  last_event: ProgressEvent | null
  error: string
  result: AnalysisSummary | null
  events?: ProgressEvent[]
}
