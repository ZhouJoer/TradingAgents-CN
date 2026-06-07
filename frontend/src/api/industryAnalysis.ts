import { request, type ApiResponse } from '@/api/request'

export type IndustryAnalysisDetailLevel = 'brief' | 'detailed'
export type IndustryAnalysisTaskStatus = 'pending' | 'running' | 'completed' | 'failed'

export interface IndustryAnalysisSubmitRequest {
  concept: string
  detail_level: IndustryAnalysisDetailLevel
  top_n: number
  market: 'CN'
  quick_analysis_model?: string
  deep_analysis_model?: string
}

export interface StockRecommendation {
  rank: number
  code: string
  name: string
  industry: string
  summary: string
  score: number
  recommendation_logic: string
  main_advantages: string
  main_risks: string
  suitable_style: string
  supply_chain_position: string
  score_breakdown: Record<string, number>
  // Legacy fields (backward compat)
  concept_match?: string
  industry_position?: string
  growth_prospect?: string
  fundamentals?: string
  technicals?: string
  financials?: string
  key_metrics: Record<string, any>
}

export interface CandidateTraceMapping {
  user_concept: string
  board_concepts: string[]
  board_industries: string[]
  keywords: string[]
  reasoning: string
}

export interface CandidateTraceBoardFetch {
  board_name: string
  board_type: string
  fetched_count: number
  valid_count: number
  failed: boolean
  reason: string
}

export interface CandidateTraceEnrichment {
  source: string
  attempted_count: number
  hit_count: number
  fields: string[]
  note: string
}

export interface CandidateTraceFilterItem {
  code: string
  name: string
  industry: string
  included: boolean
  reason: string
  reason_detail: string
  rule_score: number
  source_boards: string[]
  key_metrics: Record<string, any>
}

export interface CandidateTrace {
  mapping: CandidateTraceMapping
  board_fetches: CandidateTraceBoardFetch[]
  enrichment: CandidateTraceEnrichment[]
  original_count: number
  filtered_count: number
  excluded_count: number
  filter_summary: Record<string, any>
  filter_details: CandidateTraceFilterItem[]
  selected_candidates: CandidateTraceFilterItem[]
}

export interface IndustryLogicSections {
  supply_chain: string
  policy: string
  cycle: string
  demand: string
  competition: string
  risks: string
}

export interface StockSelectionSections {
  leaders: string
  growth_beta: string
  valuation_repair: string
  high_risk: string
  watchlist: string
}

export interface SupplyChainSegment {
  segment_key: string
  segment_name: string
  business: string
  benefit_logic: string
  key_indicators: string
  risks: string
  related_stocks: StockRecommendation[]
}

export interface RecommendationGroup {
  group_key: string
  group_name: string
  description: string
  suitable_style: string
  main_risks: string
  stocks: StockRecommendation[]
}

export interface IndustryAnalysisResult {
  concept: string
  detail_level: IndustryAnalysisDetailLevel
  mapped_boards: string[]
  candidate_count: number
  filtered_count: number
  recommendations: StockRecommendation[]
  // Full reports (Markdown)
  due_diligence_report: string
  stock_selection_report: string
  // Structured sections
  market_overview: string
  selection_reasoning: string
  risk_warning: string
  exclusion_reasons: string
  portfolio_advice: string
  tracking_indicators: string
  conclusion: string
  candidate_trace?: CandidateTrace | null
  industry_logic_sections?: IndustryLogicSections | null
  stock_selection_sections?: StockSelectionSections | null
  supply_chain_analysis?: SupplyChainSegment[]
  recommendation_groups?: RecommendationGroup[]
  // Meta
  analysis_time: number
  llm_calls: number
  data_date: string
}

export interface IndustryAnalysisSubmitData {
  task_id: string
  status: IndustryAnalysisTaskStatus
  concept: string
  created_at: string
}

export interface IndustryAnalysisTask {
  task_id: string
  status: IndustryAnalysisTaskStatus
  progress: number
  progress_message: string
  concept: string
  market?: 'CN' | string
  detail_level: IndustryAnalysisDetailLevel
  top_n: number
  result: IndustryAnalysisResult | null
  error: string | null
  created_at: string
  updated_at: string
  completed_at?: string | null
}

export const industryAnalysisApi = {
  submit(payload: IndustryAnalysisSubmitRequest): Promise<ApiResponse<IndustryAnalysisSubmitData>> {
    return request.post('/api/industry-analysis/submit', payload)
  },

  getResult(taskId: string): Promise<ApiResponse<IndustryAnalysisTask>> {
    return request.get(`/api/industry-analysis/result/${taskId}`)
  },

  getHistory(limit: number = 20): Promise<ApiResponse<IndustryAnalysisTask[]>> {
    return request.get('/api/industry-analysis/history', {
      params: { limit }
    })
  },

  delete(taskId: string): Promise<ApiResponse<{ task_id: string }>> {
    return request.delete(`/api/industry-analysis/${taskId}`)
  },

  download(taskId: string, format: 'markdown' | 'json' | 'pdf' = 'markdown'): Promise<Blob> {
    return request.get(`/api/industry-analysis/${taskId}/download`, {
      params: { format },
      responseType: 'blob'
    })
  }
}
