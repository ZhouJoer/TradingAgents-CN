import { ApiClient } from './request'

export interface BacktestMetrics {
  total_return: number
  annual_return: number
  annual_volatility: number
  sharpe: number
  max_drawdown: number
  calmar: number
  win_rate: number
  trade_count: number
  avg_turnover: number
  cash_days_ratio: number
  total_commission?: number
  commission_ratio?: number
  benchmark_return?: number
  excess_return?: number
}

export interface BacktestCurvePoint {
  date: string
  equity: number
  cash: number
  cash_weight: number
}

export interface BacktestTrade {
  date: string
  code: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  amount: number
  commission: number
}

export interface BacktestSignal {
  date: string
  execute_date: string
  trigger?: string
  reason: string
  eligible_count: number
  eligible: string[]
  raw_selected?: string[]
  selected: string[]
  target_weights: Record<string, number>
  scores: Record<string, number>
  stability?: BacktestSignalStability
  cash_entry_streak?: number
  days_to_next_rebalance?: number | null
}

export interface BacktestSignalStability {
  kept?: string[]
  keep_reasons?: Record<string, string>
  raw_selected?: string[]
  final_selected?: string[]
  pre_skip_turnover?: number
  turnover?: number
  turnover_threshold?: number
  skipped_by_turnover?: boolean
}

export interface BacktestDiagnostics {
  benchmark_code?: string
  benchmark_return?: number
  equal_weight_return?: number
  best_asset?: { code: string; return: number }
  worst_asset?: { code: string; return: number }
  return_attribution?: Array<{
    code: string
    name?: string
    contribution: number
    contribution_share: number
    avg_weight: number
    active_days: number
    asset_return?: number
  }>
  return_attribution_residual?: number
  return_attribution_residual_reason?: string
  return_attribution_cost_drag?: number
  active_days_ratio?: number
  trading_days?: number
  data_start?: string
  data_end?: string
  price_adjust?: string
}

export interface BacktestResult {
  label?: string
  strategy_id: string
  params: Record<string, any>
  metrics: BacktestMetrics
  equity_curve: BacktestCurvePoint[]
  positions: Array<{ date: string; weights: Record<string, number> }>
  signals?: BacktestSignal[]
  trades: BacktestTrade[]
  diagnostics?: BacktestDiagnostics
  data_warnings?: string[]
}

export interface EntryOffsetStabilityItem {
  offset: number
  entry_allowed_date?: string
  first_buy_date?: string
  metrics: BacktestMetrics
  diagnostics?: BacktestDiagnostics
}

export interface EntryOffsetStabilityResult {
  strategy_id: string
  params: Record<string, any>
  start_date: string
  end_date: string
  offset_start: number
  offset_end: number
  offset_step: number
  items: EntryOffsetStabilityItem[]
  summary: Record<string, number>
  data_warnings?: string[]
}

export interface BacktestStrategy {
  id: string
  name: string
  family?: string
  status?: string
  description?: string
  signals?: string[]
  default_frequency: string
  default_params?: Record<string, any>
  parameter_schema?: Array<Record<string, any>>
}

export interface ETFUniverseItem {
  code: string
  name: string
  group: string
  active?: boolean
  source?: string
  tags?: string[]
  note?: string
  is_default?: boolean
}

export interface MiningRun {
  run_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  mode?: string
  policy?: Record<string, any>
  trial_count?: number
  candidate_count?: number
  split_plan?: Record<string, any>
  trials?: MiningTrial[]
  candidates?: MiningCandidate[]
}

export interface MiningTrial {
  rank: number
  trial_index?: number
  strategy_id: string
  params: Record<string, any>
  score: number
  accepted: boolean
  reasons: string[]
  train_metrics: BacktestMetrics
  validation_metrics: BacktestMetrics
  test_metrics: BacktestMetrics
  stress_2x_metrics: BacktestMetrics
  walk_forward_slices?: Array<{ label: string; train: Record<string, string>; validation: Record<string, string>; test: Record<string, string>; metrics: BacktestMetrics }>
  walk_forward_summary?: Record<string, number>
  explanation?: MiningExplanation
}

export interface MiningExplanationCheck {
  key: string
  label: string
  passed: boolean
  value: number | string
  threshold: string
  failure?: string
}

export interface MiningExplanation {
  method?: string
  decision?: 'accepted' | 'rejected'
  passed_checks?: MiningExplanationCheck[]
  failed_checks?: MiningExplanationCheck[]
  score_components?: {
    positive?: Record<string, number>
    penalty?: Record<string, number>
  }
  robustness?: Record<string, number>
}

export interface MiningCandidate {
  candidate_id: string
  name?: string
  strategy_id: string
  params: Record<string, any>
  universe?: string[]
  score: number
  metrics: BacktestMetrics
  evaluation?: Record<string, any>
  status?: string
  tags?: string[]
  note?: string
  favorite?: boolean
  source?: string
  applied_count?: number
  last_applied_at?: string | null
  created_at?: string
  updated_at?: string
}

export const backtestApi = {
  async getStrategies() {
    return ApiClient.get<{ items: BacktestStrategy[] }>('/api/backtest/strategies')
  },
  async getETFUniverse() {
    return ApiClient.get<{ items: ETFUniverseItem[] }>('/api/backtest/etf-universe')
  },
  async saveETFUniverseItem(data: Record<string, any>) {
    return ApiClient.post<ETFUniverseItem>('/api/backtest/etf-universe', data, { showLoading: true })
  },
  async updateETFUniverseItem(code: string, data: Record<string, any>) {
    return ApiClient.patch<ETFUniverseItem>(`/api/backtest/etf-universe/${code}`, data, { showLoading: true })
  },
  async refreshETFBasic(source = 'akshare') {
    return ApiClient.post<{ source: string; saved: number }>(`/api/backtest/etf-universe/refresh-basic`, null, { params: { source }, showLoading: true })
  },
  async searchETF(q = '', limit = 50) {
    return ApiClient.get<{ items: ETFUniverseItem[] }>('/api/backtest/etf-search', { params: { q, limit } })
  },
  async run(data: Record<string, any>) {
    return ApiClient.post<BacktestResult>('/api/backtest/run', data, { showLoading: true })
  },
  async compare(data: Record<string, any>) {
    return ApiClient.post<{ items: BacktestResult[]; data_warnings: string[] }>('/api/backtest/compare', data, { showLoading: true })
  },
  async entryOffsetStability(data: Record<string, any>) {
    return ApiClient.post<EntryOffsetStabilityResult>('/api/backtest/stability/entry-offset', data, { showLoading: true })
  },
  async startMining(data: Record<string, any>) {
    return ApiClient.post<{ run_id: string; status: string }>('/api/backtest/mine', data, { showLoading: true })
  },
  async getMiningRun(runId: string) {
    return ApiClient.get<MiningRun>(`/api/backtest/mine/${runId}`)
  },
  async getDiscoveredAdaptiveTopKPack() {
    return ApiClient.get<Record<string, any>>('/api/backtest/strategy-packs/discovered/adaptive-topk-gap02')
  },
  async listCandidates(params: number | Record<string, any> = 100) {
    const query = typeof params === 'number' ? { limit: params } : params
    return ApiClient.get<{ items: MiningCandidate[] }>('/api/backtest/candidates', { params: query })
  },
  async saveCandidate(data: Record<string, any>) {
    return ApiClient.post<MiningCandidate>('/api/backtest/candidates', data, { showLoading: true })
  },
  async saveDiscoveredAdaptiveTopK(data: Record<string, any> = {}) {
    return ApiClient.post<MiningCandidate>('/api/backtest/candidates/discovered/adaptive-topk-gap02', data, { showLoading: true })
  },
  async updateCandidate(candidateId: string, data: Record<string, any>) {
    return ApiClient.patch<MiningCandidate>(`/api/backtest/candidates/${candidateId}`, data, { showLoading: true })
  },
  async deleteCandidate(candidateId: string) {
    return ApiClient.delete<{ deleted: boolean }>(`/api/backtest/candidates/${candidateId}`, { showLoading: true })
  },
  async applyCandidate(candidateId: string) {
    return ApiClient.post<{ candidate: MiningCandidate; strategy_id: string; params: Record<string, any>; universe: string[] }>(
      `/api/backtest/candidates/${candidateId}/apply`,
      null,
      { showLoading: true }
    )
  },
  async createPaperTrackerFromCandidate(candidateId: string, data: Record<string, any> = {}) {
    return ApiClient.post<{ candidate: MiningCandidate; tracker: Record<string, any>; run?: Record<string, any> | null }>(
      `/api/backtest/candidates/${candidateId}/paper-tracker`,
      data,
      { showLoading: true }
    )
  }
}
