import { ApiClient } from './request'

export interface CurrencyAmount {
  CNY: number
  HKD: number
  USD: number
}

export interface PaperAccountSummary {
  cash: CurrencyAmount | number  // 支持新旧格式
  realized_pnl: CurrencyAmount | number  // 支持新旧格式
  positions_value: CurrencyAmount
  equity: CurrencyAmount | number  // 支持新旧格式
  updated_at?: string
}

export interface PaperPositionItem {
  code: string
  quantity: number
  avg_cost: number
  last_price?: number | null
  market_value?: number
  unrealized_pnl?: number | null
}

export interface PaperOrderItem {
  user_id?: string
  code: string
  side: 'buy' | 'sell'
  quantity: number
  price: number
  amount: number
  status: 'filled' | 'rejected' | string
  created_at: string
  filled_at?: string
}

export interface GetAccountResponse {
  account: PaperAccountSummary
  positions: PaperPositionItem[]
}

export interface PlaceOrderPayload {
  code: string
  side: 'buy' | 'sell'
  quantity: number
  analysis_id?: string
}

export interface StrategyTracker {
  tracker_id: string
  name: string
  strategy_id: string
  params: Record<string, any>
  universe: string[]
  candidate_id?: string
  status: 'active' | 'paused' | string
  start_date: string
  initial_cash: number
  cash: number
  positions: Record<string, { quantity: number; avg_cost: number }>
  commission_bps: number
  slippage_bps: number
  adjust: string
  version: number
  tracking_start_date?: string | null
  open_policy?: 'next_signal' | 'sync_current' | string
  first_open_trade_date?: string | null
  last_signal?: Record<string, any> | null
  last_equity?: number
  last_run_at?: string | null
  last_processed_trade_date?: string | null
  pending_replay_date?: string | null
  last_replay_status?: string | null
  recent_orders?: any[]
  recent_runs?: any[]
}

export const paperApi = {
  async getAccount() {
    return ApiClient.get<GetAccountResponse>('/api/paper/account')
  },
  async placeOrder(data: PlaceOrderPayload) {
    return ApiClient.post<{ order: PaperOrderItem }>('/api/paper/order', data, { showLoading: true })
  },
  async getPositions() {
    return ApiClient.get<{ items: PaperPositionItem[] }>('/api/paper/positions')
  },
  async getOrders(limit = 50) {
    return ApiClient.get<{ items: PaperOrderItem[] }>(`/api/paper/orders`, { limit })
  },
  async resetAccount() {
    // 后端要求 confirm=true
    return ApiClient.post<{ message: string; cash: number }>(`/api/paper/reset?confirm=true`)
  },
  async listStrategyTrackers(includePaused = true) {
    return ApiClient.get<{ items: StrategyTracker[] }>('/api/paper/strategy-trackers', { params: { include_paused: includePaused } })
  },
  async createStrategyTracker(data: Record<string, any>) {
    return ApiClient.post<StrategyTracker>('/api/paper/strategy-trackers', data, { showLoading: true })
  },
  async updateStrategyTracker(trackerId: string, data: Record<string, any>) {
    return ApiClient.patch<StrategyTracker>(`/api/paper/strategy-trackers/${trackerId}`, data, { showLoading: true })
  },
  async deleteStrategyTracker(trackerId: string) {
    return ApiClient.delete<{ deleted: boolean }>(`/api/paper/strategy-trackers/${trackerId}`, { showLoading: true })
  },
  async runStrategyTracker(trackerId: string, force = false) {
    return ApiClient.post<Record<string, any>>(`/api/paper/strategy-trackers/${trackerId}/run`, null, { params: { force }, showLoading: true })
  }
}
