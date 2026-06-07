import { ApiClient } from './request'

export interface ReportSnapshot {
  snapshot_id: string
  report_id: string
  stock_symbol: string
  stock_name?: string
  estimated_core_tokens?: number
  viewpoint?: {
    action?: string
    confidence_score?: number
    risk_level?: string
    summary?: string
  }
  key_assumptions?: Array<{ id: string; text: string; category?: string; status?: string }>
  claims?: Record<string, Array<{ id: string; text: string; category?: string }>>
  excluded_modules?: string[]
}

export interface ReportComparison {
  comparison_available?: boolean
  comparison_id?: string
  stock_symbol: string
  viewpoint_change?: {
    from_action?: string
    to_action?: string
    confidence_delta?: number
    risk_level_change?: string
  }
  changed_assumptions?: Array<{ change_type: string; text: string }>
  risk_changes?: Array<{ change_type: string; text: string }>
  claim_changes?: Record<string, Array<{ change_type: string; text: string }>>
  summary?: string
  message?: string
}

export interface ReviewTask {
  review_id: string
  source_report_id: string
  stock_symbol: string
  stock_name?: string
  status: string
  review_mode: string
  review_window_days: number
  due_at?: string
  items?: Array<Record<string, any>>
  overall_review_result?: any
  latest_evaluation_id?: string
  latest_evaluation?: ReviewEvaluation | null
}

export interface ReviewEvaluation {
  evaluation_id: string
  review_id: string
  status: string
  model_provider?: string
  model_name?: string
  parsed_result?: any
  error?: string
  created_at?: string
}

export const reportReviewApi = {
  getSnapshot(reportId: string, regenerate = false) {
    return ApiClient.get<ReportSnapshot>(`/api/reports/${reportId}/snapshot`, { regenerate })
  },

  getLatestComparison(stockSymbol: string) {
    return ApiClient.get<ReportComparison>(`/api/reports/stock/${stockSymbol}/latest-comparison`)
  },

  createReviewTask(reportId: string, reviewWindowDays = 30, reviewMode = 'hybrid') {
    return ApiClient.post<ReviewTask>(`/api/reports/${reportId}/review-task`, {
      review_window_days: reviewWindowDays,
      review_mode: reviewMode
    })
  },

  listReviewTasks(params: { stock_symbol?: string; status?: string; limit?: number; offset?: number }) {
    return ApiClient.get<{ items: ReviewTask[]; total: number }>(`/api/reviews/tasks`, params)
  },

  getReviewTask(reviewId: string) {
    return ApiClient.get<ReviewTask>(`/api/reviews/tasks/${reviewId}`)
  },

  runReviewTask(reviewId: string) {
    return ApiClient.post<ReviewTask>(`/api/reviews/tasks/${reviewId}/run`, {})
  },

  llmEvaluate(reviewId: string) {
    return ApiClient.post<ReviewEvaluation>(`/api/reviews/tasks/${reviewId}/llm-evaluate`, {})
  }
}
