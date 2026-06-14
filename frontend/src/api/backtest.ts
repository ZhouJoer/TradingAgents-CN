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
  selected: string[]
  target_weights: Record<string, number>
  scores: Record<string, number>
  cash_entry_streak?: number
  days_to_next_rebalance?: number | null
}

export interface BacktestDiagnostics {
  benchmark_code?: string
  benchmark_return?: number
  equal_weight_return?: number
  best_asset?: { code: string; return: number }
  worst_asset?: { code: string; return: number }
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
}

export interface MiningRun {
  run_id: string
  status: 'pending' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  trial_count?: number
  candidate_count?: number
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
}

export interface MiningCandidate {
  candidate_id: string
  strategy_id: string
  params: Record<string, any>
  score: number
  metrics: BacktestMetrics
}

export const backtestApi = {
  async getStrategies() {
    return ApiClient.get<{ items: BacktestStrategy[] }>('/api/backtest/strategies')
  },
  async getETFUniverse() {
    return ApiClient.get<{ items: ETFUniverseItem[] }>('/api/backtest/etf-universe')
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
  async listCandidates(limit = 100) {
    return ApiClient.get<{ items: MiningCandidate[] }>('/api/backtest/candidates', { params: { limit } })
  },
  async saveCandidate(data: Record<string, any>) {
    return ApiClient.post<MiningCandidate>('/api/backtest/candidates', data, { showLoading: true })
  }
}
