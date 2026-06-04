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
