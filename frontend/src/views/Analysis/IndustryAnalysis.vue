<template>
  <div class="industry-analysis">
    <div class="page-header">
      <h1 class="page-title">
        <el-icon><TrendCharts /></el-icon>
        行业分析
      </h1>
      <p class="page-description">输入行业或概念，生成行业尽调与A股Top 5候选。</p>
    </div>

    <el-card class="analysis-panel" shadow="never">
      <el-form :model="form" label-width="96px" class="analysis-form">
        <el-row :gutter="20">
          <el-col :xs="24" :md="12">
            <el-form-item label="行业概念" required>
              <el-input
                v-model="form.industryQuery"
                size="large"
                clearable
                placeholder="如：AI相关、高股息、传统行业"
                @keyup.enter="submitAnalysis"
              >
                <template #prefix>
                  <el-icon><Search /></el-icon>
                </template>
              </el-input>
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="4">
            <el-form-item label="Top N">
              <el-input-number v-model="form.topN" :min="1" :max="10" size="large" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="4">
            <el-form-item label="联网检索">
              <el-switch v-model="form.enableWebSearch" size="large" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :md="4">
            <el-button
              type="primary"
              size="large"
              class="submit-button"
              :loading="submitting || analysisStatus === 'processing'"
              :disabled="!form.industryQuery.trim()"
              @click="submitAnalysis"
            >
              <el-icon><Search /></el-icon>
              开始分析
            </el-button>
          </el-col>
        </el-row>
        <el-row :gutter="20">
          <el-col :span="24">
            <ModelConfig
              v-model:quick-analysis-model="modelSettings.quickAnalysisModel"
              v-model:deep-analysis-model="modelSettings.deepAnalysisModel"
              :available-models="availableModels"
              analysis-depth="3"
            />
          </el-col>
        </el-row>
      </el-form>
    </el-card>

    <el-card v-if="currentTaskId" class="status-panel" shadow="never">
      <div class="status-row">
        <div>
          <div class="status-title">{{ statusText }}</div>
          <div class="status-subtitle">{{ statusMessage }}</div>
        </div>
        <el-tag :type="statusTagType">{{ currentTaskId }}</el-tag>
      </div>
      <el-progress :percentage="progress" :status="progressStatus" />
    </el-card>

    <template v-if="result">
      <el-card class="summary-panel" shadow="never">
        <template #header>
          <div class="card-header">
            <span>核心结论</span>
            <el-tag type="info" effect="plain">{{ result.web_search_status }}</el-tag>
            <el-tag v-if="result.model_info" type="success" effect="plain">
              {{ result.model_info }}
            </el-tag>
          </div>
        </template>
        <div class="summary-text">{{ result.summary }}</div>
        <div class="keyword-row">
          <el-tag v-for="keyword in result.keywords" :key="keyword" effect="plain">
            {{ keyword }}
          </el-tag>
        </div>
      </el-card>

      <el-card class="picks-panel" shadow="never">
        <template #header>
          <div class="card-header">
            <span>A股Top {{ result.picks.length }}</span>
            <span class="muted">候选池 {{ result.candidates_count }} 只</span>
          </div>
        </template>
        <el-table :data="result.picks" stripe style="width: 100%">
          <el-table-column type="index" label="排名" width="72" />
          <el-table-column prop="code" label="代码" width="100">
            <template #default="{ row }">
              <el-link type="primary" @click="goStock(row.code)">{{ row.code }}</el-link>
            </template>
          </el-table-column>
          <el-table-column prop="name" label="名称" width="120" />
          <el-table-column prop="industry" label="行业" min-width="120" />
          <el-table-column prop="total_score" label="总分" width="96" align="right">
            <template #default="{ row }">
              <strong>{{ row.total_score.toFixed(2) }}</strong>
            </template>
          </el-table-column>
          <el-table-column label="关键理由" min-width="260">
            <template #default="{ row }">{{ row.reason }}</template>
          </el-table-column>
          <el-table-column label="风险" min-width="220">
            <template #default="{ row }">{{ row.risk }}</template>
          </el-table-column>
        </el-table>
      </el-card>

      <el-tabs class="report-tabs" type="border-card">
        <el-tab-pane label="行业尽调">
          <div class="markdown-body" v-html="renderMarkdown(result.due_diligence_report)" />
        </el-tab-pane>
        <el-tab-pane label="选股报告">
          <div class="markdown-body" v-html="renderMarkdown(result.stock_selection_report)" />
        </el-tab-pane>
        <el-tab-pane label="资料来源">
          <el-table :data="result.sources" stripe style="width: 100%">
            <el-table-column prop="title" label="标题" min-width="260" />
            <el-table-column prop="source" label="来源" width="140" />
            <el-table-column prop="domain" label="域名" width="150" />
            <el-table-column label="链接" width="90">
              <template #default="{ row }">
                <el-link type="primary" :href="row.url" target="_blank">
                  <el-icon><Link /></el-icon>
                </el-link>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </template>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Link, Search, TrendCharts } from '@element-plus/icons-vue'
import { marked } from 'marked'
import { analysisApi, type IndustryAnalysisResult } from '@/api/analysis'
import { configApi } from '@/api/config'
import ModelConfig from '@/components/ModelConfig.vue'

const router = useRouter()

const form = reactive({
  industryQuery: '',
  topN: 5,
  enableWebSearch: true
})

const modelSettings = ref({
  quickAnalysisModel: 'qwen-turbo',
  deepAnalysisModel: 'qwen-max'
})

const availableModels = ref<any[]>([])

const submitting = ref(false)
const currentTaskId = ref('')
const analysisStatus = ref<'idle' | 'pending' | 'processing' | 'completed' | 'failed'>('idle')
const progress = ref(0)
const statusMessage = ref('')
const result = ref<IndustryAnalysisResult | null>(null)
let pollTimer: number | undefined

const statusText = computed(() => {
  if (analysisStatus.value === 'completed') return '分析完成'
  if (analysisStatus.value === 'failed') return '分析失败'
  if (analysisStatus.value === 'processing') return '分析进行中'
  return '等待开始'
})

const statusTagType = computed(() => {
  if (analysisStatus.value === 'completed') return 'success'
  if (analysisStatus.value === 'failed') return 'danger'
  return 'warning'
})

const progressStatus = computed(() => {
  if (analysisStatus.value === 'completed') return 'success'
  if (analysisStatus.value === 'failed') return 'exception'
  return undefined
})

const submitAnalysis = async () => {
  const query = form.industryQuery.trim()
  if (!query) {
    ElMessage.warning('请输入行业或概念')
    return
  }

  submitting.value = true
  result.value = null
  try {
    const response = await analysisApi.startIndustryAnalysis({
      industry_query: query,
      parameters: {
        market: 'CN',
        top_n: form.topN,
        enable_web_search: form.enableWebSearch,
        quick_analysis_model: modelSettings.value.quickAnalysisModel,
        deep_analysis_model: modelSettings.value.deepAnalysisModel
      }
    })
    currentTaskId.value = response.data.task_id
    analysisStatus.value = 'pending'
    progress.value = 0
    statusMessage.value = response.data.message || '任务已创建'
    startPolling()
    ElMessage.success('行业分析任务已启动')
  } finally {
    submitting.value = false
  }
}

const startPolling = () => {
  stopPolling()
  pollStatus()
  pollTimer = window.setInterval(pollStatus, 3000)
}

const stopPolling = () => {
  if (pollTimer) {
    window.clearInterval(pollTimer)
    pollTimer = undefined
  }
}

const pollStatus = async () => {
  if (!currentTaskId.value) return
  const response = await analysisApi.getIndustryTaskStatus(currentTaskId.value)
  const data = response.data
  analysisStatus.value = data.status
  progress.value = Number(data.progress || 0)
  statusMessage.value = data.message || data.current_step || ''

  if (data.status === 'completed') {
    stopPolling()
    await loadResult()
  } else if (data.status === 'failed') {
    stopPolling()
    ElMessage.error(data.last_error || '行业分析失败')
  }
}

const loadResult = async () => {
  if (!currentTaskId.value) return
  const response = await analysisApi.getIndustryTaskResult(currentTaskId.value)
  result.value = response.data
}

const renderMarkdown = (content: string) => {
  try {
    return marked.parse(content || '') as string
  } catch {
    return content || ''
  }
}

const goStock = (code: string) => {
  router.push(`/stocks/${code}`)
}

const initializeModelSettings = async () => {
  try {
    const sortModelsByNewest = (configs: any[]) => {
      const getTimestamp = (config: any) => {
        const timeValue = config.created_at || config.updated_at
        const timestamp = timeValue ? new Date(timeValue).getTime() : 0
        return Number.isNaN(timestamp) ? 0 : timestamp
      }
      return [...configs].sort((a, b) => getTimestamp(b) - getTimestamp(a))
    }

    const defaultModels = await configApi.getDefaultModels()
    modelSettings.value.quickAnalysisModel = defaultModels.quick_analysis_model
    modelSettings.value.deepAnalysisModel = defaultModels.deep_analysis_model

    const llmConfigs = await configApi.getLLMConfigs()
    availableModels.value = sortModelsByNewest(
      llmConfigs.filter((config: any) => config.enabled)
    )
  } catch (error) {
    console.error('加载行业分析模型配置失败:', error)
    modelSettings.value.quickAnalysisModel = 'qwen-turbo'
    modelSettings.value.deepAnalysisModel = 'qwen-max'
  }
}

onMounted(initializeModelSettings)
onBeforeUnmount(stopPolling)
</script>

<style lang="scss" scoped>
.industry-analysis {
  padding: 24px;
}

.page-header {
  margin-bottom: 24px;
}

.page-title {
  display: flex;
  align-items: center;
  gap: 10px;
  margin: 0 0 8px;
  font-size: 28px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.page-description {
  margin: 0;
  color: var(--el-text-color-secondary);
}

.analysis-panel,
.status-panel,
.summary-panel,
.picks-panel {
  margin-bottom: 18px;
  border-radius: 8px;
}

.submit-button {
  width: 100%;
}

.status-row,
.card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.status-title {
  font-size: 16px;
  font-weight: 700;
}

.status-subtitle,
.muted {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.summary-text {
  line-height: 1.8;
  color: var(--el-text-color-primary);
}

.keyword-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin-top: 14px;
}

.report-tabs {
  border-radius: 8px;
  overflow: hidden;
}

.markdown-body {
  line-height: 1.8;
  color: var(--el-text-color-primary);
}

.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3) {
  margin: 18px 0 10px;
}

.markdown-body :deep(table) {
  width: 100%;
  border-collapse: collapse;
}

.markdown-body :deep(th),
.markdown-body :deep(td) {
  border: 1px solid var(--el-border-color);
  padding: 8px 10px;
}

@media (max-width: 768px) {
  .industry-analysis {
    padding: 16px;
  }

  .submit-button {
    margin-top: 0;
  }
}
</style>
