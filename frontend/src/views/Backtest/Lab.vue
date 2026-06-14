<template>
  <div class="backtest-lab">
    <div class="page-header">
      <div>
        <h1>策略回测</h1>
        <p>挖掘结果不代表未来收益，仅用于研究和策略筛选。</p>
      </div>
      <div class="header-actions">
        <el-button :icon="Refresh" @click="loadMeta">刷新</el-button>
      </div>
    </div>

    <div class="lab-shell">
      <aside class="strategy-sidebar">
        <section class="sidebar-section">
          <div class="sidebar-title">策略选择</div>
          <el-select v-model="singleForm.strategy_id" class="sidebar-select" filterable @change="applyStrategyDefaults">
            <el-option
              v-for="item in strategies"
              :key="item.id"
              :label="item.name"
              :value="item.id"
            >
              <div class="strategy-select-option">
                <span>{{ item.name }}</span>
                <small>{{ familyLabel(item.family) }} · {{ statusLabel(item.status) }}</small>
              </div>
            </el-option>
          </el-select>
          <div v-if="selectedStrategy" class="selected-strategy-meta">
            <span>{{ familyLabel(selectedStrategy.family) }}</span>
            <span>{{ statusLabel(selectedStrategy.status) }}</span>
          </div>
        </section>

        <section v-if="selectedStrategy" class="sidebar-section">
          <div class="sidebar-title">策略解释</div>
          <h2 class="sidebar-strategy-name">{{ selectedStrategy.name }}</h2>
          <p class="sidebar-description">{{ selectedStrategy.description }}</p>
          <div class="signal-tags">
            <el-tag v-for="item in selectedStrategy.signals || []" :key="item" size="small" type="info">{{ item }}</el-tag>
          </div>
          <dl class="param-mini-list">
            <template v-for="item in paramRows(singleForm.params)" :key="item.key">
              <dt>{{ item.key }}</dt>
              <dd>{{ item.value }}</dd>
            </template>
          </dl>
        </section>

        <section class="sidebar-section">
          <div class="sidebar-title">
            <span>默认轮动池</span>
            <strong>{{ rotationUniverse.length }} 只</strong>
          </div>
          <div class="universe-groups">
            <span v-for="group in universeGroups" :key="group.key" class="universe-pill">
              {{ group.label }} {{ group.items.length }}
            </span>
          </div>
          <div class="universe-tags">
            <el-tooltip v-for="item in visibleUniverseItems" :key="item.code" :content="item.name" placement="top">
              <el-tag size="small" effect="plain">{{ item.code }}</el-tag>
            </el-tooltip>
            <el-tag v-if="hiddenUniverseCount > 0" size="small" type="info" effect="plain">+{{ hiddenUniverseCount }}</el-tag>
          </div>
          <div v-if="cashWatchUniverse.length" class="cash-watch-line">
            现金参考 {{ cashWatchUniverse.map((item) => item.code).join(', ') }}
          </div>
        </section>
      </aside>

      <main class="lab-main">
        <el-tabs v-model="activeTab" class="lab-tabs">
          <el-tab-pane label="单策略" name="single">
        <section class="control-band">
          <el-form :model="singleForm" inline label-width="86px">
            <el-form-item label="日期">
              <el-date-picker v-model="singleDates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束" />
            </el-form-item>
            <el-form-item label="Top K">
              <el-input-number v-model="singleForm.params.top_k" :min="1" :max="5" />
            </el-form-item>
            <el-form-item label="频率">
              <el-radio-group v-model="singleForm.params.rebalance_frequency">
                <el-radio-button label="weekly">周</el-radio-button>
                <el-radio-button label="biweekly">双周</el-radio-button>
                <el-radio-button label="monthly">月</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="TrendCharts" :loading="loading.single" @click="runSingle">运行回测</el-button>
            </el-form-item>
          </el-form>
        </section>

        <section v-if="singleResult" class="result-grid">
          <div class="chart-panel">
            <v-chart class="equity-chart" :option="singleChartOption" autoresize />
          </div>
          <div class="metric-panel">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item v-for="item in metricRows(singleResult.metrics)" :key="item.label" :label="item.label">
                {{ item.value }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </section>

        <section v-if="singleResult" class="table-band">
          <el-descriptions :column="4" border size="small">
            <el-descriptions-item label="基准">
              {{ singleResult.diagnostics?.benchmark_code || '-' }} {{ pct(singleResult.diagnostics?.benchmark_return) }}
            </el-descriptions-item>
            <el-descriptions-item label="等权ETF">{{ pct(singleResult.diagnostics?.equal_weight_return) }}</el-descriptions-item>
            <el-descriptions-item label="最佳ETF">
              {{ singleResult.diagnostics?.best_asset?.code || '-' }} {{ pct(singleResult.diagnostics?.best_asset?.return) }}
            </el-descriptions-item>
            <el-descriptions-item label="最差ETF">
              {{ singleResult.diagnostics?.worst_asset?.code || '-' }} {{ pct(singleResult.diagnostics?.worst_asset?.return) }}
            </el-descriptions-item>
            <el-descriptions-item label="活跃天数">{{ pct(singleResult.diagnostics?.active_days_ratio) }}</el-descriptions-item>
            <el-descriptions-item label="手续费">{{ money(singleResult.metrics.total_commission) }}</el-descriptions-item>
            <el-descriptions-item label="手续费占比">{{ pct(singleResult.metrics.commission_ratio) }}</el-descriptions-item>
            <el-descriptions-item label="数据区间">
              {{ singleResult.diagnostics?.data_start }} - {{ singleResult.diagnostics?.data_end }}
            </el-descriptions-item>
            <el-descriptions-item label="价格口径">{{ adjustLabel(singleResult.diagnostics?.price_adjust) }}</el-descriptions-item>
          </el-descriptions>
        </section>

        <section v-if="singleResult?.signals?.length" class="table-band">
          <el-table :data="singleResult.signals.slice(-30).reverse()" size="small" height="300">
            <el-table-column prop="date" label="信号日" width="110" />
            <el-table-column prop="execute_date" label="执行日" width="110" />
            <el-table-column label="触发" width="120">
              <template #default="{ row }">{{ triggerLabel(row.trigger) }}</template>
            </el-table-column>
            <el-table-column label="原因" width="130">
              <template #default="{ row }">{{ reasonLabel(row.reason) }}</template>
            </el-table-column>
            <el-table-column prop="eligible_count" label="合格数" width="80" />
            <el-table-column label="确认" width="80">
              <template #default="{ row }">{{ row.cash_entry_streak ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="距调仓" width="90">
              <template #default="{ row }">{{ row.days_to_next_rebalance ?? '-' }}</template>
            </el-table-column>
            <el-table-column label="选中" min-width="160">
              <template #default="{ row }">{{ row.selected.join(', ') || '空仓' }}</template>
            </el-table-column>
            <el-table-column label="目标权重" min-width="180">
              <template #default="{ row }">{{ formatWeights(row.target_weights) }}</template>
            </el-table-column>
            <el-table-column label="Top scores" min-width="220">
              <template #default="{ row }">{{ formatScores(row.scores) }}</template>
            </el-table-column>
          </el-table>
        </section>

        <section v-if="singleResult" class="table-band">
          <el-table :data="singleResult.trades" size="small" height="260">
            <el-table-column prop="date" label="日期" width="110" />
            <el-table-column prop="code" label="代码" width="90" />
            <el-table-column label="方向" width="80">
              <template #default="{ row }">
                <el-tag :type="row.side === 'buy' ? 'success' : 'danger'" size="small">{{ row.side === 'buy' ? '买入' : '卖出' }}</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="price" label="价格" width="90" />
            <el-table-column prop="amount" label="金额" min-width="120" />
            <el-table-column prop="commission" label="手续费" width="100" />
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="策略对比" name="compare">
        <section class="control-band">
          <el-form :model="compareForm" inline label-width="86px">
            <el-form-item label="策略">
              <el-select v-model="compareForm.strategyIds" multiple collapse-tags class="wide-control">
                <el-option v-for="item in strategies" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="日期">
              <el-date-picker v-model="compareDates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="Connection" :loading="loading.compare" @click="runCompare">对比</el-button>
            </el-form-item>
          </el-form>
        </section>

        <section v-if="compareResults.length" class="chart-panel">
          <v-chart class="equity-chart" :option="compareChartOption" autoresize />
        </section>
        <section v-if="compareResults.length" class="table-band">
          <el-table :data="compareRows" size="small">
            <el-table-column prop="label" label="策略" min-width="180" />
            <el-table-column prop="total_return" label="总收益" width="100" />
            <el-table-column prop="calmar" label="Calmar" width="100" />
            <el-table-column prop="max_drawdown" label="最大回撤" width="110" />
            <el-table-column prop="trade_count" label="交易数" width="90" />
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="入场稳定性" name="stability">
        <section class="control-band">
          <el-form :model="stabilityForm" inline label-width="104px">
            <el-form-item label="日期">
              <el-date-picker v-model="stabilityDates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束" />
            </el-form-item>
            <el-form-item label="偏移起点">
              <el-input-number v-model="stabilityForm.offset_start" :min="0" :max="120" />
            </el-form-item>
            <el-form-item label="偏移终点">
              <el-input-number v-model="stabilityForm.offset_end" :min="0" :max="120" />
            </el-form-item>
            <el-form-item label="步长">
              <el-input-number v-model="stabilityForm.offset_step" :min="1" :max="30" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="TrendCharts" :loading="loading.stability" @click="runStability">运行实验</el-button>
            </el-form-item>
          </el-form>
        </section>

        <section v-if="stabilityResult" class="result-grid">
          <div class="chart-panel">
            <v-chart class="equity-chart" :option="stabilityChartOption" autoresize />
          </div>
          <div class="metric-panel">
            <el-descriptions :column="1" border size="small">
              <el-descriptions-item v-for="item in stabilitySummaryRows" :key="item.label" :label="item.label">
                {{ item.value }}
              </el-descriptions-item>
            </el-descriptions>
          </div>
        </section>

        <section v-if="stabilityResult" class="table-band">
          <el-table :data="stabilityRows" size="small" height="360">
            <el-table-column prop="offset" label="偏移交易日" width="110" />
            <el-table-column prop="entry_allowed_date" label="允许建仓日" width="120" />
            <el-table-column prop="first_buy_date" label="首次买入日" width="120" />
            <el-table-column prop="total_return" label="总收益" width="100" />
            <el-table-column prop="excess_return" label="超额收益" width="100" />
            <el-table-column prop="max_drawdown" label="最大回撤" width="110" />
            <el-table-column prop="sharpe" label="Sharpe" width="90" />
            <el-table-column prop="calmar" label="Calmar" width="90" />
            <el-table-column prop="trade_count" label="交易数" width="90" />
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="自动挖掘" name="mine">
        <section class="control-band">
          <el-form :model="mineForm" inline label-width="86px">
            <el-form-item label="模板">
              <el-select v-model="mineForm.templates" multiple collapse-tags class="wide-control">
                <el-option v-for="item in strategies" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="日期">
              <el-date-picker v-model="mineDates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束" />
            </el-form-item>
            <el-form-item label="方式">
              <el-radio-group v-model="mineForm.search_method">
                <el-radio-button label="random">随机</el-radio-button>
                <el-radio-button label="grid">网格</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item label="次数">
              <el-input-number v-model="mineForm.max_trials" :min="1" :max="300" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="Search" :loading="loading.mine" @click="startMining">开始挖掘</el-button>
            </el-form-item>
          </el-form>
        </section>

        <section v-if="miningRun" class="mine-status">
          <el-progress :percentage="Number(miningRun.progress || 0)" :status="miningRun.status === 'failed' ? 'exception' : miningRun.status === 'completed' ? 'success' : undefined" />
          <span>{{ miningRun.status }} · {{ miningRun.message }}</span>
          <span v-if="walkForwardCount" class="muted">Walk-forward {{ walkForwardCount }} 段</span>
        </section>

        <section v-if="miningTrials.length" class="result-grid">
          <div class="chart-panel">
            <v-chart class="heatmap-chart" :option="heatmapOption" autoresize />
          </div>
          <div class="metric-panel">
            <el-table :data="miningTrials.slice(0, 8)" size="small" height="320">
              <el-table-column prop="rank" label="#" width="48" />
              <el-table-column label="策略" min-width="150">
                <template #default="{ row }">{{ strategyName(row.strategy_id) }}</template>
              </el-table-column>
              <el-table-column prop="score" label="分数" width="90" />
              <el-table-column label="训练" width="90">
                <template #default="{ row }">{{ pct(row.train_metrics?.total_return) }}</template>
              </el-table-column>
              <el-table-column label="验证" width="90">
                <template #default="{ row }">{{ pct(row.validation_metrics?.total_return) }}</template>
              </el-table-column>
              <el-table-column label="样本外" width="90">
                <template #default="{ row }">{{ pct(row.test_metrics?.total_return) }}</template>
              </el-table-column>
              <el-table-column label="超额" width="90">
                <template #default="{ row }">{{ pct(row.test_metrics?.excess_return) }}</template>
              </el-table-column>
              <el-table-column label="Calmar" width="90">
                <template #default="{ row }">{{ num(row.test_metrics?.calmar) }}</template>
              </el-table-column>
              <el-table-column label="WF正收益" width="92">
                <template #default="{ row }">{{ pct(row.walk_forward_summary?.positive_ratio) }}</template>
              </el-table-column>
              <el-table-column label="WF超额" width="82">
                <template #default="{ row }">{{ pct(row.walk_forward_summary?.beat_benchmark_ratio) }}</template>
              </el-table-column>
              <el-table-column label="通过" width="72">
                <template #default="{ row }">
                  <el-tag :type="row.accepted ? 'success' : 'info'" size="small">{{ row.accepted ? '是' : '否' }}</el-tag>
                </template>
              </el-table-column>
              <el-table-column label="操作" width="150" fixed="right">
                <template #default="{ row }">
                  <el-button link type="primary" :icon="Select" @click="applyTrial(row)">应用</el-button>
                  <el-button link type="success" :icon="DocumentAdd" :loading="savingCandidate === trialKey(row)" @click="saveTrial(row)">保存</el-button>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>
      </el-tab-pane>
        </el-tabs>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage } from 'element-plus'
import { Connection, DocumentAdd, Refresh, Search, Select, TrendCharts } from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { LineChart, HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { backtestApi, type BacktestResult, type BacktestStrategy, type EntryOffsetStabilityResult, type ETFUniverseItem, type MiningRun, type MiningTrial } from '@/api/backtest'

echartsUse([LineChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, CanvasRenderer])

const activeTab = ref('single')
const strategies = ref<BacktestStrategy[]>([])
const etfUniverse = ref<ETFUniverseItem[]>([])
const singleResult = ref<BacktestResult | null>(null)
const compareResults = ref<BacktestResult[]>([])
const stabilityResult = ref<EntryOffsetStabilityResult | null>(null)
const miningRun = ref<MiningRun | null>(null)
const miningTrials = computed<MiningTrial[]>(() => miningRun.value?.trials || [])
const walkForwardCount = computed(() => Array.isArray(miningRun.value?.split_plan?.walk_forward) ? miningRun.value.split_plan.walk_forward.length : 0)
const loading = reactive({ single: false, compare: false, stability: false, mine: false })
const pollTimer = ref<number | null>(null)
const savingCandidate = ref<string | null>(null)

const defaultStart = dayjs().subtract(4, 'year').format('YYYY-MM-DD')
const defaultEnd = dayjs().format('YYYY-MM-DD')
const singleDates = ref<[string, string]>([defaultStart, defaultEnd])
const compareDates = ref<[string, string]>([defaultStart, defaultEnd])
const stabilityDates = ref<[string, string]>([defaultStart, defaultEnd])
const mineDates = ref<[string, string]>([defaultStart, defaultEnd])

const singleForm = reactive({
  strategy_id: 'industry_momentum_enhanced',
  initial_cash: 1000000,
  commission_bps: 5,
  slippage_bps: 5,
  params: {} as Record<string, any>
})
const selectedStrategy = computed(() => strategies.value.find((item) => item.id === singleForm.strategy_id))
const rotationUniverse = computed(() => etfUniverse.value.filter((item) => item.group !== 'cash_watch'))
const cashWatchUniverse = computed(() => etfUniverse.value.filter((item) => item.group === 'cash_watch'))
const universeGroups = computed(() => {
  const order = ['broad', 'sector', 'factor', 'commodity']
  return order
    .map((key) => ({
      key,
      label: universeGroupLabel(key),
      items: rotationUniverse.value.filter((item) => item.group === key)
    }))
    .filter((item) => item.items.length > 0)
})
const visibleUniverseItems = computed(() => rotationUniverse.value.slice(0, 18))
const hiddenUniverseCount = computed(() => Math.max(0, rotationUniverse.value.length - visibleUniverseItems.value.length))

const compareForm = reactive({
  strategyIds: ['industry_momentum_enhanced', 'vol_adjusted_momentum', 'donchian_breakout_rotation']
})

const mineForm = reactive({
  templates: ['industry_momentum_enhanced', 'vol_adjusted_momentum', 'trend_following_equal_weight', 'rsrs_timing_rotation'],
  search_method: 'random',
  max_trials: 40,
  seed: 7
})

const stabilityForm = reactive({
  offset_start: 0,
  offset_end: 20,
  offset_step: 1
})

async function loadMeta() {
  const [strategyRes, universeRes] = await Promise.all([backtestApi.getStrategies(), backtestApi.getETFUniverse()])
  if (strategyRes.success) {
    strategies.value = strategyRes.data.items
    applyStrategyDefaults()
  }
  if (universeRes.success) etfUniverse.value = universeRes.data.items
}

function applyStrategyDefaults() {
  const defaults = selectedStrategy.value?.default_params || {}
  singleForm.params = {
    cash_entry_mode: 'daily_when_cash',
    cash_entry_confirmations: 2,
    min_days_to_rebalance_for_cash_entry: 2,
    ...defaults
  }
}

function basePayload(dates: [string, string]) {
  return {
    start_date: dates[0],
    end_date: dates[1],
    initial_cash: 1000000,
    commission_bps: 5,
    slippage_bps: 5,
    adjust: 'qfq'
  }
}

async function runSingle() {
  try {
    loading.single = true
    const res = await backtestApi.run({
      ...basePayload(singleDates.value),
      strategy_id: singleForm.strategy_id,
      params: singleForm.params
    })
    if (res.success) {
      singleResult.value = res.data
      singleForm.params = { ...res.data.params }
    }
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '回测失败'))
  } finally {
    loading.single = false
  }
}

async function runCompare() {
  try {
    loading.compare = true
    const res = await backtestApi.compare({
      ...basePayload(compareDates.value),
      strategies: compareForm.strategyIds.map((id) => ({ strategy_id: id, label: strategyName(id), params: {} }))
    })
    if (res.success) compareResults.value = res.data.items
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '对比失败'))
  } finally {
    loading.compare = false
  }
}

async function runStability() {
  try {
    loading.stability = true
    const res = await backtestApi.entryOffsetStability({
      ...basePayload(stabilityDates.value),
      strategy_id: singleForm.strategy_id,
      params: singleForm.params,
      offset_start: stabilityForm.offset_start,
      offset_end: stabilityForm.offset_end,
      offset_step: stabilityForm.offset_step
    })
    if (res.success) stabilityResult.value = res.data
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '稳定性实验失败'))
  } finally {
    loading.stability = false
  }
}

async function startMining() {
  try {
    loading.mine = true
    const res = await backtestApi.startMining({
      ...basePayload(mineDates.value),
      templates: mineForm.templates,
      search_method: mineForm.search_method,
      max_trials: mineForm.max_trials,
      seed: mineForm.seed
    })
    if (res.success) {
      await pollMining(res.data.run_id)
      startPolling(res.data.run_id)
    }
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '挖掘启动失败'))
  } finally {
    loading.mine = false
  }
}

function startPolling(runId: string) {
  stopPolling()
  pollTimer.value = window.setInterval(() => pollMining(runId), 2500)
}

function stopPolling() {
  if (pollTimer.value) {
    window.clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

async function pollMining(runId: string) {
  const res = await backtestApi.getMiningRun(runId)
  if (res.success) {
    miningRun.value = res.data
    if (['completed', 'failed'].includes(res.data.status)) stopPolling()
  }
}

function trialKey(row: MiningTrial) {
  return `${row.trial_index || row.rank || row.strategy_id}-${row.strategy_id}`
}

function applyTrial(row: MiningTrial) {
  singleForm.strategy_id = row.strategy_id
  singleForm.params = { ...row.params }
  activeTab.value = 'single'
  ElMessage.success('已应用到单策略回测表单')
}

async function saveTrial(row: MiningTrial) {
  try {
    const key = trialKey(row)
    savingCandidate.value = key
    const res = await backtestApi.saveCandidate({
      name: `${strategyName(row.strategy_id)} #${row.rank || row.strategy_id}`,
      strategy_id: row.strategy_id,
      params: row.params,
      run_id: miningRun.value?.run_id,
      trial_index: row.trial_index || row.rank,
      score: row.score,
      metrics: row.test_metrics,
      evaluation: {
        train_metrics: row.train_metrics,
        validation_metrics: row.validation_metrics,
        test_metrics: row.test_metrics,
        stress_2x_metrics: row.stress_2x_metrics,
        walk_forward_summary: row.walk_forward_summary || {},
        walk_forward_slices: row.walk_forward_slices || [],
        reasons: row.reasons || []
      }
    })
    if (res.success) ElMessage.success('已保存候选策略配置')
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '保存候选策略失败'))
  } finally {
    savingCandidate.value = null
  }
}

function apiErrorMessage(error: any, fallback: string) {
  return error?.response?.data?.detail || error?.response?.data?.message || error?.message || fallback
}

function strategyName(id: string) {
  return strategies.value.find((item) => item.id === id)?.name || id
}

function pct(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-'
  return `${(value * 100).toFixed(2)}%`
}

function num(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-'
  return Number(value).toFixed(3)
}

function money(value?: number) {
  if (value === undefined || value === null || Number.isNaN(value)) return '-'
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: 2 })
}

const valueLabels: Record<string, string> = {
  weekly: '每周',
  biweekly: '每两周',
  monthly: '每月',
  qfq: '前复权',
  hfq: '后复权',
  none: '不复权',
  ret_gt_0: '收益率大于 0',
  score_gt_0: '综合分大于 0',
  trend_filter: '趋势过滤',
  daily_when_cash: '空仓时每日扫描',
  cash_confirmed_scan: '空仓确认入场',
  rebalance_only: '仅调仓日扫描'
}

const fallbackParamLabels: Record<string, string> = {
  rebalance_frequency: '调仓频率',
  top_k: '持仓数量',
  momentum_windows: '动量窗口',
  momentum_weights: '动量权重',
  momentum_window: '动量窗口',
  absolute_window: '绝对动量窗口',
  trend_fast_ma: '快趋势均线',
  trend_ma: '趋势均线',
  vol_window: '波动窗口',
  vol_penalty: '波动惩罚',
  empty_threshold: '空仓规则',
  cash_entry_mode: '空仓入场',
  cash_entry_confirmations: '空仓确认次数',
  min_days_to_rebalance_for_cash_entry: '距调仓日最少交易日',
  fast_window: '快动量窗口',
  slow_window: '慢动量窗口',
  fast_vol_window: '快波动窗口',
  slow_vol_window: '慢波动窗口',
  max_weight: '单标的权重上限',
  fast_ma: '快均线',
  slow_ma: '慢均线',
  score_window: '评分窗口',
  lookback: '回看窗口',
  breakout_buffer: '突破缓冲',
  rsrs_window: 'RSRS窗口',
  z_window: '标准分窗口',
  z_threshold: '标准分阈值',
  ma: '确认均线',
  segment: '分段长度',
  regime_fast_ma: '状态快均线',
  regime_slow_ma: '状态慢均线',
  regime_momentum_window: '状态动量窗口',
  regime_up_threshold: '上涨阈值',
  regime_down_threshold: '下跌阈值',
  top_k_uptrend: '上涨持仓数',
  top_k_range: '震荡持仓数',
  top_k_downtrend: '下跌防守持仓数',
  range_window: '震荡动量窗口',
  range_ma: '震荡均线',
  range_vol_window: '震荡波动窗口',
  range_vol_penalty: '震荡波动惩罚',
  defensive_codes: '防守资产池',
  defensive_window: '防守动量窗口',
  defensive_ma: '防守均线'
}

function familyLabel(value?: string) {
  const labels: Record<string, string> = {
    momentum: '动量',
    trend: '趋势',
    breakout: '突破',
    timing: '择时',
    chan: '缠论',
    adaptive: '自适应'
  }
  return labels[value || ''] || value || '-'
}

function universeGroupLabel(value?: string) {
  const labels: Record<string, string> = {
    broad: '宽基',
    sector: '行业',
    factor: '因子',
    commodity: '商品',
    cash_watch: '现金'
  }
  return labels[value || ''] || value || '-'
}

function statusLabel(value?: string) {
  const labels: Record<string, string> = {
    candidate: '候选策略',
    baseline: '基线策略',
    experimental: '实验策略'
  }
  return labels[value || ''] || value || '-'
}

function adjustLabel(value?: string) {
  return valueLabels[value || ''] || value || '-'
}

function reasonLabel(value?: string) {
  const labels: Record<string, string> = {
    selected: '已选出标的',
    warmup: '指标预热',
    no_eligible_asset: '无合格标的',
    no_chan_fractal_setup: '无分型机会',
    no_center_breakout: '无中枢突破',
    regime_uptrend: '上涨状态',
    regime_uptrend_no_asset: '上涨状态无合格标的',
    regime_range: '震荡状态',
    regime_range_no_asset: '震荡状态无合格标的',
    regime_downtrend_defensive: '下跌状态防守',
    regime_downtrend_cash: '下跌状态空仓'
  }
  return labels[value || ''] || value || '-'
}

function triggerLabel(value?: string) {
  const labels: Record<string, string> = {
    periodic: '周期调仓',
    cash_daily_scan: '空仓扫描',
    cash_confirmed_scan: '空仓确认入场'
  }
  return labels[value || ''] || value || '-'
}

function paramLabel(key: string) {
  const schema = selectedStrategy.value?.parameter_schema?.find((item: any) => item.key === key)
  return String(schema?.label || fallbackParamLabels[key] || key)
}

function formatParamValue(value: any): string {
  if (Array.isArray(value)) return value.map((item) => valueLabels[String(item)] || String(item)).join(', ')
  return valueLabels[String(value)] || String(value)
}

function paramRows(params: Record<string, any>) {
  return Object.entries(params || {}).map(([key, value]) => ({
    key: paramLabel(key),
    value: formatParamValue(value)
  }))
}

function formatWeights(weights: Record<string, number>) {
  const entries = Object.entries(weights || {})
  if (!entries.length) return '空仓'
  return entries.map(([code, weight]) => `${code}:${pct(weight)}`).join(' | ')
}

function formatScores(scores: Record<string, number>) {
  const entries = Object.entries(scores || {}).slice(0, 5)
  if (!entries.length) return '-'
  return entries.map(([code, score]) => `${code}:${num(score)}`).join(' | ')
}

function metricRows(metrics: any) {
  return [
    { label: '总收益', value: pct(metrics.total_return) },
    { label: '年化收益', value: pct(metrics.annual_return) },
    { label: '最大回撤', value: pct(metrics.max_drawdown) },
    { label: 'Sharpe', value: num(metrics.sharpe) },
    { label: 'Calmar', value: num(metrics.calmar) },
    { label: '交易数', value: String(metrics.trade_count) },
    { label: '空仓占比', value: pct(metrics.cash_days_ratio) },
    { label: '手续费占比', value: pct(metrics.commission_ratio) }
  ]
}

function equitySeries(result: BacktestResult) {
  const base = result.equity_curve[0]?.equity || 1
  return result.equity_curve.map((item) => [item.date, Number(((item.equity / base - 1) * 100).toFixed(2))])
}

const singleChartOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  grid: { left: 48, right: 24, top: 32, bottom: 48 },
  dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18 }],
  xAxis: { type: 'category' },
  yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
  series: singleResult.value ? [{ name: strategyName(singleResult.value.strategy_id), type: 'line', showSymbol: false, data: equitySeries(singleResult.value) }] : []
}))

const compareChartOption = computed<EChartsOption>(() => ({
  tooltip: { trigger: 'axis' },
  legend: { top: 0 },
  grid: { left: 48, right: 24, top: 36, bottom: 48 },
  dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18 }],
  xAxis: { type: 'category' },
  yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
  series: compareResults.value.map((item) => ({ name: item.label || strategyName(item.strategy_id), type: 'line', showSymbol: false, data: equitySeries(item) }))
}))

const compareRows = computed(() => compareResults.value.map((item) => ({
  label: item.label || strategyName(item.strategy_id),
  total_return: pct(item.metrics.total_return),
  calmar: num(item.metrics.calmar),
  max_drawdown: pct(item.metrics.max_drawdown),
  trade_count: item.metrics.trade_count
})))

const stabilityRows = computed(() => (stabilityResult.value?.items || []).map((item) => ({
  offset: item.offset,
  entry_allowed_date: item.entry_allowed_date || '-',
  first_buy_date: item.first_buy_date || '未买入',
  total_return: pct(item.metrics.total_return),
  excess_return: pct(item.metrics.excess_return),
  max_drawdown: pct(item.metrics.max_drawdown),
  sharpe: num(item.metrics.sharpe),
  calmar: num(item.metrics.calmar),
  trade_count: item.metrics.trade_count
})))

const stabilitySummaryRows = computed(() => {
  const summary = stabilityResult.value?.summary || {}
  return [
    { label: '样本数', value: String(summary.sample_count ?? '-') },
    { label: '正收益占比', value: pct(summary.positive_ratio) },
    { label: '跑赢基准占比', value: pct(summary.beat_benchmark_ratio) },
    { label: '收益中位数', value: pct(summary.total_return_median) },
    { label: '收益均值', value: pct(summary.total_return_mean) },
    { label: '收益标准差', value: pct(summary.total_return_std) },
    { label: '最差回撤', value: pct(summary.max_drawdown_worst) },
    { label: 'Calmar 中位数', value: num(summary.calmar_median) },
    { label: '最佳偏移', value: String(summary.best_offset ?? '-') },
    { label: '最差偏移', value: String(summary.worst_offset ?? '-') }
  ]
})

const stabilityChartOption = computed<EChartsOption>(() => {
  const items = stabilityResult.value?.items || []
  return {
    tooltip: { trigger: 'axis' },
    legend: { top: 0 },
    grid: { left: 48, right: 24, top: 36, bottom: 48 },
    dataZoom: [{ type: 'inside' }, { type: 'slider', height: 18 }],
    xAxis: { type: 'category', data: items.map((item) => String(item.offset)), name: '偏移交易日' },
    yAxis: { type: 'value', axisLabel: { formatter: '{value}%' } },
    series: [
      { name: '总收益', type: 'line', showSymbol: true, data: items.map((item) => Number((item.metrics.total_return * 100).toFixed(2))) },
      { name: '超额收益', type: 'line', showSymbol: true, data: items.map((item) => Number(((item.metrics.excess_return || 0) * 100).toFixed(2))) },
      { name: '最大回撤', type: 'line', showSymbol: true, data: items.map((item) => Number((item.metrics.max_drawdown * 100).toFixed(2))) }
    ]
  }
})

const heatmapOption = computed<EChartsOption>(() => {
  const trials = miningTrials.value
  const xs = Array.from(new Set(trials.map((item) => String(item.params.momentum_window || '-'))))
  const ys = Array.from(new Set(trials.map((item) => String(item.params.trend_ma || item.params.slow_ma || '-'))))
  const data = trials.map((item) => [
    xs.indexOf(String(item.params.momentum_window || '-')),
    ys.indexOf(String(item.params.trend_ma || item.params.slow_ma || '-')),
    Number(item.score || 0)
  ])
  return {
    tooltip: { position: 'top' },
    grid: { left: 64, right: 24, top: 24, bottom: 48 },
    xAxis: { type: 'category', data: xs, name: '动量' },
    yAxis: { type: 'category', data: ys, name: '均线' },
    visualMap: { min: Math.min(0, ...data.map((item) => item[2] as number)), max: Math.max(1, ...data.map((item) => item[2] as number)), calculable: true, orient: 'horizontal', left: 'center', bottom: 0 },
    series: [{ type: 'heatmap', data }]
  }
})

onMounted(loadMeta)
onUnmounted(stopPolling)
</script>

<style scoped lang="scss">
.backtest-lab {
  padding: 16px;
}

.lab-shell {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 12px;
  align-items: start;
}

.lab-main {
  min-width: 0;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;

  h1 {
    margin: 0;
    font-size: 20px;
    font-weight: 650;
  }

  p {
    margin: 4px 0 0;
    color: var(--el-text-color-secondary);
    font-size: 13px;
  }
}

.strategy-sidebar {
  position: sticky;
  top: 12px;
  max-height: calc(100vh - 32px);
  overflow: auto;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-bg-color);
  padding: 12px;
}

.sidebar-section + .sidebar-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--el-border-color-lighter);
}

.sidebar-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 8px;
  color: var(--el-text-color-regular);
  font-size: 13px;
  font-weight: 650;

  strong {
    color: var(--el-color-primary);
    font-size: 12px;
  }
}

.sidebar-select {
  width: 100%;
}

.strategy-select-option {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-width: 0;

  span {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  small {
    flex: 0 0 auto;
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}

.selected-strategy-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 8px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.sidebar-strategy-name {
  margin: 0;
  font-size: 15px;
  font-weight: 650;
}

.sidebar-description {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.5;
}

.signal-tags,
.universe-tags,
.universe-groups {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.signal-tags {
  margin-top: 10px;
}

.param-mini-list {
  display: grid;
  grid-template-columns: minmax(84px, auto) minmax(0, 1fr);
  gap: 6px 10px;
  margin: 12px 0 0;
  font-size: 12px;

  dt {
    color: var(--el-text-color-secondary);
  }

  dd {
    min-width: 0;
    margin: 0;
    overflow-wrap: anywhere;
    color: var(--el-text-color-primary);
  }
}

.universe-pill {
  border-radius: 999px;
  background: var(--el-fill-color-light);
  padding: 2px 8px;
  color: var(--el-text-color-regular);
  font-size: 12px;
}

.universe-tags {
  margin-top: 10px;
}

.cash-watch-line {
  margin-top: 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.control-band,
.table-band,
.chart-panel,
.metric-panel {
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-bg-color);
  padding: 12px;
  margin-bottom: 12px;
}

.wide-control {
  width: 280px;
}

.result-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 12px;
}

.equity-chart {
  height: 360px;
}

.heatmap-chart {
  height: 320px;
}

.mine-status {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 12px;

  .el-progress {
    flex: 1;
  }

  .muted {
    color: var(--el-text-color-secondary);
    font-size: 12px;
    white-space: nowrap;
  }
}

@media (max-width: 1120px) {
  .lab-shell {
    grid-template-columns: 1fr;
  }

  .strategy-sidebar {
    position: static;
    max-height: none;
  }
}

@media (max-width: 960px) {
  .page-header,
  .result-grid {
    grid-template-columns: 1fr;
    display: block;
  }

  .wide-control {
    width: 100%;
  }
}
</style>
