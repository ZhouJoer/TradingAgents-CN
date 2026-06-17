<template>
  <el-card class="credibility-panel" shadow="never">
    <template #header>
      <div class="panel-header">
        <div class="header-title">
          <el-icon><DataAnalysis /></el-icon>
          <span>报告可信度说明</span>
        </div>
        <el-tag :type="freshnessTagType" size="small">{{ freshnessLabel }}</el-tag>
      </div>
    </template>

    <el-alert
      v-if="credibilityUnavailable"
      class="credibility-alert"
      title="可信度暂不可用"
      :description="credibilityUnavailableReason"
      type="warning"
      show-icon
      :closable="false"
    />

    <div class="credibility-grid">
      <section class="credibility-section">
        <h4>
          <el-icon><Calendar /></el-icon>
          数据新鲜度
        </h4>
        <dl>
          <div>
            <dt>分析日期</dt>
            <dd>{{ dataFreshness.analysis_date || '未知' }}</dd>
          </div>
          <div>
            <dt>生成时间</dt>
            <dd>{{ formatTime(dataFreshness.generated_at) }}</dd>
          </div>
          <div>
            <dt>行情更新</dt>
            <dd>{{ formatTime(dataFreshness.market_quote_updated_at) }}</dd>
          </div>
          <div>
            <dt>基础信息</dt>
            <dd>{{ formatTime(dataFreshness.stock_basic_updated_at) }}</dd>
          </div>
          <div>
            <dt>财务数据</dt>
            <dd>{{ formatTime(dataFreshness.financial_updated_at) }}</dd>
          </div>
        </dl>
        <ul v-if="dataFreshness.notes?.length" class="note-list">
          <li v-for="note in dataFreshness.notes" :key="note">{{ note }}</li>
        </ul>
      </section>

      <section class="credibility-section">
        <h4>
          <el-icon><Files /></el-icon>
          数据源与记录状态
        </h4>
        <dl>
          <div>
            <dt>报告来源</dt>
            <dd>{{ dataSources.report_source || '未知' }}</dd>
          </div>
          <div>
            <dt>实际来源记录</dt>
            <dd>
              <el-tag :type="dataSources.actual_source_recorded ? 'success' : 'info'" size="small">
                {{ dataSources.actual_source_recorded ? '已记录' : '未记录' }}
              </el-tag>
            </dd>
          </div>
        </dl>
        <div class="tag-group">
          <span class="tag-label">启用源</span>
          <el-tag v-for="source in enabledSources" :key="`enabled-${source}`" size="small" effect="plain">
            {{ source }}
          </el-tag>
          <span v-if="!enabledSources.length" class="empty-text">未知</span>
        </div>
        <div class="tag-group">
          <span class="tag-label">可追踪源</span>
          <el-tag v-for="source in observedSources" :key="`observed-${source}`" size="small" type="success" effect="plain">
            {{ source }}
          </el-tag>
          <span v-if="!observedSources.length" class="empty-text">未记录</span>
        </div>
      </section>

      <section class="credibility-section">
        <h4>
          <el-icon><Warning /></el-icon>
          缺失项
        </h4>
        <div v-if="missingItems.length" class="item-list">
          <div v-for="item in missingItems" :key="item.key" class="list-row">
            <el-tag :type="missingTagType(item.severity)" size="small">{{ severityText(item.severity) }}</el-tag>
            <div>
              <strong>{{ item.label }}</strong>
              <p>{{ item.reason || '报告中未记录原因' }}</p>
            </div>
          </div>
        </div>
        <el-empty v-else description="未发现核心报告模块缺失" :image-size="56" />
      </section>

      <section class="credibility-section">
        <h4>
          <el-icon><Cpu /></el-icon>
          模型与成本
        </h4>
        <dl>
          <div>
            <dt>模型</dt>
            <dd>{{ modelUsage.model_info || '未知' }}</dd>
          </div>
          <div>
            <dt>Token</dt>
            <dd>{{ formatNumber(modelUsage.tokens_used) }}</dd>
          </div>
          <div>
            <dt>输入/输出</dt>
            <dd>{{ formatNumber(modelUsage.input_tokens) }} / {{ formatNumber(modelUsage.output_tokens) }}</dd>
          </div>
          <div>
            <dt>成本</dt>
            <dd>{{ formatCost(modelUsage) }}</dd>
          </div>
          <div>
            <dt>成本来源</dt>
            <dd>{{ costSourceText(modelUsage.cost_source) }}</dd>
          </div>
        </dl>
      </section>

      <section class="credibility-section">
        <h4>
          <el-icon><Check /></el-icon>
          置信度依据
        </h4>
        <div class="confidence-line">
          <el-progress
            :percentage="normalizedConfidence"
            :color="confidenceColor"
            :stroke-width="8"
          />
          <span>{{ confidenceBasis.label || '未知' }}</span>
        </div>
        <div class="factor-columns">
          <div>
            <div class="factor-title">正向因素</div>
            <ul>
              <li v-for="item in positiveFactors" :key="item">{{ item }}</li>
              <li v-if="!positiveFactors.length" class="empty-text">未记录明确正向依据</li>
            </ul>
          </div>
          <div>
            <div class="factor-title">限制因素</div>
            <ul>
              <li v-for="item in limitingFactors" :key="item">{{ item }}</li>
              <li v-if="!limitingFactors.length" class="empty-text">未记录明确限制因素</li>
            </ul>
          </div>
        </div>
      </section>

      <section class="credibility-section">
        <h4>
          <el-icon><List /></el-icon>
          关键反证
        </h4>
        <div v-if="counterEvidence.length" class="item-list">
          <div v-for="(item, index) in counterEvidence" :key="`${item.source_module}-${index}`" class="list-row">
            <el-tag :type="item.severity === 'high' ? 'danger' : 'warning'" size="small">
              {{ item.source_module }}
            </el-tag>
            <p>{{ item.text }}</p>
          </div>
        </div>
        <el-empty v-else description="未提取到明确反证" :image-size="56" />
      </section>
    </div>
  </el-card>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { Calendar, Check, Cpu, DataAnalysis, Files, List, Warning } from '@element-plus/icons-vue'

type FreshnessLevel = 'fresh' | 'stale' | 'unknown'

type Credibility = {
  unavailable?: boolean
  error?: string
  data_freshness?: {
    analysis_date?: string
    generated_at?: string | null
    market_quote_updated_at?: string | null
    stock_basic_updated_at?: string | null
    financial_updated_at?: string | null
    freshness_level?: FreshnessLevel
    notes?: string[]
  }
  data_sources?: {
    report_source?: string
    enabled_sources?: string[]
    observed_sources?: string[]
    actual_source_recorded?: boolean
  }
  missing_items?: Array<{
    key: string
    label: string
    severity?: string
    reason?: string
  }>
  model_usage?: {
    model_info?: string
    tokens_used?: number | null
    input_tokens?: number | null
    output_tokens?: number | null
    cost?: number | null
    currency?: string
    cost_source?: string
  }
  confidence_basis?: {
    confidence_score?: number | null
    label?: string
    positive_factors?: string[]
    limiting_factors?: string[]
  }
  counter_evidence?: Array<{
    source_module: string
    text: string
    severity?: string
  }>
}

const props = defineProps<{
  credibility?: Credibility | null
}>()

const fallbackCredibility: Credibility = {
  data_freshness: { freshness_level: 'unknown', notes: ['报告未返回可信度说明。'] },
  data_sources: { enabled_sources: [], observed_sources: [], actual_source_recorded: false },
  missing_items: [],
  model_usage: { cost_source: 'unavailable', currency: 'CNY' },
  confidence_basis: { label: '未知', positive_factors: [], limiting_factors: ['报告未返回可信度说明。'] },
  counter_evidence: []
}

const credibility = computed(() => props.credibility || fallbackCredibility)
const dataFreshness = computed(() => credibility.value.data_freshness || fallbackCredibility.data_freshness!)
const dataSources = computed(() => credibility.value.data_sources || fallbackCredibility.data_sources!)
const modelUsage = computed(() => credibility.value.model_usage || fallbackCredibility.model_usage!)
const confidenceBasis = computed(() => credibility.value.confidence_basis || fallbackCredibility.confidence_basis!)
const missingItems = computed(() => credibility.value.missing_items || [])
const counterEvidence = computed(() => credibility.value.counter_evidence || [])
const enabledSources = computed(() => dataSources.value.enabled_sources || [])
const observedSources = computed(() => dataSources.value.observed_sources || [])
const positiveFactors = computed(() => confidenceBasis.value.positive_factors || [])
const limitingFactors = computed(() => confidenceBasis.value.limiting_factors || [])
const credibilityUnavailable = computed(() => Boolean(credibility.value.unavailable))
const credibilityUnavailableReason = computed(() => {
  const limiting = limitingFactors.value[0]
  return limiting || credibility.value.error || '可信度生成失败，报告主体仍可查看。'
})

const freshnessLabel = computed(() => {
  if (credibilityUnavailable.value) return '可信度暂不可用'
  const value = dataFreshness.value.freshness_level
  if (value === 'fresh') return '数据较新'
  if (value === 'stale') return '可能过期'
  return '新鲜度未知'
})

const freshnessTagType = computed(() => {
  if (credibilityUnavailable.value) return 'warning'
  const value = dataFreshness.value.freshness_level
  if (value === 'fresh') return 'success'
  if (value === 'stale') return 'warning'
  return 'info'
})

const normalizedConfidence = computed(() => {
  const score = confidenceBasis.value.confidence_score
  if (typeof score !== 'number') return 0
  return Math.max(0, Math.min(100, Math.round(score > 1 ? score : score * 100)))
})

const confidenceColor = computed(() => {
  if (normalizedConfidence.value >= 80) return '#67C23A'
  if (normalizedConfidence.value >= 60) return '#409EFF'
  if (normalizedConfidence.value >= 40) return '#E6A23C'
  return '#F56C6C'
})

const formatTime = (value?: string | null) => {
  if (!value) return '未知'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('zh-CN')
}

const formatNumber = (value?: number | null) => {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '未知'
  return Number(value).toLocaleString('zh-CN')
}

const formatCost = (usage: Credibility['model_usage']) => {
  if (!usage || usage.cost === null || usage.cost === undefined) return '未知'
  return `${usage.currency || 'CNY'} ${Number(usage.cost).toFixed(6)}`
}

const costSourceText = (source?: string) => {
  if (source === 'token_usage') return '使用统计'
  if (source === 'report') return '报告记录'
  return '未记录'
}

const missingTagType = (severity?: string) => {
  if (severity === 'high') return 'danger'
  if (severity === 'low') return 'info'
  return 'warning'
}

const severityText = (severity?: string) => {
  if (severity === 'high') return '高'
  if (severity === 'low') return '低'
  return '中'
}
</script>

<style lang="scss" scoped>
.credibility-panel {
  margin-bottom: 24px;

  .panel-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 12px;
  }

  .header-title {
    display: flex;
    align-items: center;
    gap: 8px;
    font-weight: 600;
  }
}

.credibility-alert {
  margin-bottom: 16px;
}

.credibility-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}

.credibility-section {
  min-width: 0;
  padding: 16px;
  border: 1px solid var(--el-border-color-light);
  border-radius: 8px;
  background: var(--el-fill-color-blank);

  h4 {
    display: flex;
    align-items: center;
    gap: 6px;
    margin: 0 0 12px;
    font-size: 15px;
    color: var(--el-text-color-primary);
  }

  dl {
    display: grid;
    gap: 8px;
    margin: 0;

    > div {
      display: grid;
      grid-template-columns: 86px minmax(0, 1fr);
      gap: 10px;
      align-items: start;
    }

    dt {
      color: var(--el-text-color-secondary);
      font-size: 13px;
    }

    dd {
      min-width: 0;
      margin: 0;
      color: var(--el-text-color-primary);
      overflow-wrap: anywhere;
    }
  }
}

.note-list,
.factor-columns ul {
  margin: 12px 0 0;
  padding-left: 18px;
  color: var(--el-text-color-regular);
  line-height: 1.7;
}

.tag-group {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 12px;
}

.tag-label,
.factor-title {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.empty-text {
  color: var(--el-text-color-secondary);
}

.item-list {
  display: grid;
  gap: 10px;
}

.list-row {
  display: flex;
  align-items: flex-start;
  gap: 10px;

  p {
    margin: 2px 0 0;
    color: var(--el-text-color-regular);
    line-height: 1.6;
  }
}

.confidence-line {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 12px;
  align-items: center;
}

.factor-columns {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
  margin-top: 14px;
}

@media (max-width: 900px) {
  .credibility-grid,
  .factor-columns {
    grid-template-columns: 1fr;
  }
}
</style>
