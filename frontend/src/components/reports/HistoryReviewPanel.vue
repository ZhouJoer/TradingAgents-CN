<template>
  <el-card class="history-review-panel" shadow="never">
    <template #header>
      <div class="review-card-header">
        <button class="review-title-button" type="button" @click="toggleReviewPanel">
          <el-icon><DataAnalysis /></el-icon>
          <span>历史对比与复盘评审</span>
          <el-icon class="review-toggle-icon" :class="{ expanded: panelExpanded }"><ArrowDown /></el-icon>
        </button>
        <div class="review-header-summary">
          <el-tag size="small" :type="latestComparison?.comparison_available === false ? 'info' : 'primary'">
            {{ comparisonSummaryText }}
          </el-tag>
          <el-tag size="small" :type="getReviewStatusTagType(activeReviewTask?.status)">
            {{ reviewTaskSummaryText }}
          </el-tag>
        </div>
      </div>
    </template>

    <div v-show="panelExpanded" class="review-panel-body">
      <div class="review-panel-intro">
        <div>
          <div class="intro-title">{{ comparisonSummaryText }}</div>
          <div class="intro-meta">
            风险变化：{{ latestComparison?.viewpoint_change?.risk_level_change || '-' }}；
            置信度变化：{{ formatDelta(latestComparison?.viewpoint_change?.confidence_delta) }}
          </div>
        </div>
        <div>
          <div class="intro-title">{{ reviewTaskSummaryText }}</div>
          <div class="intro-meta">
            复盘周期：{{ activeReviewTask?.review_window_days ? `${activeReviewTask.review_window_days} 天` : '-' }}
          </div>
        </div>
      </div>

      <el-tabs v-model="activeReviewTab" @tab-change="handleReviewTabChange">
        <el-tab-pane label="历史对比" name="comparison">
          <div v-if="comparisonLoading" class="review-loading">
            <el-skeleton :rows="4" animated />
          </div>
          <el-empty v-else-if="!latestComparison || latestComparison.comparison_available === false" description="暂无可对比的上一份报告" />
          <div v-else class="comparison-panel">
            <el-alert type="info" :closable="false" show-icon>
              <template #title>{{ latestComparison.summary || '已生成最近两份报告的观点变化摘要' }}</template>
            </el-alert>
            <el-descriptions :column="3" border class="review-descriptions">
              <el-descriptions-item label="观点变化">
                {{ formatAction(latestComparison.viewpoint_change?.from_action) }} → {{ formatAction(latestComparison.viewpoint_change?.to_action) }}
              </el-descriptions-item>
              <el-descriptions-item label="风险变化">
                {{ latestComparison.viewpoint_change?.risk_level_change || '-' }}
              </el-descriptions-item>
              <el-descriptions-item label="置信度变化">
                {{ formatDelta(latestComparison.viewpoint_change?.confidence_delta) }}
              </el-descriptions-item>
            </el-descriptions>
            <div class="change-columns">
              <div>
                <h4>关键假设变化</h4>
                <el-empty v-if="!latestComparison.changed_assumptions?.length" description="暂无明显变化" :image-size="64" />
                <el-tag
                  v-for="item in latestComparison.changed_assumptions"
                  :key="`${item.change_type}-${item.text}`"
                  class="change-tag"
                  :type="item.change_type === 'added' ? 'success' : 'info'"
                >
                  {{ item.change_type === 'added' ? '新增' : '移除' }}：{{ item.text }}
                </el-tag>
              </div>
              <div>
                <h4>风险变化</h4>
                <el-empty v-if="!latestComparison.risk_changes?.length" description="暂无明显变化" :image-size="64" />
                <el-tag
                  v-for="item in latestComparison.risk_changes"
                  :key="`${item.change_type}-${item.text}`"
                  class="change-tag"
                  :type="item.change_type === 'added' ? 'warning' : 'info'"
                >
                  {{ item.change_type === 'added' ? '新增' : '移除' }}：{{ item.text }}
                </el-tag>
              </div>
            </div>
          </div>
        </el-tab-pane>

        <el-tab-pane label="复盘评审" name="review">
          <div class="review-actions review-toolbar">
            <el-button type="primary" :disabled="!!activeReviewTask" :loading="reviewCreating" @click="createReviewTask">
              创建复盘任务
            </el-button>
            <el-button :disabled="!activeReviewTask" :loading="reviewRunning" @click="runReviewTask">
              执行规则复盘
            </el-button>
            <el-button type="success" :disabled="!activeReviewTask" :loading="llmEvaluating" @click="runLlmEvaluation">
              {{ activeReviewTask?.latest_evaluation ? '重新运行 LLM评审' : '运行 LLM评审' }}
            </el-button>
          </div>

          <div v-if="!activeReviewTask" class="review-empty-state">
            <el-empty description="尚未创建当前报告的复盘任务" :image-size="72" />
          </div>
          <div v-else class="review-result">
            <div class="review-status-grid">
              <div class="review-status-card">
                <div class="status-card-header">
                  <span class="status-card-title">规则复盘</span>
                  <el-tag size="small" :type="ruleReviewTagType">{{ ruleReviewStatusText }}</el-tag>
                </div>
                <div class="status-card-main">{{ ruleReviewSummary }}</div>
                <div class="status-card-meta">
                  自动项 {{ ruleReviewStats.judged }}/{{ ruleReviewStats.total }}；人工项 {{ ruleReviewStats.manual }}
                </div>
              </div>
              <div class="review-status-card">
                <div class="status-card-header">
                  <span class="status-card-title">LLM评审</span>
                  <el-tag size="small" :type="llmReviewTagType">{{ llmReviewStatusText }}</el-tag>
                </div>
                <div class="status-card-main">{{ llmReviewSummary }}</div>
                <div class="status-card-meta">
                  {{ activeReviewTask.latest_evaluation?.model_name || '等待模型评审' }}
                </div>
              </div>
            </div>

            <el-descriptions :column="3" border class="review-descriptions">
              <el-descriptions-item label="任务状态">{{ formatReviewStatus(activeReviewTask.status) }}</el-descriptions-item>
              <el-descriptions-item label="复盘模式">{{ formatReviewMode(activeReviewTask.review_mode) }}</el-descriptions-item>
              <el-descriptions-item label="复盘周期">{{ activeReviewTask.review_window_days }} 天</el-descriptions-item>
            </el-descriptions>

            <div class="review-section">
              <h4>规则复盘：价格触发项检查</h4>
              <el-alert
                :type="ruleReviewAlertType"
                :closable="false"
                show-icon
              >
                <template #title>{{ ruleReviewSummary }}</template>
                <div>{{ ruleReviewDetail }}</div>
              </el-alert>
            </div>

            <div class="review-section llm-result">
              <h4>LLM评审：研究质量复盘</h4>
              <el-alert
                :type="llmReviewAlertType"
                :closable="false"
                show-icon
              >
                <template #title>{{ llmReviewSummary }}</template>
                <div>{{ llmReviewDetail }}</div>
              </el-alert>
            </div>

            <div v-if="activeReviewTask.latest_evaluation?.parsed_result?.dimension_reviews" class="dimension-grid">
              <div
                v-for="(item, key) in activeReviewTask.latest_evaluation.parsed_result.dimension_reviews"
                :key="key"
                class="dimension-item"
              >
                <div class="dimension-title">{{ getDimensionName(String(key)) }}</div>
                <div class="dimension-score">{{ item.score ?? '-' }} 分</div>
                <p>{{ item.reasoning || item.what_happened || '-' }}</p>
              </div>
            </div>
          </div>
        </el-tab-pane>
      </el-tabs>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { ArrowDown, DataAnalysis } from '@element-plus/icons-vue'
import { reportReviewApi, type ReportComparison, type ReviewTask } from '@/api/reportReview'

const props = defineProps<{
  reportId: string
  stockSymbol: string
}>()

const activeReviewTab = ref('comparison')
const panelExpanded = ref(false)
const latestComparison = ref<ReportComparison | null>(null)
const comparisonLoading = ref(false)
const activeReviewTask = ref<ReviewTask | null>(null)
const reviewCreating = ref(false)
const reviewRunning = ref(false)
const llmEvaluating = ref(false)

const comparisonSummaryText = computed(() => {
  if (comparisonLoading.value) return '历史对比加载中'
  if (!latestComparison.value) return '历史对比未加载'
  if (latestComparison.value.comparison_available === false) return '暂无历史对比'
  const change = latestComparison.value.viewpoint_change
  const fromAction = formatAction(change?.from_action)
  const toAction = formatAction(change?.to_action)
  return `观点变化：${fromAction} → ${toAction}`
})

const reviewTaskSummaryText = computed(() => {
  if (!activeReviewTask.value) return '尚未创建复盘任务'
  const verdict = llmReviewResult.value?.overall_verdict
  if (verdict) return `评审结论：${formatVerdict(verdict)}`
  return `复盘状态：${llmReviewStatusText.value}`
})

const reviewItems = computed(() => activeReviewTask.value?.items || [])

const ruleReviewStats = computed(() => {
  const items = reviewItems.value
  const judged = items.filter(item => item.result === 'hit' || item.result === 'miss')
  const hit = judged.filter(item => item.result === 'hit').length
  const manual = items.filter(item => item.result === 'pending_manual').length
  return {
    total: items.filter(item => item.type === 'price' || item.condition?.type === 'price').length,
    judged: judged.length,
    hit,
    miss: judged.length - hit,
    manual
  }
})

const ruleReviewStatusText = computed(() => {
  if (!activeReviewTask.value) return '未创建'
  if (reviewRunning.value) return '执行中'
  if (!ruleReviewStats.value.judged) return activeReviewTask.value.status === 'completed' ? '无自动命中项' : '待执行'
  return ruleReviewStats.value.miss > 0 ? '价格项未命中' : '价格项已命中'
})

const ruleReviewSummary = computed(() => {
  if (!activeReviewTask.value) return '尚未创建复盘任务'
  const stats = ruleReviewStats.value
  if (!stats.judged) {
    return stats.total ? '价格触发项尚未完成检查' : '未提取到可自动判断的价格触发项'
  }
  return `${stats.hit}/${stats.judged} 个价格触发项命中`
})

const ruleReviewDetail = computed(() => {
  const stats = ruleReviewStats.value
  if (!activeReviewTask.value) return '创建任务后可执行规则复盘。'
  if (!stats.judged) {
    return stats.manual
      ? `已提取 ${stats.manual} 个人工/LLM复盘项，基本面、新闻面和技术面需要通过 LLM评审判断。`
      : '规则复盘仅覆盖目标价、止损、支撑位、压力位等价格触发项。'
  }
  return '该结果只表示价格触发条件是否兑现，不等同于基本面、新闻面或技术面判断的正确性。'
})

const ruleReviewTagType = computed(() => {
  if (reviewRunning.value) return 'warning'
  if (!ruleReviewStats.value.judged) return 'info'
  return ruleReviewStats.value.miss > 0 ? 'warning' : 'success'
})

const ruleReviewAlertType = computed(() => {
  if (!ruleReviewStats.value.judged) return 'info'
  return ruleReviewStats.value.miss > 0 ? 'warning' : 'success'
})

const llmReviewResult = computed(() => activeReviewTask.value?.latest_evaluation?.parsed_result || null)

const llmReviewStatusText = computed(() => {
  if (!activeReviewTask.value) return '未创建'
  if (llmEvaluating.value) return '评审中'
  if (activeReviewTask.value.latest_evaluation?.status === 'failed') return '评审失败'
  if (llmReviewResult.value?.overall_verdict) return formatVerdict(llmReviewResult.value.overall_verdict)
  return '待评审'
})

const llmReviewSummary = computed(() => {
  if (!activeReviewTask.value) return '尚未创建复盘任务'
  if (llmEvaluating.value) return 'LLM正在评审历史判断质量'
  if (activeReviewTask.value.latest_evaluation?.status === 'failed') return 'LLM评审失败'
  if (llmReviewResult.value?.overall_verdict) return formatVerdict(llmReviewResult.value.overall_verdict)
  return '尚未运行 LLM评审'
})

const llmReviewDetail = computed(() => {
  if (!activeReviewTask.value) return '创建任务后可运行 LLM评审。'
  if (activeReviewTask.value.latest_evaluation?.status === 'failed') {
    return activeReviewTask.value.latest_evaluation.error || llmReviewResult.value?.summary || '模型调用或结果解析失败。'
  }
  if (llmReviewResult.value?.summary) return llmReviewResult.value.summary
  return 'LLM评审会基于原报告、当前行情、财务、新闻和技术证据，判断历史分析依据是否合理。'
})

const llmReviewTagType = computed(() => {
  const verdict = llmReviewResult.value?.overall_verdict
  if (llmEvaluating.value) return 'warning'
  if (activeReviewTask.value?.latest_evaluation?.status === 'failed') return 'danger'
  if (!verdict) return 'info'
  if (verdict === 'correct') return 'success'
  if (verdict === 'incorrect') return 'danger'
  if (verdict === 'partially_correct' || verdict === 'too_early') return 'warning'
  return 'info'
})

const llmReviewAlertType = computed(() => {
  const verdict = llmReviewResult.value?.overall_verdict
  if (activeReviewTask.value?.latest_evaluation?.status === 'failed') return 'error'
  if (verdict) return getVerdictAlertType(verdict)
  return 'info'
})

const toggleReviewPanel = async () => {
  panelExpanded.value = !panelExpanded.value
  if (!panelExpanded.value) return
  await handleReviewTabChange(activeReviewTab.value)
}

const handleReviewTabChange = async (name: string | number) => {
  if (name === 'comparison') {
    await loadLatestComparison()
  } else if (name === 'review') {
    await loadReviewTask()
  }
}

const loadLatestComparison = async () => {
  if (!props.stockSymbol || latestComparison.value || comparisonLoading.value) return
  comparisonLoading.value = true
  try {
    const res = await reportReviewApi.getLatestComparison(props.stockSymbol)
    if (res.success) {
      latestComparison.value = res.data
    }
  } catch (error) {
    console.warn('加载历史对比失败:', error)
  } finally {
    comparisonLoading.value = false
  }
}

const loadReviewTask = async () => {
  if (!props.reportId || !props.stockSymbol) return
  try {
    const res = await reportReviewApi.listReviewTasks({
      stock_symbol: props.stockSymbol,
      limit: 20
    })
    if (res.success) {
      activeReviewTask.value = res.data.items.find(item => item.source_report_id === props.reportId) || null
      await refreshActiveReviewTask()
    }
  } catch (error) {
    console.warn('加载复盘任务失败:', error)
  }
}

const createReviewTask = async () => {
  if (!props.reportId) return
  reviewCreating.value = true
  try {
    const res = await reportReviewApi.createReviewTask(props.reportId, 30, 'hybrid')
    if (res.success) {
      activeReviewTask.value = res.data
      await refreshActiveReviewTask()
      ElMessage.success('复盘任务已创建')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '创建复盘任务失败')
  } finally {
    reviewCreating.value = false
  }
}

const runReviewTask = async () => {
  if (!activeReviewTask.value) return
  reviewRunning.value = true
  try {
    const res = await reportReviewApi.runReviewTask(activeReviewTask.value.review_id)
    if (res.success) {
      activeReviewTask.value = res.data
      await refreshActiveReviewTask()
      ElMessage.success('规则复盘完成')
    }
  } catch (error: any) {
    ElMessage.error(error.message || '规则复盘失败')
  } finally {
    reviewRunning.value = false
  }
}

const runLlmEvaluation = async () => {
  if (!activeReviewTask.value) return
  llmEvaluating.value = true
  try {
    const res = await reportReviewApi.llmEvaluate(activeReviewTask.value.review_id)
    if (res.success) {
      ElMessage.success(res.data.status === 'completed' ? 'LLM评审完成' : 'LLM评审未完成，请查看错误信息')
      await refreshActiveReviewTask()
    }
  } catch (error: any) {
    ElMessage.error(error.message || 'LLM评审失败')
  } finally {
    llmEvaluating.value = false
  }
}

const refreshActiveReviewTask = async () => {
  if (!activeReviewTask.value?.review_id) return
  try {
    const res = await reportReviewApi.getReviewTask(activeReviewTask.value.review_id)
    if (res.success) {
      activeReviewTask.value = res.data
    }
  } catch (error) {
    console.warn('刷新复盘任务详情失败:', error)
  }
}

const formatDelta = (value?: number | null) => {
  if (value === undefined || value === null) return '-'
  const sign = value > 0 ? '+' : ''
  return `${sign}${value}`
}

const formatAction = (value?: string) => {
  if (!value) return '-'
  const match = String(value).match(/买入|持有|卖出/)
  if (match) return match[0]
  const compact = String(value).replace(/\s+/g, ' ').trim()
  return compact.length > 8 ? `${compact.slice(0, 8)}...` : compact
}

const formatVerdict = (value?: string) => {
  const map: Record<string, string> = {
    correct: '判断基本正确',
    partially_correct: '判断部分正确',
    incorrect: '判断被证伪',
    unverifiable: '证据不足，无法验证',
    too_early: '观察期过短',
    validated: '规则复盘命中',
    failed: '规则复盘未命中',
    inconclusive: '暂无明确结论'
  }
  return map[value || ''] || value || '暂无结论'
}

const formatReviewStatus = (value?: string) => {
  const map: Record<string, string> = {
    pending: '待复盘',
    running: '复盘中',
    completed: '已完成',
    failed: '失败',
    skipped: '已跳过'
  }
  return map[value || ''] || value || '未知'
}

const formatReviewMode = (value?: string) => {
  const map: Record<string, string> = {
    rule_only: '仅规则',
    llm_judge: 'LLM评审',
    hybrid: '规则 + LLM'
  }
  return map[value || ''] || value || '未知'
}

const getReviewStatusTagType = (value?: string) => {
  if (value === 'completed') return 'success'
  if (value === 'running') return 'warning'
  if (value === 'failed') return 'danger'
  return 'info'
}

const getVerdictAlertType = (value?: string) => {
  if (value === 'correct' || value === 'validated') return 'success'
  if (value === 'incorrect' || value === 'failed') return 'error'
  if (value === 'partially_correct' || value === 'too_early') return 'warning'
  return 'info'
}

const getDimensionName = (value: string) => {
  const map: Record<string, string> = {
    fundamental: '基本面',
    news: '新闻面',
    technical: '技术面',
    risk: '风险意识',
    final_recommendation: '最终建议'
  }
  return map[value] || value
}

const resetPanelData = () => {
  panelExpanded.value = false
  activeReviewTab.value = 'comparison'
  latestComparison.value = null
  activeReviewTask.value = null
}

watch(
  () => [props.reportId, props.stockSymbol],
  async () => {
    resetPanelData()
    await loadLatestComparison()
    await loadReviewTask()
  },
  { immediate: true }
)
</script>

<style lang="scss" scoped>
.history-review-panel {
  margin-bottom: 24px;

  .review-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 16px;
  }

  .review-title-button {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    min-width: 0;
    padding: 0;
    border: 0;
    background: transparent;
    color: var(--el-text-color-primary);
    font: inherit;
    font-weight: 600;
    cursor: pointer;
    flex: 0 0 auto;
  }

  .review-toggle-icon {
    color: var(--el-text-color-secondary);
    transition: transform 0.2s ease;

    &.expanded {
      transform: rotate(180deg);
    }
  }

  .review-header-summary {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 8px;
    flex-wrap: wrap;
    min-width: 0;
    overflow: hidden;

    :deep(.el-tag) {
      max-width: 220px;
    }

    :deep(.el-tag__content) {
      display: block;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
  }

  .review-panel-body {
    padding-top: 4px;
  }

  .review-panel-intro {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
    margin-bottom: 16px;

    > div {
      border: 1px solid var(--el-border-color-light);
      border-radius: 8px;
      padding: 12px 14px;
      background: var(--el-fill-color-blank);
    }
  }

  .intro-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--el-text-color-primary);
    line-height: 1.5;
  }

  .intro-meta {
    margin-top: 4px;
    color: var(--el-text-color-secondary);
    font-size: 13px;
    line-height: 1.5;
  }

  .review-loading {
    padding: 12px 0;
  }

  .review-descriptions {
    margin-top: 16px;
  }

  .change-columns {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 20px;
    margin-top: 20px;

    h4 {
      margin: 0 0 12px 0;
      font-size: 15px;
      color: var(--el-text-color-primary);
    }
  }

  .change-tag {
    display: block;
    width: fit-content;
    max-width: 100%;
    height: auto;
    white-space: normal;
    line-height: 1.5;
    margin: 0 0 8px 0;
    padding: 6px 10px;
  }

  .review-actions {
    display: flex;
    flex-wrap: wrap;
    gap: 10px;
    margin-bottom: 16px;
  }

  .review-toolbar {
    align-items: center;
  }

  .review-empty-state {
    border: 1px dashed var(--el-border-color);
    border-radius: 8px;
    background: var(--el-fill-color-lighter);
  }

  .review-result {
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .review-status-grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 12px;
  }

  .review-status-card {
    border: 1px solid var(--el-border-color-light);
    border-radius: 8px;
    padding: 14px;
    background: var(--el-fill-color-blank);
  }

  .status-card-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 10px;
    margin-bottom: 10px;
  }

  .status-card-title {
    font-size: 14px;
    font-weight: 600;
    color: var(--el-text-color-primary);
  }

  .status-card-main {
    font-size: 15px;
    font-weight: 700;
    color: var(--el-text-color-primary);
    line-height: 1.5;
  }

  .status-card-meta {
    margin-top: 6px;
    font-size: 13px;
    color: var(--el-text-color-secondary);
    line-height: 1.5;
  }

  .review-section h4,
  .llm-result h4 {
    margin: 0 0 10px 0;
    font-size: 15px;
    color: var(--el-text-color-primary);
  }

  .dimension-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
    gap: 12px;
  }

  .dimension-item {
    border: 1px solid var(--el-border-color-light);
    border-radius: 8px;
    padding: 14px;
    background: var(--el-fill-color-blank);

    .dimension-title {
      font-weight: 600;
      color: var(--el-text-color-primary);
    }

    .dimension-score {
      margin: 8px 0;
      color: var(--el-color-primary);
      font-weight: 700;
    }

    p {
      margin: 0;
      line-height: 1.6;
      color: var(--el-text-color-regular);
    }
  }

  @media (max-width: 768px) {
    .review-card-header {
      align-items: flex-start;
      flex-direction: column;
    }

    .review-header-summary {
      justify-content: flex-start;
    }

    .review-panel-intro,
    .change-columns,
    .review-status-grid {
      grid-template-columns: 1fr;
    }
  }
}
</style>
