<template>
  <div class="industry-analysis-page">
    <a ref="downloadAnchor" class="hidden-download-link" aria-hidden="true"></a>

    <div class="page-header">
      <div>
        <h1 class="page-title">
          <el-icon class="title-icon"><TrendCharts /></el-icon>
          行业/概念分析
        </h1>
        <p class="page-description">输入行业或主题概念，AI 输出行业尽调、选股推荐与 Top 5 深度分析。</p>
      </div>
      <el-tag type="primary" effect="dark">A股 / CN</el-tag>
    </div>

    <el-row :gutter="24" class="panel-row">
      <el-col :xs="24" :lg="15">
        <el-card class="panel-card form-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div>
                <span class="card-title">分析参数</span>
                <p class="card-subtitle">默认输出完整详细版分析，支持快速主题输入。</p>
              </div>
              <el-tag type="success" effect="plain">详细模式</el-tag>
            </div>
          </template>

          <el-form label-position="top" class="analysis-form">
            <el-form-item label="概念/行业主题" required>
              <el-input
                v-model="formState.concept"
                size="large"
                clearable
                maxlength="50"
                show-word-limit
                placeholder="如：AI相关、高股息、新能源、半导体..."
                @keyup.enter="submitAnalysis"
              >
                <template #prefix>
                  <el-icon><Search /></el-icon>
                </template>
              </el-input>
            </el-form-item>

            <el-form-item label="快捷标签">
              <div class="quick-tags">
                <el-tag
                  v-for="tag in quickConcepts"
                  :key="tag"
                  class="quick-tag"
                  effect="plain"
                  round
                  @click="applyQuickConcept(tag)"
                >
                  {{ tag }}
                </el-tag>
              </div>
            </el-form-item>

            <el-form-item label="推荐股票数量">
              <div class="slider-wrap">
                <el-slider v-model="formState.top_n" :min="1" :max="10" :step="1" show-input />
              </div>
            </el-form-item>

            <div class="model-config-wrap">
              <ModelConfig
                v-model:quick-analysis-model="modelSettings.quickAnalysisModel"
                v-model:deep-analysis-model="modelSettings.deepAnalysisModel"
                :available-models="availableModels"
                analysis-depth="3"
              />
            </div>

            <div class="form-actions">
              <el-button
                type="primary"
                size="large"
                :loading="submitting"
                :disabled="isRunning"
                @click="submitAnalysis"
              >
                <el-icon><Promotion /></el-icon>
                {{ isRunning ? '分析进行中' : '开始分析' }}
              </el-button>
              <el-button size="large" :disabled="submitting || isRunning" @click="resetForm">
                重置
              </el-button>
            </div>
          </el-form>
        </el-card>
      </el-col>

      <el-col :xs="24" :lg="9">
        <el-card class="panel-card history-card" shadow="hover">
          <template #header>
            <div class="card-header">
              <div>
                <span class="card-title">最近分析</span>
                <p class="card-subtitle">点击历史任务可查看结果或继续跟踪进度。</p>
              </div>
              <el-button link type="primary" :loading="historyLoading" @click="loadHistory">刷新</el-button>
            </div>
          </template>

          <el-skeleton v-if="historyLoading" :rows="6" animated />

          <template v-else>
            <el-empty v-if="!historyList.length" description="暂无行业分析记录" :image-size="96" />

            <el-scrollbar v-else max-height="420px">
              <div class="history-list">
                <div
                  v-for="task in historyList"
                  :key="task.task_id"
                  class="history-item"
                  :class="{ active: task.task_id === activeTask?.task_id }"
                  @click="selectHistoryTask(task.task_id)"
                >
                  <div class="history-item-main">
                    <div class="history-concept">{{ task.concept }}</div>
                    <div class="history-item-actions">
                      <el-tag :type="statusTagType(task.status)" size="small">{{ statusText(task.status) }}</el-tag>
                      <el-button
                        v-if="task.status === 'failed' || task.status === 'completed'"
                        link
                        type="danger"
                        size="small"
                        @click.stop="deleteHistoryTask(task.task_id)"
                      >
                        <el-icon><Delete /></el-icon>
                      </el-button>
                    </div>
                  </div>
                  <div class="history-item-meta">
                    <span>{{ formatDateTime(task.updated_at || task.created_at) }}</span>
                    <span v-if="task.status === 'running' || task.status === 'pending'">{{ normalizeProgress(task.progress) }}%</span>
                  </div>
                </div>
              </div>
            </el-scrollbar>
          </template>
        </el-card>
      </el-col>
    </el-row>

    <transition name="fade-slide">
      <el-card v-if="activeTask && isRunning" class="panel-card progress-card" shadow="hover">
        <template #header>
          <div class="card-header">
            <div>
              <span class="card-title">分析进度</span>
              <p class="card-subtitle">{{ activeTask.concept }}</p>
            </div>
            <el-tag type="warning">{{ statusText(activeTask.status) }}</el-tag>
          </div>
        </template>

        <div class="progress-layout">
          <div>
            <div class="progress-label">当前阶段</div>
            <div class="progress-stage">{{ progressStageMessage }}</div>
            <div class="progress-meta">
              <span>任务ID：{{ activeTask.task_id }}</span>
              <span>创建时间：{{ formatDateTime(activeTask.created_at) }}</span>
              <span>更新时间：{{ formatDateTime(activeTask.updated_at) }}</span>
            </div>
          </div>

          <el-progress
            class="industry-main-progress"
            :percentage="normalizeProgress(activeTask.progress)"
            :stroke-width="14"
          />
        </div>
      </el-card>
    </transition>

    <el-card v-if="taskLoading" class="panel-card skeleton-card" shadow="hover">
      <el-skeleton :rows="10" animated />
    </el-card>

    <el-card v-else-if="errorMessage" class="panel-card error-card" shadow="hover">
      <el-result icon="error" title="行业分析失败" :sub-title="errorMessage">
        <template #extra>
          <el-button type="primary" @click="loadHistory">刷新历史</el-button>
          <el-button type="danger" plain :loading="deleting" @click="handleDelete" v-if="activeTask">
            <el-icon><Delete /></el-icon>
            删除此任务
          </el-button>
        </template>
      </el-result>
    </el-card>

    <div v-else-if="activeResult" class="result-section">
      <el-card class="panel-card result-summary-card" shadow="hover">
        <div class="result-summary-header">
          <div>
            <div class="result-title-row">
              <h2>{{ activeResult.concept }}</h2>
              <el-tag type="success">已完成</el-tag>
            </div>
            <p class="result-subtitle">行业尽调、选股报告与结构化推荐结果已生成。</p>
          </div>

          <div class="action-bar">
            <el-dropdown trigger="click" @command="handleDownload">
              <el-button type="primary" :loading="downloading">
                <el-icon><Download /></el-icon>
                下载报告
                <el-icon class="el-icon--right"><ArrowDown /></el-icon>
              </el-button>
              <template #dropdown>
                <el-dropdown-menu>
                  <el-dropdown-item command="markdown">Markdown</el-dropdown-item>
                  <el-dropdown-item command="json">JSON</el-dropdown-item>
                  <el-dropdown-item command="pdf">PDF</el-dropdown-item>
                </el-dropdown-menu>
              </template>
            </el-dropdown>

            <el-button type="danger" plain :loading="deleting" @click="handleDelete">
              <el-icon><Delete /></el-icon>
              删除
            </el-button>
          </div>
        </div>

        <div class="meta-grid">
          <div class="meta-card">
            <span class="meta-label">分析耗时</span>
            <strong>{{ formatDuration(activeResult.analysis_time) }}</strong>
          </div>
          <div class="meta-card">
            <span class="meta-label">LLM 调用</span>
            <strong>{{ activeResult.llm_calls }}</strong>
          </div>
          <div class="meta-card">
            <span class="meta-label">候选数量</span>
            <strong>{{ activeResult.candidate_count }}</strong>
          </div>
          <div class="meta-card">
            <span class="meta-label">筛选后数量</span>
            <strong>{{ activeResult.filtered_count }}</strong>
          </div>
          <div class="meta-card">
            <span class="meta-label">推荐数量</span>
            <strong>{{ activeResult.recommendations.length }}</strong>
          </div>
          <div class="meta-card">
            <span class="meta-label">数据日期</span>
            <strong>{{ activeResult.data_date || '--' }}</strong>
          </div>
        </div>

        <div class="board-tags">
          <span class="board-label">映射板块</span>
          <el-tag v-for="board in activeResult.mapped_boards" :key="board" effect="plain" type="success">
            {{ board }}
          </el-tag>
          <span v-if="!activeResult.mapped_boards.length" class="empty-text">暂无映射板块</span>
        </div>
      </el-card>

      <el-card class="panel-card tabs-card" shadow="hover">
        <el-tabs v-model="activeTab" class="result-tabs">
          <el-tab-pane label="分析过程" name="trace">
            <div class="tab-pane">
              <template v-if="candidateTrace">
                <div class="trace-summary-grid">
                  <div class="meta-card">
                    <span class="meta-label">初始候选</span>
                    <strong>{{ candidateTrace.original_count }}</strong>
                  </div>
                  <div class="meta-card">
                    <span class="meta-label">进入选股</span>
                    <strong>{{ candidateTrace.filtered_count }}</strong>
                  </div>
                  <div class="meta-card">
                    <span class="meta-label">剔除数量</span>
                    <strong>{{ candidateTrace.excluded_count }}</strong>
                  </div>
                </div>

                <el-card class="inner-card" shadow="never">
                  <template #header>
                    <span>概念映射</span>
                  </template>
                  <div class="trace-tags">
                    <el-tag v-for="board in candidateTrace.mapping.board_concepts" :key="`concept-${board}`" type="success" effect="plain">
                      概念：{{ board }}
                    </el-tag>
                    <el-tag v-for="board in candidateTrace.mapping.board_industries" :key="`industry-${board}`" type="warning" effect="plain">
                      行业：{{ board }}
                    </el-tag>
                    <el-tag v-for="keyword in candidateTrace.mapping.keywords" :key="`keyword-${keyword}`" effect="plain">
                      {{ keyword }}
                    </el-tag>
                  </div>
                  <div v-if="candidateTrace.mapping.reasoning" class="markdown-content" v-html="renderMarkdown(candidateTrace.mapping.reasoning)"></div>
                </el-card>

                <el-card class="inner-card" shadow="never">
                  <template #header>
                    <span>候选抓取</span>
                  </template>
                  <el-table :data="candidateTrace.board_fetches" row-key="board_name">
                    <el-table-column prop="board_name" label="板块" min-width="140" show-overflow-tooltip />
                    <el-table-column prop="board_type" label="类型" width="110" />
                    <el-table-column prop="fetched_count" label="抓取数" width="100" align="right" />
                    <el-table-column prop="valid_count" label="有效数" width="100" align="right" />
                    <el-table-column label="状态" width="90">
                      <template #default="{ row }">
                        <el-tag :type="row.failed ? 'danger' : 'success'" size="small">{{ row.failed ? '失败' : '成功' }}</el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column prop="reason" label="说明" min-width="180" show-overflow-tooltip />
                  </el-table>
                </el-card>

                <el-card class="inner-card" shadow="never">
                  <template #header>
                    <span>数据补全</span>
                  </template>
                  <el-table :data="candidateTrace.enrichment" row-key="source">
                    <el-table-column prop="source" label="数据源" min-width="160" />
                    <el-table-column prop="attempted_count" label="尝试数" width="100" align="right" />
                    <el-table-column prop="hit_count" label="命中数" width="100" align="right" />
                    <el-table-column label="字段" min-width="180">
                      <template #default="{ row }">{{ (row.fields || []).join('、') || '--' }}</template>
                    </el-table-column>
                    <el-table-column prop="note" label="说明" min-width="200" show-overflow-tooltip />
                  </el-table>
                </el-card>

                <el-card class="inner-card" shadow="never">
                  <template #header>
                    <span>过滤明细</span>
                  </template>
                  <el-table :data="filterDetails" row-key="code" max-height="520">
                    <el-table-column prop="code" label="代码" width="100" />
                    <el-table-column prop="name" label="名称" width="120" />
                    <el-table-column prop="industry" label="行业" min-width="120" show-overflow-tooltip />
                    <el-table-column label="入围" width="90">
                      <template #default="{ row }">
                        <el-tag :type="row.included ? 'success' : 'info'" size="small">{{ row.included ? '是' : '否' }}</el-tag>
                      </template>
                    </el-table-column>
                    <el-table-column prop="reason_detail" label="原因" min-width="220" show-overflow-tooltip />
                    <el-table-column label="规则评分" width="120">
                      <template #default="{ row }">{{ formatScoreValue(row.rule_score || 0) }}</template>
                    </el-table-column>
                    <el-table-column label="来源板块" min-width="180" show-overflow-tooltip>
                      <template #default="{ row }">{{ (row.source_boards || []).join('、') || '--' }}</template>
                    </el-table-column>
                  </el-table>
                </el-card>
              </template>

              <el-empty v-else description="该历史报告未记录过程明细" :image-size="100" />
            </div>
          </el-tab-pane>

          <el-tab-pane label="主题发现" name="discovery">
            <div class="tab-pane">
              <div v-if="discoveryInsightSections.length" class="discovery-grid">
                <el-card
                  v-for="section in discoveryInsightSections"
                  :key="section.key"
                  class="inner-card discovery-card"
                  shadow="never"
                >
                  <template #header>
                    <div class="inner-card-header">
                      <span>{{ section.title }}</span>
                      <el-tag effect="plain" type="primary">{{ section.items.length }}</el-tag>
                    </div>
                  </template>

                  <div class="discovery-list">
                    <div v-for="(item, index) in section.items" :key="`${section.key}-${index}`" class="discovery-item">
                      <div class="discovery-item-header">
                        <strong>{{ item.title || section.title }}</strong>
                        <el-tag :type="severityTagType(item.severity)" size="small">
                          {{ severityText(item.severity) }}
                        </el-tag>
                      </div>
                      <p v-if="item.summary">{{ item.summary }}</p>
                      <dl>
                        <div v-if="item.evidence">
                          <dt>依据</dt>
                          <dd>{{ item.evidence }}</dd>
                        </div>
                        <div v-if="item.tracking_signal">
                          <dt>跟踪信号</dt>
                          <dd>{{ item.tracking_signal }}</dd>
                        </div>
                        <div v-if="item.expected_timing">
                          <dt>观察窗口</dt>
                          <dd>{{ item.expected_timing }}</dd>
                        </div>
                      </dl>
                      <div v-if="item.related_stocks?.length" class="trace-tags">
                        <el-tag v-for="stock in item.related_stocks" :key="`${section.key}-${index}-${stock.code}`" effect="plain" size="small">
                          {{ stock.name || stock.code }}
                        </el-tag>
                      </div>
                    </div>
                  </div>
                </el-card>
              </div>

              <el-empty v-else description="本次结果未生成主题发现清单" :image-size="100" />
            </div>
          </el-tab-pane>

          <el-tab-pane label="行业逻辑" name="industry-logic">
            <div class="tab-pane">
              <div class="structured-grid">
                <el-card
                  v-for="section in industryLogicDisplaySections"
                  :key="section.key"
                  class="inner-card structured-card"
                  shadow="never"
                >
                  <template #header>
                    <span>{{ section.title }}</span>
                  </template>
                  <div class="markdown-content" v-html="renderMarkdown(section.content)"></div>
                </el-card>
              </div>

              <el-card v-if="supplyChainSegments.length" class="inner-card" shadow="never">
                <template #header>
                  <span>产业链视角</span>
                </template>
                <el-table :data="supplyChainSegments" row-key="segment_key">
                  <el-table-column prop="segment_name" label="环节" width="140" />
                  <el-table-column prop="business" label="主要业务" min-width="180" show-overflow-tooltip />
                  <el-table-column prop="benefit_logic" label="受益逻辑" min-width="200" show-overflow-tooltip />
                  <el-table-column prop="key_indicators" label="关键指标" min-width="180" show-overflow-tooltip />
                  <el-table-column prop="risks" label="风险" min-width="180" show-overflow-tooltip />
                  <el-table-column label="相关股票" min-width="180">
                    <template #default="{ row }">
                      <div class="trace-tags">
                        <el-tag v-for="stock in row.related_stocks" :key="`${row.segment_key}-${stock.code}`" effect="plain" size="small">
                          {{ stock.name || stock.code }}
                        </el-tag>
                      </div>
                    </template>
                  </el-table-column>
                </el-table>
              </el-card>

              <div class="markdown-content" v-html="renderMarkdown(cleanDueDiligenceReport || emptyMarkdown)"></div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="选股逻辑" name="stock-selection">
            <div class="tab-pane">
              <el-card class="inner-card" shadow="never">
                <template #header>
                  <div class="inner-card-header">
                    <span>综合 Top 结果</span>
                    <el-tag type="primary" effect="plain">{{ topRecommendations.length }} 只</el-tag>
                  </div>
                </template>

                <el-table :data="topRecommendations" class="top-table" row-key="code">
                  <el-table-column prop="rank" label="排名" width="72" align="center" />
                  <el-table-column prop="code" label="代码" width="110" />
                  <el-table-column prop="name" label="名称" width="120" />
                  <el-table-column prop="industry" label="行业" min-width="120" show-overflow-tooltip />
                  <el-table-column label="评分" width="180">
                    <template #default="{ row }">
                      <el-progress :percentage="normalizeScore(row.score)" :stroke-width="10" />
                    </template>
                  </el-table-column>
                  <el-table-column prop="summary" label="推荐摘要" min-width="260" show-overflow-tooltip />
                </el-table>
              </el-card>

              <div class="structured-grid">
                <el-card
                  v-for="section in stockSelectionDisplaySections"
                  :key="section.key"
                  class="inner-card structured-card"
                  shadow="never"
                >
                  <template #header>
                    <span>{{ section.title }}</span>
                  </template>
                  <div class="markdown-content" v-html="renderMarkdown(section.content)"></div>
                </el-card>
              </div>

              <div class="markdown-content" v-html="renderMarkdown(cleanStockSelectionReport || emptyMarkdown)"></div>
            </div>
          </el-tab-pane>

          <el-tab-pane label="分组推荐" name="recommendation-groups">
            <div class="tab-pane">
              <div v-if="recommendationGroups.length" class="group-grid">
                <el-card
                  v-for="group in recommendationGroups"
                  :key="group.group_key"
                  class="detail-card"
                  shadow="hover"
                >
                  <template #header>
                    <div>
                      <div class="stock-title">{{ group.group_name || group.group_key }}</div>
                      <div class="stock-subtitle">{{ group.suitable_style || '风格待补充' }}</div>
                    </div>
                  </template>
                  <div class="markdown-content" v-html="renderMarkdown(group.description || emptyMarkdown)"></div>
                  <el-alert v-if="group.main_risks" class="group-risk" type="warning" :closable="false" :title="group.main_risks" />
                  <el-table :data="group.stocks" row-key="code" class="top-table">
                    <el-table-column prop="code" label="代码" width="100" />
                    <el-table-column prop="name" label="名称" width="120" />
                    <el-table-column label="评分" width="130">
                      <template #default="{ row }">
                        <el-progress :percentage="normalizeScore(row.score)" :stroke-width="8" />
                      </template>
                    </el-table-column>
                    <el-table-column prop="recommendation_logic" label="推荐逻辑" min-width="220" show-overflow-tooltip />
                    <el-table-column prop="main_risks" label="主要风险" min-width="180" show-overflow-tooltip />
                  </el-table>
                </el-card>
              </div>
              <el-empty v-else description="本次结果未生成分组推荐" :image-size="100" />
            </div>
          </el-tab-pane>

          <el-tab-pane label="个股详情" name="top-detail">
            <div class="detail-grid">
              <el-card
                v-for="item in topRecommendations"
                :key="item.code"
                class="detail-card"
                shadow="hover"
              >
                <template #header>
                  <div class="detail-card-header">
                    <div>
                      <div class="stock-title">#{{ item.rank }} {{ item.name }}</div>
                      <div class="stock-subtitle">{{ item.code }} · {{ item.industry || '未分类' }}</div>
                    </div>
                    <el-tag type="primary" effect="dark">{{ normalizeScore(item.score) }}分</el-tag>
                  </div>
                </template>

                <div class="detail-score">
                  <el-progress :percentage="normalizeScore(item.score)" :stroke-width="12" />
                </div>

                <div class="detail-tags">
                  <el-tag effect="plain" type="success">{{ item.suitable_style || '风格待补充' }}</el-tag>
                  <el-tag effect="plain" type="warning">{{ item.supply_chain_position || '产业链位置待补充' }}</el-tag>
                </div>

                <div class="detail-block">
                  <h4>推荐摘要</h4>
                  <div class="markdown-content" v-html="renderMarkdown(item.summary || emptyMarkdown)"></div>
                </div>
                <div class="detail-block">
                  <h4>推荐逻辑</h4>
                  <div class="markdown-content" v-html="renderMarkdown(item.recommendation_logic || emptyMarkdown)"></div>
                </div>
                <div class="detail-block">
                  <h4>主要优势</h4>
                  <div class="markdown-content" v-html="renderMarkdown(item.main_advantages || emptyMarkdown)"></div>
                </div>
                <div class="detail-block">
                  <h4>主要风险</h4>
                  <div class="markdown-content" v-html="renderMarkdown(item.main_risks || emptyMarkdown)"></div>
                </div>

                <div v-if="scoreBreakdownEntries(item).length" class="detail-block">
                  <h4>评分拆解</h4>
                  <div class="score-breakdown">
                    <el-tag
                      v-for="entry in scoreBreakdownEntries(item)"
                      :key="`${item.code}-${entry.key}`"
                      effect="plain"
                    >
                      {{ entry.key }}：{{ formatScoreValue(entry.value) }}
                    </el-tag>
                  </div>
                </div>

                <div v-if="metricEntries(item).length" class="detail-block">
                  <h4>关键指标</h4>
                  <div class="metric-tags">
                    <el-tag
                      v-for="entry in metricEntries(item)"
                      :key="`${item.code}-${entry.key}`"
                      effect="plain"
                      class="metric-tag"
                    >
                      {{ entry.key }}：{{ formatMetricValue(entry.value) }}
                    </el-tag>
                  </div>
                </div>
              </el-card>
            </div>

            <el-empty v-if="!topRecommendations.length" description="暂无推荐股票详情" :image-size="100" />
          </el-tab-pane>
        </el-tabs>
      </el-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { ArrowDown, Delete, Download, Promotion, Search, TrendCharts } from '@element-plus/icons-vue'
import dayjs from 'dayjs'
import { marked } from 'marked'
import {
  industryAnalysisApi,
  type IndustryAnalysisDetailLevel,
  type IndustryAnalysisResult,
  type IndustryAnalysisTask,
  type IndustryAnalysisTaskStatus,
  type DiscoveryInsightItem,
  type StockRecommendation
} from '@/api/industryAnalysis'
import ModelConfig from '@/components/ModelConfig.vue'
import { useAnalysisModelSettings } from '@/composables/useAnalysisModelSettings'

marked.setOptions({ breaks: true, gfm: true })

const quickConcepts = ['AI相关', '高股息', '新能源', '半导体', '机器人', '低空经济', '出海链', '中特估']
const emptyMarkdown = '暂无内容'
const route = useRoute()

type DownloadFormat = 'markdown' | 'json' | 'pdf'

interface StructuredSection {
  key: string
  title: string
  content: string
}

interface DiscoveryInsightSection {
  key: string
  title: string
  items: DiscoveryInsightItem[]
}

const statusTextMap: Record<IndustryAnalysisTaskStatus, string> = {
  pending: '排队中',
  running: '分析中',
  completed: '已完成',
  failed: '已失败'
}

const formState = reactive({
  concept: '',
  detail_level: 'detailed' as IndustryAnalysisDetailLevel,
  top_n: 5,
  market: 'CN' as const
})

const {
  modelSettings,
  availableModels,
  initializeModelSettings,
  getModelParameters
} = useAnalysisModelSettings()

const activeTab = ref('trace')
const submitting = ref(false)
const historyLoading = ref(false)
const taskLoading = ref(false)
const downloading = ref(false)
const deleting = ref(false)
const historyList = ref<IndustryAnalysisTask[]>([])
const activeTask = ref<IndustryAnalysisTask | null>(null)
const errorMessage = ref('')
const pollTimer = ref<number | null>(null)
const completedToastTaskId = ref('')
const failedToastTaskId = ref('')
const downloadAnchor = ref<HTMLAnchorElement | null>(null)

const isRunning = computed(() => {
  const status = activeTask.value?.status
  return status === 'pending' || status === 'running'
})

const activeResult = computed<IndustryAnalysisResult | null>(() => activeTask.value?.result ?? null)
const topRecommendations = computed(() => activeResult.value?.recommendations.slice(0, 5) ?? [])
const candidateTrace = computed(() => activeResult.value?.candidate_trace ?? null)
const filterDetails = computed(() => candidateTrace.value?.filter_details ?? [])
const supplyChainSegments = computed(() => activeResult.value?.supply_chain_analysis ?? [])
const recommendationGroups = computed(() => activeResult.value?.recommendation_groups ?? [])
const discoveryInsightSections = computed<DiscoveryInsightSection[]>(() => {
  const insights = activeResult.value?.discovery_insights
  if (!insights) return []

  return [
    { key: 'industry_bottlenecks', title: '产业瓶颈', items: insights.industry_bottlenecks || [] },
    { key: 'non_consensus_targets', title: '非共识标的', items: insights.non_consensus_targets || [] },
    { key: 'financial_inflections', title: '财务拐点', items: insights.financial_inflections || [] },
    { key: 'red_team_counterpoints', title: '红队反证', items: insights.red_team_counterpoints || [] },
    { key: 'future_catalysts', title: '未来催化事件', items: insights.future_catalysts || [] }
  ].filter(section => section.items.length > 0)
})
const cleanDueDiligenceReport = computed(() => stripStructuredPayloadBlocks(activeResult.value?.due_diligence_report || ''))
const cleanStockSelectionReport = computed(() => stripStructuredPayloadBlocks(activeResult.value?.stock_selection_report || ''))
const progressStageMessage = computed(() => {
  if (!activeTask.value) return ''
  return activeTask.value.progress_message || (activeTask.value.status === 'pending' ? '任务排队中...' : 'AI 正在分析中...')
})
const industryLogicDisplaySections = computed<StructuredSection[]>(() => {
  const result = activeResult.value
  if (!result) return []
  const sections = result.industry_logic_sections

  return [
    { key: 'supply_chain', title: '产业链', content: sections?.supply_chain || '' },
    { key: 'policy', title: '政策', content: sections?.policy || '' },
    { key: 'cycle', title: '景气度', content: sections?.cycle || '' },
    { key: 'demand', title: '需求驱动', content: sections?.demand || '' },
    { key: 'competition', title: '竞争格局', content: sections?.competition || '' },
    { key: 'risks', title: '风险', content: sections?.risks || '' }
  ].filter(section => section.content && section.content.trim())
})

const stockSelectionDisplaySections = computed<StructuredSection[]>(() => {
  const result = activeResult.value
  if (!result) return []
  const sections = result.stock_selection_sections

  return [
    { key: 'leaders', title: '龙头', content: sections?.leaders || result.selection_reasoning },
    { key: 'growth_beta', title: '成长弹性', content: sections?.growth_beta || '' },
    { key: 'valuation_repair', title: '低估修复', content: sections?.valuation_repair || '' },
    { key: 'high_risk', title: '高风险高波动', content: sections?.high_risk || '' },
    { key: 'watchlist', title: '观察名单', content: sections?.watchlist || '' },
    { key: 'risk_warning', title: '风险提示', content: result.risk_warning },
    { key: 'exclusion_reasons', title: '剔除原因', content: result.exclusion_reasons },
    { key: 'portfolio_advice', title: '组合建议', content: result.portfolio_advice },
    { key: 'tracking_indicators', title: '跟踪指标', content: result.tracking_indicators },
    { key: 'conclusion', title: '结论', content: result.conclusion }
  ].filter(section => section.content && section.content.trim())
})

const getErrorMessage = async (error: unknown, fallback: string) => {
  const blob = typeof error === 'object' && error !== null ? (error as { response?: { data?: unknown } }).response?.data : undefined
  if (blob instanceof Blob) {
    try {
      const text = await blob.text()
      try {
        const parsed = JSON.parse(text) as { detail?: string; message?: string }
        return parsed.detail || parsed.message || fallback
      } catch {
        return text || fallback
      }
    } catch {
      return fallback
    }
  }

  if (error instanceof Error && error.message) {
    return error.message
  }

  return fallback
}

const stripStructuredPayloadBlocks = (content: string) => {
  if (!content) return ''
  const hasStructuredKeys = (text: string) => (
    text.includes('industry_logic_sections') ||
    text.includes('stock_selection_sections') ||
    text.includes('supply_chain_analysis') ||
    text.includes('recommendation_groups') ||
    text.includes('discovery_insights')
  )

  let cleaned = content.replace(/```(?:json)?\s*([\s\S]*?)\s*```/gi, (block, body) => {
    return hasStructuredKeys(String(body || '')) ? '' : block
  })

  const markerMatch = cleaned.match(/\s*STRUCTURED_JSON\s*:\s*(\{[\s\S]*\})\s*$/i)
  if (markerMatch && hasStructuredKeys(markerMatch[1] || '')) {
    cleaned = cleaned.slice(0, markerMatch.index)
  }

  return cleaned.replace(/\n{3,}/g, '\n\n').trim()
}

const renderMarkdown = (content: string) => {
  try {
    return String(marked.parse(content || ''))
  } catch {
    return `<pre style="white-space: pre-wrap; font-family: inherit;">${content || ''}</pre>`
  }
}

const formatDateTime = (value?: string | null) => {
  if (!value) return '--'
  return dayjs(value).format('YYYY-MM-DD HH:mm:ss')
}

const formatDuration = (seconds?: number | null) => {
  if (seconds === null || seconds === undefined) return '--'
  if (seconds < 60) return `${seconds.toFixed(1)} 秒`
  const minutes = Math.floor(seconds / 60)
  const remainSeconds = Math.round(seconds % 60)
  return `${minutes}分 ${remainSeconds}秒`
}

const normalizeProgress = (value?: number | null) => Math.max(0, Math.min(100, Math.round(Number(value || 0))))
const normalizeScore = (value?: number | null) => Math.max(0, Math.min(100, Math.round(Number(value || 0))))

const statusText = (status?: IndustryAnalysisTaskStatus) => {
  if (!status) return '未知状态'
  return statusTextMap[status] || '未知状态'
}

const statusTagType = (status?: IndustryAnalysisTaskStatus) => {
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'danger'
  if (status === 'running') return 'warning'
  return 'info'
}

const severityTagType = (severity?: string) => {
  if (severity === 'high') return 'danger'
  if (severity === 'low') return 'info'
  return 'warning'
}

const severityText = (severity?: string) => {
  if (severity === 'high') return '高'
  if (severity === 'low') return '低'
  return '中'
}

const formatScoreValue = (value: number) => {
  if (Number.isInteger(value)) return String(value)
  return value.toFixed(1)
}

const formatMetricValue = (value: unknown) => {
  if (value === null || value === undefined || value === '') return '--'
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(2)
  }
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.map(item => String(item)).join('、')
  if (typeof value === 'object') {
    try {
      return JSON.stringify(value)
    } catch {
      return String(value)
    }
  }
  return String(value)
}

const scoreBreakdownEntries = (item: StockRecommendation) => {
  return Object.entries(item.score_breakdown || {}).map(([key, value]) => ({ key, value }))
}

const metricEntries = (item: StockRecommendation) => {
  return Object.entries(item.key_metrics || {}).map(([key, value]) => ({ key, value }))
}

const upsertHistoryTask = (task: IndustryAnalysisTask) => {
  const next = [...historyList.value]
  const index = next.findIndex(item => item.task_id === task.task_id)
  if (index >= 0) {
    next[index] = task
  } else {
    next.unshift(task)
  }

  next.sort((a, b) => dayjs(b.updated_at || b.created_at).valueOf() - dayjs(a.updated_at || a.created_at).valueOf())
  historyList.value = next.slice(0, 20)
}

const removeHistoryTask = (taskId: string) => {
  historyList.value = historyList.value.filter(item => item.task_id !== taskId)
}

const stopPolling = () => {
  if (pollTimer.value !== null) {
    window.clearInterval(pollTimer.value)
    pollTimer.value = null
  }
}

const startPolling = (taskId: string) => {
  stopPolling()
  pollTimer.value = window.setInterval(() => {
    void loadTaskDetail(taskId, { silent: true })
  }, 5000)
}

const loadHistory = async () => {
  historyLoading.value = true
  try {
    const response = await industryAnalysisApi.getHistory(20)
    historyList.value = response.data || []

    if (!activeTask.value && historyList.value.length > 0) {
      await loadTaskDetail(historyList.value[0].task_id, { silent: true })
    }
  } catch (error) {
    errorMessage.value = await getErrorMessage(error, '加载行业分析历史失败')
  } finally {
    historyLoading.value = false
  }
}

const loadTaskDetail = async (taskId: string, options?: { silent?: boolean }) => {
  if (!options?.silent) {
    taskLoading.value = true
  }

  try {
    const response = await industryAnalysisApi.getResult(taskId)
    const task = response.data

    activeTask.value = task
    errorMessage.value = task.status === 'failed' ? task.error || '行业分析执行失败' : ''
    upsertHistoryTask(task)

    if (task.status === 'pending' || task.status === 'running') {
      startPolling(task.task_id)
    } else {
      stopPolling()
    }

    if (task.status === 'completed' && completedToastTaskId.value !== task.task_id) {
      completedToastTaskId.value = task.task_id
      if (!options?.silent) {
        ElMessage.success('行业/概念分析已完成')
      }
    }

    if (task.status === 'failed' && task.error && failedToastTaskId.value !== task.task_id) {
      failedToastTaskId.value = task.task_id
      if (!options?.silent) {
        ElMessage.error(task.error)
      }
    }
  } catch (error) {
    stopPolling()
    errorMessage.value = await getErrorMessage(error, '获取任务详情失败')
  } finally {
    if (!options?.silent) {
      taskLoading.value = false
    }
  }
}

const submitAnalysis = async () => {
  const concept = formState.concept.trim()
  if (!concept) {
    ElMessage.warning('请输入行业或概念关键词')
    return
  }

  submitting.value = true
  errorMessage.value = ''

  try {
    const response = await industryAnalysisApi.submit({
      concept,
      detail_level: 'detailed',
      top_n: formState.top_n,
      market: formState.market,
      ...getModelParameters()
    })

    const submittedTask = response.data
    activeTask.value = {
      task_id: submittedTask.task_id,
      status: submittedTask.status,
      progress: 0,
      progress_message: '任务已提交，正在排队分析...',
      concept: submittedTask.concept,
      detail_level: 'detailed',
      top_n: formState.top_n,
      result: null,
      error: null,
      created_at: submittedTask.created_at,
      updated_at: submittedTask.created_at,
      completed_at: null
    }

    activeTab.value = 'trace'
    ElMessage.success(response.message || '分析任务已提交')
    await loadHistory()
    await loadTaskDetail(submittedTask.task_id, { silent: true })
  } catch (error) {
    ElMessage.error(await getErrorMessage(error, '提交行业分析任务失败'))
  } finally {
    submitting.value = false
  }
}

const selectHistoryTask = async (taskId: string) => {
  activeTab.value = 'trace'
  errorMessage.value = ''
  await loadTaskDetail(taskId)
}

const applyQuickConcept = (concept: string) => {
  formState.concept = concept
}

const resetForm = () => {
  formState.concept = ''
  formState.top_n = 5
}

const sanitizeFileName = (value: string) => {
  return value.replace(/[\/:*?"<>|\s]+/g, '-').replace(/-+/g, '-').replace(/^-|-$/g, '') || 'industry-analysis'
}

const getDownloadExtension = (format: DownloadFormat) => {
  if (format === 'markdown') return 'md'
  if (format === 'json') return 'json'
  return 'pdf'
}

const handleDownload = async (command: string | number | object) => {
  if (!activeTask.value) return

  const format = String(command) as DownloadFormat
  downloading.value = true

  try {
    const blob = await industryAnalysisApi.download(activeTask.value.task_id, format)
    const url = window.URL.createObjectURL(blob)
    const anchor = downloadAnchor.value
    const fileName = `${sanitizeFileName(activeTask.value.concept)}-${activeTask.value.task_id}.${getDownloadExtension(format)}`

    if (anchor) {
      anchor.href = url
      anchor.download = fileName
      anchor.click()
    } else {
      const tempAnchor = document.createElement('a')
      tempAnchor.href = url
      tempAnchor.download = fileName
      tempAnchor.style.display = 'none'
      document.body.appendChild(tempAnchor)
      tempAnchor.click()
      document.body.removeChild(tempAnchor)
    }

    window.setTimeout(() => window.URL.revokeObjectURL(url), 1000)
    ElMessage.success('报告下载成功')
  } catch (error) {
    ElMessage.error(await getErrorMessage(error, '下载报告失败'))
  } finally {
    downloading.value = false
  }
}

const handleDelete = async () => {
  if (!activeTask.value) return

  try {
    await ElMessageBox.confirm(`确定删除“${activeTask.value.concept}”的分析记录吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }

  deleting.value = true

  try {
    const taskId = activeTask.value.task_id
    const response = await industryAnalysisApi.delete(taskId)

    if (activeTask.value?.task_id === taskId) {
      stopPolling()
      activeTask.value = null
      errorMessage.value = ''
    }

    removeHistoryTask(taskId)
    ElMessage.success(response.message || '行业分析记录已删除')

    if (historyList.value.length > 0) {
      await loadTaskDetail(historyList.value[0].task_id, { silent: true })
    }
  } catch (error) {
    ElMessage.error(await getErrorMessage(error, '删除行业分析记录失败'))
  } finally {
    deleting.value = false
  }
}

const deleteHistoryTask = async (taskId: string) => {
  const task = historyList.value.find(t => t.task_id === taskId)
  const label = task?.concept || taskId

  try {
    await ElMessageBox.confirm(`确定删除"${label}"的分析记录吗？`, '删除确认', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
  } catch {
    return
  }

  try {
    await industryAnalysisApi.delete(taskId)

    if (activeTask.value?.task_id === taskId) {
      stopPolling()
      activeTask.value = null
      errorMessage.value = ''
    }

    removeHistoryTask(taskId)
    ElMessage.success('分析记录已删除')

    if (historyList.value.length > 0 && !activeTask.value) {
      await loadTaskDetail(historyList.value[0].task_id, { silent: true })
    }
  } catch (error) {
    ElMessage.error(await getErrorMessage(error, '删除失败'))
  }
}

onMounted(() => {
  void initializeModelSettings()
  const taskId = typeof route.query.task_id === 'string' ? route.query.task_id : ''
  if (taskId) {
    void loadTaskDetail(taskId, { silent: true }).finally(() => {
      void loadHistory()
    })
  } else {
    void loadHistory()
  }
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.industry-analysis-page {
  min-height: 100%;
  padding: 24px;
  background: var(--el-bg-color-page);
}

.hidden-download-link {
  display: none;
}

.page-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 24px;
  padding: 28px 32px;
  border-radius: 24px;
  border: 1px solid color-mix(in srgb, var(--el-color-primary) 18%, transparent);
  background: linear-gradient(135deg, color-mix(in srgb, var(--el-color-primary) 12%, var(--el-bg-color) 88%), var(--el-bg-color));
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.08);
}

.page-title {
  display: flex;
  align-items: center;
  gap: 12px;
  margin: 0;
  font-size: 30px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.title-icon {
  color: var(--el-color-primary);
}

.page-description {
  margin: 10px 0 0;
  color: var(--el-text-color-regular);
}

.panel-row,
.progress-card,
.skeleton-card,
.error-card,
.result-section {
  margin-bottom: 24px;
}

.panel-card {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 20px;
  overflow: hidden;
  transition: transform 0.25s ease, box-shadow 0.25s ease;
}

.panel-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 14px 28px rgba(0, 0, 0, 0.08);
}

.card-header,
.result-summary-header,
.inner-card-header,
.detail-card-header,
.history-item-main {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}

.history-item-actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}

.card-title {
  display: block;
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.card-subtitle,
.result-subtitle {
  margin: 6px 0 0;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.analysis-form {
  padding-top: 6px;
}

.quick-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
}

.trace-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.quick-tag {
  cursor: pointer;
  transition: all 0.2s ease;
}

.quick-tag:hover {
  transform: translateY(-1px);
  color: var(--el-color-primary);
  border-color: var(--el-color-primary-light-5);
}

.slider-wrap {
  padding: 0 8px;
}

.model-config-wrap {
  margin: 8px 0 4px;
  padding: 16px;
  border-radius: 12px;
  border: 1px solid var(--el-border-color-lighter);
  background: var(--el-fill-color-blank);
}

.form-actions,
.action-bar,
.detail-tags,
.score-breakdown,
.metric-tags,
.board-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.progress-layout {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.progress-label,
.meta-label,
.board-label {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.progress-stage {
  margin-top: 8px;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.7;
  color: var(--el-text-color-primary);
}

.progress-meta,
.history-item-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  margin-top: 12px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.industry-main-progress {
  width: 100%;
}

.industry-main-progress :deep(.el-progress-bar__outer) {
  height: 14px !important;
  background-color: color-mix(in srgb, var(--el-color-primary) 10%, var(--el-fill-color-light));
}

.industry-main-progress :deep(.el-progress-bar__inner) {
  transition: width 0.6s ease;
}

.history-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.history-item {
  width: 100%;
  padding: 16px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 16px;
  background: var(--el-fill-color-extra-light);
  color: inherit;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s ease;
}

.history-item:hover,
.history-item.active {
  border-color: color-mix(in srgb, var(--el-color-primary) 35%, transparent);
  background: color-mix(in srgb, var(--el-color-primary) 9%, var(--el-fill-color-extra-light) 91%);
}

.history-concept {
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.result-title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-bottom: 4px;
}

.result-title-row h2 {
  margin: 0;
  font-size: 24px;
  color: var(--el-text-color-primary);
}

.meta-grid {
  display: grid;
  grid-template-columns: repeat(6, minmax(0, 1fr));
  gap: 14px;
  margin-top: 24px;
}

.meta-card {
  padding: 16px;
  border-radius: 16px;
  background: var(--el-fill-color-extra-light);
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.meta-card strong {
  font-size: 20px;
  color: var(--el-color-primary);
}

.board-tags {
  align-items: center;
  margin-top: 18px;
}

.empty-text {
  color: var(--el-text-color-secondary);
}

.tabs-card,
.result-summary-card {
  margin-bottom: 24px;
}

.tab-pane {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.inner-card {
  border-radius: 16px;
  background: color-mix(in srgb, var(--el-fill-color-extra-light) 70%, transparent);
}

.structured-grid,
.detail-grid,
.group-grid,
.discovery-grid {
  display: grid;
  gap: 20px;
}

.structured-grid,
.discovery-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.detail-grid,
.group-grid {
  grid-template-columns: repeat(2, minmax(0, 1fr));
}

.trace-summary-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
}

.group-risk {
  margin: 12px 0;
}

.discovery-list {
  display: grid;
  gap: 14px;
}

.discovery-item {
  padding: 14px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 12px;
  background: var(--el-fill-color-blank);
}

.discovery-item-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 10px;
}

.discovery-item p {
  margin: 10px 0;
  color: var(--el-text-color-regular);
  line-height: 1.7;
}

.discovery-item dl {
  display: grid;
  gap: 8px;
  margin: 0 0 10px;
}

.discovery-item dl > div {
  display: grid;
  grid-template-columns: 76px minmax(0, 1fr);
  gap: 10px;
}

.discovery-item dt {
  color: var(--el-text-color-secondary);
}

.discovery-item dd {
  margin: 0;
  overflow-wrap: anywhere;
}

.detail-card {
  border-radius: 18px;
}

.stock-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--el-text-color-primary);
}

.stock-subtitle {
  margin-top: 6px;
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.detail-score {
  margin-bottom: 18px;
}

.detail-block + .detail-block {
  margin-top: 18px;
}

.detail-block h4 {
  margin: 0 0 10px;
  font-size: 15px;
  color: var(--el-text-color-primary);
}

.metric-tag {
  margin-right: 0;
}

.markdown-content {
  line-height: 1.8;
  color: var(--el-text-color-primary);
  word-break: break-word;
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3),
.markdown-content :deep(h4) {
  margin: 18px 0 10px;
  color: var(--el-text-color-primary);
}

.markdown-content :deep(p),
.markdown-content :deep(ul),
.markdown-content :deep(ol),
.markdown-content :deep(blockquote) {
  margin: 0 0 12px;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  padding-left: 20px;
}

.markdown-content :deep(code) {
  padding: 2px 6px;
  border-radius: 6px;
  background: var(--el-fill-color-light);
}

.markdown-content :deep(pre) {
  padding: 14px;
  border-radius: 12px;
  overflow-x: auto;
  background: #111827;
  color: #e5e7eb;
}

.markdown-content :deep(table) {
  width: 100%;
  margin: 14px 0;
  border-collapse: collapse;
  overflow: hidden;
  border-radius: 12px;
}

.markdown-content :deep(th),
.markdown-content :deep(td) {
  padding: 10px 12px;
  border: 1px solid var(--el-border-color-light);
  text-align: left;
}

.markdown-content :deep(th) {
  background: var(--el-fill-color-light);
}

.markdown-content :deep(blockquote) {
  padding: 12px 16px;
  border-left: 4px solid var(--el-color-primary);
  border-radius: 0 12px 12px 0;
  background: color-mix(in srgb, var(--el-color-primary) 8%, transparent);
}

.fade-slide-enter-active,
.fade-slide-leave-active {
  transition: all 0.25s ease;
}

.fade-slide-enter-from,
.fade-slide-leave-to {
  opacity: 0;
  transform: translateY(8px);
}

@media (max-width: 1400px) {
  .meta-grid {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 992px) {
  .page-header,
  .result-summary-header {
    flex-direction: column;
    align-items: flex-start;
  }

  .structured-grid,
  .detail-grid,
  .group-grid,
  .discovery-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .industry-analysis-page {
    padding: 16px;
  }

  .page-header {
    padding: 22px 20px;
  }

  .page-title {
    font-size: 24px;
  }

  .meta-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .trace-summary-grid {
    grid-template-columns: 1fr;
  }

  .card-header,
  .inner-card-header,
  .detail-card-header,
  .history-item-main {
    align-items: flex-start;
  }
}

@media (max-width: 576px) {
  .meta-grid {
    grid-template-columns: 1fr;
  }

  .form-actions,
  .action-bar {
    width: 100%;
  }

  .form-actions :deep(.el-button),
  .action-bar :deep(.el-button) {
    flex: 1;
  }
}
</style>
