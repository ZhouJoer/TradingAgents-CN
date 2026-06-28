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
          <div v-if="selectedConceptExplanations.length" class="concept-explain-list">
            <div v-for="item in selectedConceptExplanations" :key="item.term" class="concept-explain-item">
              <strong>{{ item.term }}</strong>
              <p>{{ item.meaning }}</p>
              <small>{{ item.role }}</small>
            </div>
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
              <el-input-number v-model="singleForm.params.top_k" :min="1" :max="5" @change="markParamsEdited" />
            </el-form-item>
            <el-form-item label="频率">
              <el-radio-group v-model="singleForm.params.rebalance_frequency" @change="markParamsEdited">
                <el-radio-button label="weekly">周</el-radio-button>
                <el-radio-button label="biweekly">双周</el-radio-button>
                <el-radio-button label="monthly">月</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="TrendCharts" :loading="loading.single" @click="runSingle">运行回测</el-button>
              <el-button :icon="DocumentAdd" :loading="loading.candidates" @click="saveDiscoveredAdaptiveTopK">保存混合参数</el-button>
              <el-button type="success" :icon="Connection" @click="createTrackerFromCurrentParams">加入模拟仓</el-button>
            </el-form-item>
          </el-form>
          <div class="param-source-bar">
            <div class="param-source-main">
              <el-tag :type="paramSourceTagType" size="small" effect="light">{{ paramSourceKindLabel }}</el-tag>
              <strong>{{ paramSource.label }}</strong>
              <span>{{ paramSource.detail }}</span>
            </div>
            <div v-if="paramSourceStats.length" class="param-source-stats">
              <span v-for="item in paramSourceStats" :key="item.label">{{ item.label }} {{ item.value }}</span>
            </div>
            <el-button size="small" :icon="Refresh" :disabled="paramSource.kind === 'default'" @click="restoreDefaultParams">
              恢复默认
            </el-button>
          </div>
        </section>

        <section v-if="editableParamFields.length" class="param-panel">
          <div class="section-title">
            <span>策略参数</span>
            <small>{{ strategyParamHint }} · {{ paramSourceKindLabel }}</small>
          </div>
          <div class="param-editor-grid">
            <div v-for="field in editableParamFields" :key="field.key" class="param-editor-item">
              <label :for="`param-${field.key}`">{{ field.label || paramLabel(field.key) }}</label>
              <el-select
                v-if="field.type === 'select'"
                :id="`param-${field.key}`"
                v-model="singleForm.params[field.key]"
                class="param-control"
                size="small"
                @change="markParamsEdited"
              >
                <el-option
                  v-for="option in field.options || []"
                  :key="String(option)"
                  :label="valueLabels[String(option)] || String(option)"
                  :value="option"
                />
              </el-select>
              <el-switch
                v-else-if="field.type === 'boolean'"
                :id="`param-${field.key}`"
                v-model="singleForm.params[field.key]"
                class="param-switch"
                size="small"
                @change="markParamsEdited"
              />
              <el-input-number
                v-else-if="field.type === 'number'"
                :id="`param-${field.key}`"
                v-model="singleForm.params[field.key]"
                class="param-control"
                size="small"
                controls-position="right"
                :min="field.min"
                :max="field.max"
                :step="paramStep(field)"
                :precision="paramPrecision(field)"
                @change="markParamsEdited"
              />
              <el-input
                v-else
                :id="`param-${field.key}`"
                :model-value="listParamValue(field.key)"
                class="param-control"
                size="small"
                @update:model-value="updateListParam(field.key, $event)"
              />
            </div>
          </div>
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

        <section v-if="returnAttributionRows.length" class="table-band">
          <div class="section-title">
            <span>收益来源（持仓贡献估算）</span>
            <small :title="singleResult?.diagnostics?.return_attribution_residual_reason">
              残差 {{ pct(singleResult?.diagnostics?.return_attribution_residual) }} / 成本拖累 {{ pct(singleResult?.diagnostics?.return_attribution_cost_drag) }}
            </small>
          </div>
          <el-table :data="returnAttributionRows" size="small" height="260">
            <el-table-column label="ETF" min-width="180">
              <template #default="{ row }">
                <strong>{{ row.code }}</strong>
                <span class="muted-cell">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="贡献" width="100">
              <template #default="{ row }">{{ pct(row.contribution) }}</template>
            </el-table-column>
            <el-table-column label="占总收益" width="100">
              <template #default="{ row }">{{ pct(row.contribution_share) }}</template>
            </el-table-column>
            <el-table-column label="持有天数" prop="active_days" width="90" />
            <el-table-column label="平均仓位" width="100">
              <template #default="{ row }">{{ pct(row.avg_weight) }}</template>
            </el-table-column>
            <el-table-column label="标的涨跌" width="100">
              <template #default="{ row }">{{ pct(row.asset_return) }}</template>
            </el-table-column>
          </el-table>
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
            <el-table-column label="原始选中" min-width="160">
              <template #default="{ row }">{{ row.raw_selected?.join(', ') || '-' }}</template>
            </el-table-column>
            <el-table-column label="稳定器" min-width="180">
              <template #default="{ row }">{{ stabilityLabel(row.stability) }}</template>
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
            <el-form-item label="当前参数">
              <el-checkbox v-model="compareForm.includeCurrentParams">
                纳入对比
                <span class="inline-hint">{{ compareCurrentParamLabel }}</span>
              </el-checkbox>
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

      <el-tab-pane label="参数库" name="library">
        <section class="control-band">
          <el-form :model="candidateFilters" inline label-width="72px">
            <el-form-item label="策略">
              <el-select v-model="candidateFilters.strategy_id" clearable filterable class="wide-control">
                <el-option v-for="item in strategies" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item label="状态">
              <el-select v-model="candidateFilters.status" class="small-control">
                <el-option label="有效" value="active" />
                <el-option label="归档" value="archived" />
                <el-option label="全部" value="all" />
              </el-select>
            </el-form-item>
            <el-form-item label="关键词">
              <el-input v-model="candidateFilters.keyword" clearable placeholder="名称 / 标签 / 备注" />
            </el-form-item>
            <el-form-item>
              <el-checkbox v-model="candidateFilters.favorite">仅收藏</el-checkbox>
            </el-form-item>
            <el-form-item>
              <el-button :icon="Search" :loading="loading.candidates" @click="loadCandidates">筛选</el-button>
            </el-form-item>
          </el-form>
        </section>

        <section class="table-band">
          <div class="section-title">
            <span>候选参数库</span>
            <small>{{ savedCandidates.length }} 组，可直接回测、对比或创建模拟跟踪</small>
          </div>
          <el-table :data="savedCandidates" size="small" height="330" v-loading="loading.candidates">
            <el-table-column label="参数集" min-width="220">
              <template #default="{ row }">
                <strong>{{ row.name || strategyName(row.strategy_id) }}</strong>
                <span class="muted-cell">{{ strategyName(row.strategy_id) }} · {{ candidateUniverseText(row) }}</span>
              </template>
            </el-table-column>
            <el-table-column label="标签" min-width="160">
              <template #default="{ row }">
                <el-tag v-for="tag in candidateTags(row)" :key="tag" size="small" effect="plain">{{ tag }}</el-tag>
                <span v-if="!candidateTags(row).length" class="muted-cell">-</span>
              </template>
            </el-table-column>
            <el-table-column label="Score" width="90">
              <template #default="{ row }">{{ num(row.score) }}</template>
            </el-table-column>
            <el-table-column label="收益" width="90">
              <template #default="{ row }">{{ pct(row.metrics?.total_return) }}</template>
            </el-table-column>
            <el-table-column label="应用" width="90">
              <template #default="{ row }">{{ row.applied_count || 0 }}</template>
            </el-table-column>
            <el-table-column label="状态" width="90">
              <template #default="{ row }">
                <el-tag :type="row.status === 'archived' ? 'info' : 'success'" size="small">
                  {{ row.status === 'archived' ? '归档' : '有效' }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="操作" width="370" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :icon="Select" @click="applyCandidate(row)">回测</el-button>
                <el-button link type="success" :icon="Connection" @click="addCandidateToCompare(row)">对比</el-button>
                <el-button link type="warning" :icon="DocumentAdd" @click="createTrackerFromCandidate(row)">跟踪</el-button>
                <el-button link :icon="CopyDocument" @click="copyCandidateParams(row)">复制</el-button>
                <el-button link :icon="Edit" @click="openEditCandidate(row)">编辑</el-button>
                <el-button link :type="row.favorite ? 'warning' : 'info'" :icon="row.favorite ? StarFilled : Star" @click="toggleCandidateFavorite(row)" />
                <el-button link type="info" :icon="Operation" @click="archiveCandidate(row)">归档</el-button>
                <el-button link type="danger" :icon="Delete" @click="deleteCandidate(row)" />
              </template>
            </el-table-column>
          </el-table>
        </section>

        <section class="table-band">
          <div class="section-title">
            <span>ETF 候选池</span>
            <small>默认池 + 你的覆盖项；未显式传 universe 时使用 active 且排除现金观察组</small>
          </div>
          <el-form :model="etfDraft" inline label-width="64px" class="etf-editor">
            <el-form-item label="代码">
              <el-input v-model="etfDraft.code" placeholder="159915" class="small-control" />
            </el-form-item>
            <el-form-item label="名称">
              <el-input v-model="etfDraft.name" placeholder="创业板 ETF" />
            </el-form-item>
            <el-form-item label="分组">
              <el-select v-model="etfDraft.group" class="small-control">
                <el-option v-for="item in etfGroupOptions" :key="item" :label="universeGroupLabel(item)" :value="item" />
              </el-select>
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="DocumentAdd" @click="saveETFItem">保存</el-button>
              <el-button :icon="Refresh" @click="refreshETFBasic">刷新基础信息</el-button>
            </el-form-item>
          </el-form>
          <el-table :data="etfUniverse" size="small" height="270">
            <el-table-column label="ETF" min-width="180">
              <template #default="{ row }">
                <strong>{{ row.code }}</strong>
                <span class="muted-cell">{{ row.name }}</span>
              </template>
            </el-table-column>
            <el-table-column label="分组" width="100">
              <template #default="{ row }">{{ universeGroupLabel(row.group) }}</template>
            </el-table-column>
            <el-table-column label="来源" width="110">
              <template #default="{ row }">{{ row.is_default ? '内置' : row.source || 'manual' }}</template>
            </el-table-column>
            <el-table-column label="备注" min-width="160">
              <template #default="{ row }">{{ row.note || '-' }}</template>
            </el-table-column>
            <el-table-column label="启用" width="90" fixed="right">
              <template #default="{ row }">
                <el-switch :model-value="row.active !== false" @change="(value) => toggleETFActive(row, Boolean(value))" />
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>

      <el-tab-pane label="自动挖掘" name="mine">
        <section class="control-band">
          <el-form :model="mineForm" inline label-width="86px">
            <el-form-item label="模式">
              <el-radio-group v-model="mineForm.mode">
                <el-radio-button label="auto_robust">稳健自动</el-radio-button>
                <el-radio-button label="custom">自定义</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="mineForm.mode === 'custom'" label="模板">
              <el-select v-model="mineForm.templates" multiple collapse-tags class="wide-control">
                <el-option v-for="item in strategies" :key="item.id" :label="item.name" :value="item.id" />
              </el-select>
            </el-form-item>
            <el-form-item v-if="mineForm.mode === 'custom'" label="套件">
              <el-button-group class="template-actions">
                <el-button :icon="Operation" @click="selectMiningTemplates('priceTools')">新指标</el-button>
                <el-button :icon="TrendCharts" @click="selectMiningTemplates('core')">核心</el-button>
                <el-button :icon="Select" @click="selectMiningTemplates('all')">全量</el-button>
              </el-button-group>
            </el-form-item>
            <el-form-item label="日期">
              <el-date-picker v-model="mineDates" type="daterange" value-format="YYYY-MM-DD" start-placeholder="开始" end-placeholder="结束" />
            </el-form-item>
            <el-form-item v-if="mineForm.mode === 'custom'" label="方式">
              <el-radio-group v-model="mineForm.search_method">
                <el-radio-button label="random">随机</el-radio-button>
                <el-radio-button label="grid">网格</el-radio-button>
              </el-radio-group>
            </el-form-item>
            <el-form-item v-if="mineForm.mode === 'custom'" label="次数">
              <el-input-number v-model="mineForm.max_trials" :min="1" :max="300" />
            </el-form-item>
            <el-form-item>
              <el-button type="primary" :icon="Search" :loading="loading.mine" @click="startMining">
                {{ mineForm.mode === 'auto_robust' ? '稳健自动挖掘' : '开始挖掘' }}
              </el-button>
            </el-form-item>
          </el-form>
          <div v-if="mineForm.mode === 'auto_robust'" class="auto-mining-explain">
            <div v-for="item in autoMiningSteps" :key="item.title" class="auto-mining-step">
              <strong>{{ item.title }}</strong>
              <span>{{ item.text }}</span>
            </div>
          </div>
        </section>

        <section v-if="miningRun" class="mine-status">
          <el-progress :percentage="Number(miningRun.progress || 0)" :status="miningRun.status === 'failed' ? 'exception' : miningRun.status === 'completed' ? 'success' : undefined" />
          <span>{{ miningRun.status }} · {{ miningRun.message }}</span>
          <span v-if="walkForwardCount" class="muted">Walk-forward {{ walkForwardCount }} 段</span>
          <span v-if="miningRun.status === 'completed'" class="muted">通过 {{ miningRun.candidate_count || 0 }} / {{ miningRun.trial_count || 0 }}</span>
        </section>

        <section v-if="miningPolicyRows.length" class="table-band">
          <div class="section-title">
            <span>挖掘方法</span>
            <small>{{ miningRun?.policy?.profile?.name || miningModeLabel(miningRun?.mode) }}</small>
          </div>
          <div class="mining-policy-grid">
            <div v-for="item in miningPolicyRows" :key="item.label" class="policy-metric">
              <span>{{ item.label }}</span>
              <strong>{{ item.value }}</strong>
            </div>
          </div>
        </section>

        <section v-if="miningTrials.length" class="result-grid mining-results-grid">
          <div class="chart-panel">
            <div class="section-title">
              <span>参数热力图</span>
              <small>颜色越深代表综合分越高</small>
            </div>
            <v-chart class="heatmap-chart" :option="heatmapOption" autoresize />
          </div>
          <div class="metric-panel mining-trials-panel">
            <div class="section-title">
              <span>候选试验</span>
              <small>展开行查看通过检查、淘汰原因和评分拆解</small>
            </div>
            <el-table :data="miningTrials.slice(0, 8)" class="trial-table" size="small" height="360" :fit="false">
              <el-table-column type="expand" width="42">
                <template #default="{ row }">
                  <div class="trial-explanation">
                    <div class="trial-explanation-head">
                      <strong>{{ trialDecisionLabel(row) }}</strong>
                      <span>{{ row.explanation?.method || '训练/验证/样本外 + walk-forward + 成本压力测试' }}</span>
                    </div>
                    <div class="trial-explain-grid">
                      <div>
                        <h4>通过检查</h4>
                        <el-tag v-for="item in explanationChecks(row, true)" :key="item.key" size="small" type="success" effect="plain">
                          {{ item.label }} {{ checkValueText(item) }}
                        </el-tag>
                        <span v-if="!explanationChecks(row, true).length" class="muted-cell">暂无</span>
                      </div>
                      <div>
                        <h4>淘汰原因</h4>
                        <el-tag v-for="item in explanationChecks(row, false)" :key="item.key" size="small" type="danger" effect="plain">
                          {{ item.label }} {{ checkValueText(item) }}
                        </el-tag>
                        <span v-if="!explanationChecks(row, false).length" class="muted-cell">全部通过</span>
                      </div>
                      <div>
                        <h4>评分正项</h4>
                        <span v-for="item in scoreComponentRows(row, 'positive')" :key="item.key" class="score-chip positive">
                          {{ item.label }} {{ num(item.value) }}
                        </span>
                      </div>
                      <div>
                        <h4>惩罚项</h4>
                        <span v-for="item in scoreComponentRows(row, 'penalty')" :key="item.key" class="score-chip penalty">
                          {{ item.label }} {{ num(item.value) }}
                        </span>
                      </div>
                    </div>
                  </div>
                </template>
              </el-table-column>
              <el-table-column prop="rank" label="#" width="48" />
              <el-table-column label="策略" width="180">
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
              <el-table-column label="结论" width="180">
                <template #default="{ row }">{{ topTrialReason(row) }}</template>
              </el-table-column>
              <el-table-column label="操作" width="168" fixed="right">
                <template #default="{ row }">
                  <div class="trial-actions">
                    <el-button link type="primary" :icon="Select" @click="applyTrial(row)">
                      {{ row.accepted ? '使用候选' : '试用参数' }}
                    </el-button>
                    <el-button link type="success" :icon="DocumentAdd" :loading="savingCandidate === trialKey(row)" @click="openSaveTrialDialog(row)">保存</el-button>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </div>
        </section>

        <section v-if="savedCandidates.length" class="table-band">
          <div class="section-title">
            <span>已保存候选参数</span>
            <small>应用后进入单策略表单，不覆盖默认参数</small>
          </div>
          <el-table :data="savedCandidates" size="small" height="260">
            <el-table-column label="策略" min-width="180">
              <template #default="{ row }">{{ strategyName(row.strategy_id) }}</template>
            </el-table-column>
            <el-table-column label="分数" width="90">
              <template #default="{ row }">{{ num(row.score) }}</template>
            </el-table-column>
            <el-table-column label="收益" width="90">
              <template #default="{ row }">{{ pct(row.metrics?.total_return) }}</template>
            </el-table-column>
            <el-table-column label="回撤" width="90">
              <template #default="{ row }">{{ pct(row.metrics?.max_drawdown) }}</template>
            </el-table-column>
            <el-table-column label="Calmar" width="90">
              <template #default="{ row }">{{ num(row.metrics?.calmar) }}</template>
            </el-table-column>
            <el-table-column label="操作" width="190" fixed="right">
              <template #default="{ row }">
                <el-button link type="primary" :icon="Select" @click="applyCandidate(row)">应用</el-button>
                <el-button link type="warning" :icon="Connection" @click="createTrackerFromCandidate(row)">加入模拟仓</el-button>
              </template>
            </el-table-column>
          </el-table>
        </section>
      </el-tab-pane>
        </el-tabs>
      </main>
    </div>

    <el-dialog v-model="saveCandidateDialog" title="保存候选参数" width="520px">
      <el-form label-width="72px">
        <el-form-item label="名称">
          <el-input v-model="candidateDraft.name" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="candidateDraft.tags" placeholder="逗号分隔，如 accepted, low_turnover" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="candidateDraft.note" type="textarea" :rows="3" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="saveCandidateDialog = false">取消</el-button>
        <el-button type="primary" :loading="!!savingCandidate" @click="saveTrial()">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="editCandidateDialog" title="编辑候选参数" width="520px">
      <el-form label-width="72px">
        <el-form-item label="名称">
          <el-input v-model="candidateEditDraft.name" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="candidateEditDraft.tags" placeholder="逗号分隔" />
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="candidateEditDraft.note" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="收藏">
          <el-switch v-model="candidateEditDraft.favorite" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editCandidateDialog = false">取消</el-button>
        <el-button type="primary" @click="updateCandidateDraft">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, onUnmounted, reactive, ref } from 'vue'
import dayjs from 'dayjs'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Connection, CopyDocument, Delete, DocumentAdd, Edit, Operation, Refresh, Search, Select, Star, StarFilled, TrendCharts } from '@element-plus/icons-vue'
import { use as echartsUse } from 'echarts/core'
import { LineChart, HeatmapChart } from 'echarts/charts'
import { GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import VChart from 'vue-echarts'
import type { EChartsOption } from 'echarts'
import { backtestApi, type BacktestResult, type BacktestSignalStability, type BacktestStrategy, type EntryOffsetStabilityResult, type ETFUniverseItem, type MiningCandidate, type MiningExplanationCheck, type MiningRun, type MiningTrial } from '@/api/backtest'
import { paperApi } from '@/api/paper'

echartsUse([LineChart, HeatmapChart, GridComponent, TooltipComponent, LegendComponent, DataZoomComponent, VisualMapComponent, CanvasRenderer])

const activeTab = ref('single')
const strategies = ref<BacktestStrategy[]>([])
const etfUniverse = ref<ETFUniverseItem[]>([])
const singleResult = ref<BacktestResult | null>(null)
const compareResults = ref<BacktestResult[]>([])
const stabilityResult = ref<EntryOffsetStabilityResult | null>(null)
const miningRun = ref<MiningRun | null>(null)
const savedCandidates = ref<MiningCandidate[]>([])
const miningTrials = computed<MiningTrial[]>(() => miningRun.value?.trials || [])
const walkForwardCount = computed(() => Array.isArray(miningRun.value?.split_plan?.walk_forward) ? miningRun.value.split_plan.walk_forward.length : 0)
const miningPolicyRows = computed(() => {
  const policy = miningRun.value?.policy
  if (!policy) return []
  const constraints = policy.constraints || {}
  return [
    { label: '模板池', value: String((policy.templates || []).length) },
    { label: '搜索方式', value: valueLabels[policy.search_method] || policy.search_method || '-' },
    { label: '试验上限', value: String(policy.max_trials ?? '-') },
    { label: 'Walk-forward', value: `${policy.walk_forward?.max_slices ?? 0} 段` },
    { label: '最大回撤', value: pct(constraints.max_drawdown) },
    { label: 'WF正收益', value: pct(constraints.min_walk_forward_positive_ratio) },
    { label: 'WF超额', value: pct(constraints.min_walk_forward_beat_benchmark_ratio) },
    { label: '最少交易', value: String(constraints.min_trades ?? '-') }
  ]
})
const loading = reactive({ single: false, compare: false, stability: false, mine: false, candidates: false })
const pollTimer = ref<number | null>(null)
const savingCandidate = ref<string | null>(null)
const saveCandidateDialog = ref(false)
const editCandidateDialog = ref(false)

const autoMiningSteps = [
  { title: '模板池', text: '排除 Fibonacci，优先动量、EMA、Price Action 与稳健自适应轮动。' },
  { title: '验证法', text: '使用训练/验证/样本外切分，并额外做多段 walk-forward。' },
  { title: '压力测试', text: '候选必须在 2 倍手续费和滑点下仍保持正收益。' },
  { title: '通过门槛', text: '约束样本外回撤、交易次数、WF 正收益占比和跑赢基准占比。' }
]

const defaultStart = dayjs().subtract(4, 'year').format('YYYY-MM-DD')
const defaultEnd = dayjs().format('YYYY-MM-DD')
const singleDates = ref<[string, string]>([defaultStart, defaultEnd])
const compareDates = ref<[string, string]>([defaultStart, defaultEnd])
const stabilityDates = ref<[string, string]>([defaultStart, defaultEnd])
const mineDates = ref<[string, string]>([defaultStart, defaultEnd])

const singleForm = reactive({
  strategy_id: 'biweekly_adaptive_stable_rotation',
  initial_cash: 1000000,
  commission_bps: 5,
  slippage_bps: 5,
  params: {} as Record<string, any>
})

interface ParamSourceState {
  kind: 'default' | 'mined' | 'manual'
  label: string
  detail: string
  baseLabel?: string
  accepted?: boolean
  trial?: MiningTrial
  candidate?: MiningCandidate
}

const paramSource = ref<ParamSourceState>({
  kind: 'default',
  label: '策略默认参数',
  detail: '来自策略目录的默认配置'
})

interface ConceptExplanation {
  term: string
  meaning: string
  role: string
}

const conceptExplanations: Record<string, ConceptExplanation[]> = {
  price_action_breakout_rotation: [
    {
      term: 'Price Action',
      meaning: '只看价格本身形成的结构，例如近期高点、低点是否抬高、突破和区间位置。',
      role: '本策略把它量化为接近或突破回看高点、低点抬高、短期动量为正。'
    },
    {
      term: '突破缓冲',
      meaning: '0.99 表示收盘价达到近期高点的 99% 就算接近突破，1.00 表示必须真正突破。',
      role: '数值越低越容易入场，信号更早但噪音也更高。'
    },
    {
      term: '低点抬高',
      meaning: '最近一段时间的最低价高于前一段最低价，代表价格结构没有继续走弱。',
      role: '开启后会过滤掉只有反弹、但底部结构还没改善的 ETF。'
    }
  ],
  fibonacci_retracement_rotation: [
    {
      term: 'Fibonacci 回撤',
      meaning: '从一段上涨的 swing low 到 swing high 计算 38.2%、50%、61.8% 等回撤区。',
      role: '当前回测稳定性偏弱，更适合作为观察信号，不建议单独作为主轮动策略。'
    },
    {
      term: 'Swing 高低点',
      meaning: '当前实现会在回看窗口里自动寻找先出现的低点和之后的高点，作为上涨段。',
      role: '回看窗口越长，识别的是越大的价格波段。'
    },
    {
      term: '反弹确认',
      meaning: '价格进入 Fibonacci 区间后，还要相对若干日前上涨，并站上趋势 EMA。',
      role: '它避免把仍在下跌中的回撤误判成买点。'
    }
  ]
}

const selectedStrategy = computed(() => strategies.value.find((item) => item.id === singleForm.strategy_id))
const selectedConceptExplanations = computed(() => conceptExplanations[singleForm.strategy_id] || [])
const primaryParamKeys = new Set(['top_k', 'rebalance_frequency'])
const editableParamFields = computed(() => (selectedStrategy.value?.parameter_schema || []).filter((item: any) => !primaryParamKeys.has(String(item.key))))
const strategyParamHint = computed(() => {
  if (!selectedStrategy.value) return ''
  const status = statusLabel(selectedStrategy.value.status)
  const family = familyLabel(selectedStrategy.value.family)
  return `${family} / ${status}`
})
const paramSourceKindLabel = computed(() => {
  if (paramSource.value.kind === 'default') return '默认参数'
  if (paramSource.value.kind === 'mined') return paramSource.value.accepted ? '挖掘候选' : '挖掘试验'
  return '手动修改'
})
const paramSourceTagType = computed(() => {
  if (paramSource.value.kind === 'default') return 'info'
  if (paramSource.value.kind === 'mined') return paramSource.value.accepted ? 'success' : 'warning'
  return 'warning'
})
const paramSourceStats = computed(() => {
  const trial = paramSource.value.kind === 'mined' ? paramSource.value.trial : null
  const candidate = paramSource.value.kind === 'mined' ? paramSource.value.candidate : null
  if (candidate) {
    return [
      { label: 'Score', value: num(candidate.score) },
      { label: '收益', value: pct(candidate.metrics?.total_return) },
      { label: '回撤', value: pct(candidate.metrics?.max_drawdown) },
      { label: 'Calmar', value: num(candidate.metrics?.calmar) }
    ]
  }
  if (!trial) return []
  return [
    { label: 'Rank', value: `#${trial.rank || trial.trial_index || '-'}` },
    { label: 'Score', value: num(trial.score) },
    { label: '样本外', value: pct(trial.test_metrics?.total_return) },
    { label: 'WF', value: `${pct(trial.walk_forward_summary?.positive_ratio)} / ${pct(trial.walk_forward_summary?.beat_benchmark_ratio)}` }
  ]
})
const compareCurrentParamLabel = computed(() => `${strategyName(singleForm.strategy_id)} · ${paramSourceKindLabel.value}`)
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
  strategyIds: ['industry_momentum_enhanced', 'ema_momentum_rotation', 'price_action_breakout_rotation', 'dual_momentum_core'],
  includeCurrentParams: false
})

const mineForm = reactive({
  mode: 'auto_robust',
  templates: ['ema_momentum_rotation', 'price_action_breakout_rotation'],
  search_method: 'random',
  max_trials: 120,
  seed: 7
})

const candidateFilters = reactive({
  strategy_id: '',
  status: 'active',
  keyword: '',
  favorite: false,
  sort_by: 'created'
})
const etfDraft = reactive({ code: '', name: '', group: 'sector' })
const etfGroupOptions = ['broad', 'sector', 'factor', 'commodity', 'cash_watch']
const candidateDraft = reactive({
  row: null as MiningTrial | null,
  name: '',
  tags: '',
  note: ''
})
const candidateEditDraft = reactive({
  candidate_id: '',
  name: '',
  tags: '',
  note: '',
  favorite: false
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
  await loadCandidates()
}

async function loadETFUniverse() {
  const res = await backtestApi.getETFUniverse()
  if (res.success) etfUniverse.value = res.data.items
}

async function loadCandidates() {
  try {
    loading.candidates = true
    const params: Record<string, any> = {
      limit: 100,
      status: candidateFilters.status,
      sort_by: candidateFilters.sort_by
    }
    if (candidateFilters.strategy_id) params.strategy_id = candidateFilters.strategy_id
    if (candidateFilters.keyword) params.keyword = candidateFilters.keyword
    if (candidateFilters.favorite) params.favorite = true
    const res = await backtestApi.listCandidates(params)
    if (res.success) savedCandidates.value = res.data.items
  } catch {
    savedCandidates.value = []
  } finally {
    loading.candidates = false
  }
}

function applyStrategyDefaults() {
  const defaults = selectedStrategy.value?.default_params || {}
  singleForm.params = {
    cash_entry_mode: 'daily_when_cash',
    cash_entry_confirmations: 2,
    min_days_to_rebalance_for_cash_entry: 2,
    ...defaults
  }
  setDefaultParamSource()
}

function setDefaultParamSource() {
  paramSource.value = {
    kind: 'default',
    label: `${strategyName(singleForm.strategy_id)} 默认参数`,
    detail: '来自策略目录的默认配置；切换策略时会自动载入。'
  }
}

function restoreDefaultParams() {
  applyStrategyDefaults()
  ElMessage.success('已恢复策略默认参数')
}

function markParamsEdited() {
  if (paramSource.value.kind === 'manual') return
  paramSource.value = {
    ...paramSource.value,
    kind: 'manual',
    label: '手动修改参数',
    detail: `基于${paramSourceKindLabel.value}调整；不会覆盖策略默认参数。`,
    baseLabel: paramSource.value.label,
    trial: undefined
  }
}

function selectMiningTemplates(mode: 'priceTools' | 'core' | 'all') {
  const ids = strategies.value.map((item) => item.id)
  const priceTools = ['ema_momentum_rotation', 'price_action_breakout_rotation'].filter((id) => ids.includes(id))
  const core = ['industry_momentum_enhanced', 'biweekly_adaptive_stable_rotation', 'dual_momentum_core', 'trend_following_equal_weight'].filter((id) => ids.includes(id))
  if (mode === 'all') {
    mineForm.templates = ids
    mineForm.max_trials = Math.max(mineForm.max_trials, 120)
    return
  }
  mineForm.templates = mode === 'core' ? core : priceTools
  mineForm.max_trials = Math.max(mineForm.max_trials, mode === 'core' ? 60 : 60)
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
    const requests = compareForm.strategyIds.map((id) => ({ strategy_id: id, label: `${strategyName(id)} · 默认`, params: {} }))
    if (compareForm.includeCurrentParams) {
      requests.push({
        strategy_id: singleForm.strategy_id,
        label: compareCurrentParamLabel.value,
        params: { ...singleForm.params }
      })
    }
    const res = await backtestApi.compare({
      ...basePayload(compareDates.value),
      strategies: requests
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
      mode: mineForm.mode,
      templates: mineForm.templates,
      search_method: mineForm.search_method,
      max_trials: mineForm.mode === 'auto_robust' ? Math.max(mineForm.max_trials, 120) : mineForm.max_trials,
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
  paramSource.value = {
    kind: 'mined',
    label: `${strategyName(row.strategy_id)} #${row.rank || row.trial_index || '-'}`,
    detail: row.accepted ? '来自自动挖掘并通过稳健门槛；可直接运行单策略回测。' : `来自挖掘试验但未通过：${topTrialReason(row)}。`,
    accepted: row.accepted,
    trial: row
  }
  compareForm.includeCurrentParams = true
  activeTab.value = 'single'
  ElMessage.success(row.accepted ? '已应用挖掘候选参数' : '已试用挖掘试验参数')
}

async function applyCandidate(row: MiningCandidate) {
  let candidate = row
  let params = row.params || {}
  try {
    const res = await backtestApi.applyCandidate(row.candidate_id)
    if (res.success) {
      candidate = res.data.candidate
      params = res.data.params || candidate.params || {}
      await loadCandidates()
    }
  } catch (error: any) {
    ElMessage.warning(apiErrorMessage(error, '候选应用计数失败，已使用本地参数'))
  }
  singleForm.strategy_id = candidate.strategy_id
  singleForm.params = { ...params }
  paramSource.value = {
    kind: 'mined',
    label: candidate.name || `${strategyName(candidate.strategy_id)} 已保存候选`,
    detail: '来自候选策略库；可直接运行回测或纳入策略对比。',
    accepted: true,
    candidate
  }
  compareForm.includeCurrentParams = true
  activeTab.value = 'single'
  ElMessage.success('已应用已保存候选参数')
}

async function addCandidateToCompare(row: MiningCandidate) {
  await applyCandidate(row)
  if (!compareForm.strategyIds.includes(row.strategy_id)) compareForm.strategyIds.push(row.strategy_id)
  compareForm.includeCurrentParams = true
  activeTab.value = 'compare'
}

async function saveDiscoveredAdaptiveTopK() {
  try {
    loading.candidates = true
    const res = await backtestApi.saveDiscoveredAdaptiveTopK({
      universe: rotationUniverse.value.map((item) => item.code),
      favorite: true
    })
    if (res.success) {
      await loadCandidates()
      await applyCandidate(res.data)
      ElMessage.success('已保存混合 Top2 参数，可直接加入模拟仓')
    }
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '保存混合参数失败'))
  } finally {
    loading.candidates = false
  }
}

async function createTrackerFromCurrentParams() {
  try {
    const res = await paperApi.createStrategyTracker({
      name: `${strategyName(singleForm.strategy_id)} · ${paramSourceKindLabel.value}`,
      strategy_id: singleForm.strategy_id,
      params: { ...singleForm.params },
      universe: rotationUniverse.value.map((item) => item.code),
      tracking_start_date: dayjs().format('YYYY-MM-DD'),
      open_policy: 'next_signal',
      initial_cash: singleForm.initial_cash || 1000000,
      commission_bps: singleForm.commission_bps || 5,
      slippage_bps: singleForm.slippage_bps || 5,
      adjust: 'qfq'
    })
    if (res.success) ElMessage.success('已加入模拟仓，可在“模拟交易 / 策略跟踪”查看')
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '加入模拟仓失败'))
  }
}

async function createTrackerFromCandidate(row: MiningCandidate) {
  try {
    const candidate = row
    const res = await backtestApi.createPaperTrackerFromCandidate(row.candidate_id, {
      name: candidate.name || `${strategyName(candidate.strategy_id)} 参数跟踪`,
      tracking_start_date: dayjs().format('YYYY-MM-DD'),
      open_policy: 'next_signal',
      initial_cash: 1000000,
      commission_bps: 5,
      slippage_bps: 5,
      adjust: 'qfq'
    })
    if (res.success) {
      ElMessage.success('已加入模拟仓，可在“模拟交易 / 策略跟踪”查看')
      await loadCandidates()
    }
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '加入模拟仓失败'))
  }
}

async function copyCandidateParams(row: MiningCandidate) {
  try {
    await navigator.clipboard.writeText(JSON.stringify(row.params || {}, null, 2))
    ElMessage.success('参数 JSON 已复制')
  } catch {
    ElMessage.error('复制失败')
  }
}

function openEditCandidate(row: MiningCandidate) {
  candidateEditDraft.candidate_id = row.candidate_id
  candidateEditDraft.name = row.name || strategyName(row.strategy_id)
  candidateEditDraft.tags = candidateTags(row).join(', ')
  candidateEditDraft.note = row.note || ''
  candidateEditDraft.favorite = !!row.favorite
  editCandidateDialog.value = true
}

async function updateCandidateDraft() {
  try {
    await backtestApi.updateCandidate(candidateEditDraft.candidate_id, {
      name: candidateEditDraft.name,
      tags: splitTags(candidateEditDraft.tags),
      note: candidateEditDraft.note,
      favorite: candidateEditDraft.favorite
    })
    editCandidateDialog.value = false
    await loadCandidates()
    ElMessage.success('候选参数已更新')
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '更新候选参数失败'))
  }
}

async function toggleCandidateFavorite(row: MiningCandidate) {
  try {
    await backtestApi.updateCandidate(row.candidate_id, { favorite: !row.favorite })
    await loadCandidates()
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '更新收藏失败'))
  }
}

async function archiveCandidate(row: MiningCandidate) {
  try {
    await backtestApi.updateCandidate(row.candidate_id, { status: 'archived' })
    await loadCandidates()
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '归档失败'))
  }
}

async function deleteCandidate(row: MiningCandidate) {
  try {
    await ElMessageBox.confirm(`确认删除 ${row.name || strategyName(row.strategy_id)}？`, '删除候选参数', { type: 'warning' })
    await backtestApi.deleteCandidate(row.candidate_id)
    await loadCandidates()
    ElMessage.success('已删除候选参数')
  } catch (error: any) {
    if (error !== 'cancel') ElMessage.error(apiErrorMessage(error, '删除失败'))
  }
}

async function saveETFItem() {
  try {
    if (!etfDraft.code.trim()) {
      ElMessage.warning('请填写 ETF 代码')
      return
    }
    const res = await backtestApi.saveETFUniverseItem({
      code: etfDraft.code,
      name: etfDraft.name || etfDraft.code,
      group: etfDraft.group,
      active: true,
      source: 'manual'
    })
    if (res.success) {
      etfDraft.code = ''
      etfDraft.name = ''
      etfDraft.group = 'sector'
      await loadETFUniverse()
      ElMessage.success('已保存 ETF 候选项')
    }
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '保存 ETF 失败'))
  }
}

async function toggleETFActive(row: ETFUniverseItem, active: boolean) {
  try {
    await backtestApi.updateETFUniverseItem(row.code, { active })
    await loadETFUniverse()
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '更新 ETF 状态失败'))
  }
}

async function refreshETFBasic() {
  try {
    const res = await backtestApi.refreshETFBasic('akshare')
    if (res.success) ElMessage.success(`ETF 基础信息已刷新 ${res.data.saved} 条`)
    await loadETFUniverse()
  } catch (error: any) {
    ElMessage.error(apiErrorMessage(error, '刷新 ETF 基础信息失败'))
  }
}

function openSaveTrialDialog(row: MiningTrial) {
  candidateDraft.row = row
  candidateDraft.name = `${strategyName(row.strategy_id)} #${row.rank || row.trial_index || row.strategy_id}`
  candidateDraft.tags = row.accepted ? 'accepted' : 'trial'
  candidateDraft.note = topTrialReason(row)
  saveCandidateDialog.value = true
}

async function saveTrial(row?: MiningTrial | null) {
  const trial = row || candidateDraft.row
  if (!trial) return
  try {
    const key = trialKey(trial)
    savingCandidate.value = key
    const res = await backtestApi.saveCandidate({
      name: candidateDraft.name || `${strategyName(trial.strategy_id)} #${trial.rank || trial.strategy_id}`,
      strategy_id: trial.strategy_id,
      params: trial.params,
      run_id: miningRun.value?.run_id,
      trial_index: trial.trial_index || trial.rank,
      score: trial.score,
      metrics: trial.test_metrics,
      tags: splitTags(candidateDraft.tags),
      note: candidateDraft.note,
      source: 'mining',
      evaluation: {
        train_metrics: trial.train_metrics,
        validation_metrics: trial.validation_metrics,
        test_metrics: trial.test_metrics,
        stress_2x_metrics: trial.stress_2x_metrics,
        walk_forward_summary: trial.walk_forward_summary || {},
        walk_forward_slices: trial.walk_forward_slices || [],
        reasons: trial.reasons || [],
        explanation: trial.explanation || {}
      }
    })
    if (res.success) {
      ElMessage.success('已保存候选策略配置')
      saveCandidateDialog.value = false
      await loadCandidates()
    }
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

function etfName(code: string) {
  return etfUniverse.value.find((item) => item.code === code)?.name || code
}

function splitTags(value: string | string[] | undefined) {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean)
  return String(value || '')
    .split(/[,，\s]+/)
    .map((item) => item.trim())
    .filter(Boolean)
}

function candidateTags(row: MiningCandidate) {
  return splitTags(row.tags || [])
}

function candidateUniverseText(row: MiningCandidate) {
  const universe = row.universe || []
  if (!universe.length) return '默认 active 池'
  return `${universe.length} 只 ETF`
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
  random: '随机',
  grid: '网格',
  auto_robust: '稳健自动',
  custom: '自定义',
  ret_gt_0: '收益率大于 0',
  score_gt_0: '综合分大于 0',
  trend_filter: '趋势过滤',
  daily_when_cash: '空仓时每日扫描',
  cash_confirmed_scan: '空仓确认入场',
  rebalance_only: '仅调仓日扫描',
  true: '是',
  false: '否'
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
  fast_ema: '快 EMA',
  slow_ema: '慢 EMA',
  trend_ema: '趋势 EMA',
  trend_weight: '趋势权重',
  vol_window: '波动窗口',
  vol_penalty: '波动惩罚',
  adaptive_top_k: 'Top K 自适应',
  top_k_score_gap: 'Top1/2 分差阈值',
  min_momentum: '最小动量',
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
  higher_low_window: '低点窗口',
  require_higher_low: '要求低点抬高',
  breakout_weight: '突破权重',
  range_weight: '区间权重',
  fib_low: '回撤下沿',
  fib_high: '回撤上沿',
  zone_tolerance: '区间容忍',
  bounce_days: '反弹确认日',
  bounce_threshold: '反弹阈值',
  min_leg_return: '最小上升段',
  bounce_weight: '反弹权重',
  fib_distance_penalty: '偏离惩罚',
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
  defensive_ma: '防守均线',
  min_holding_days: '最短持有交易日',
  rank_switch_buffer: '排名缓冲',
  rebalance_turnover_threshold: '小换仓过滤'
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
    regime_downtrend_cash: '下跌状态空仓',
    ema_selected: 'EMA 趋势确认',
    ema_no_asset: 'EMA 无合格标的',
    price_action_breakout: '价格突破确认',
    price_action_no_breakout: '无价格突破',
    fibonacci_retracement: 'Fibonacci 回撤反弹',
    fibonacci_no_retracement: '无回撤反弹'
  }
  return labels[value || ''] || value || '-'
}

const failureReasonLabels: Record<string, string> = {
  test_return_not_positive: '样本外收益不为正',
  test_excess_not_positive: '样本外未跑赢基准',
  drawdown_too_high: '样本外回撤过高',
  too_few_trades: '交易次数不足',
  performance_too_concentrated: '收益集中在少数切分',
  failed_2x_cost_stress: '2 倍成本压力测试未过',
  validation_return_below_threshold: '验证集收益未达标',
  test_calmar_below_threshold: '样本外 Calmar 未达标',
  calmar_gap_too_large: '验证/样本外差距过大',
  walk_forward_too_few_slices: 'walk-forward 样本不足',
  walk_forward_return_unstable: 'walk-forward 正收益占比不足',
  walk_forward_excess_unstable: 'walk-forward 超额占比不足'
}

const scoreComponentLabels: Record<string, string> = {
  test_calmar: '样本外Calmar',
  validation_calmar: '验证Calmar',
  test_excess_return: '样本外超额',
  validation_excess_return: '验证超额',
  stress_return: '压力测试',
  walk_forward: 'WF稳定',
  drawdown: '回撤',
  turnover: '换手',
  calmar_gap: 'Calmar差距',
  walk_forward_instability: 'WF波动'
}

function miningModeLabel(value?: string) {
  return valueLabels[value || ''] || value || '-'
}

function explanationChecks(row: MiningTrial, passed: boolean): MiningExplanationCheck[] {
  const checks = passed ? row.explanation?.passed_checks : row.explanation?.failed_checks
  return Array.isArray(checks) ? checks : []
}

function checkValueText(item: MiningExplanationCheck) {
  return `(${formatCheckValue(item.value, item.key)} / ${item.threshold})`
}

function formatCheckValue(value: number | string, key: string) {
  if (typeof value !== 'number') return String(value)
  if (key.includes('return') || key.includes('ratio') || key.includes('drawdown')) return pct(value)
  if (Number.isInteger(value)) return String(value)
  return num(value)
}

function scoreComponentRows(row: MiningTrial, type: 'positive' | 'penalty') {
  const source = row.explanation?.score_components?.[type] || {}
  return Object.entries(source).map(([key, value]) => ({
    key,
    label: scoreComponentLabels[key] || key,
    value: Number(value)
  }))
}

function topTrialReason(row: MiningTrial) {
  if (row.accepted) return '通过稳健门槛'
  const failed = row.explanation?.failed_checks?.[0]
  if (failed?.label) return failed.label
  const code = row.reasons?.[0]
  return failureReasonLabels[code || ''] || code || '-'
}

function trialDecisionLabel(row: MiningTrial) {
  return row.accepted ? '已通过：可保存为候选' : `未通过：${topTrialReason(row)}`
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
  if (typeof value === 'boolean') return value ? '是' : '否'
  if (Array.isArray(value)) return value.map((item) => valueLabels[String(item)] || String(item)).join(', ')
  return valueLabels[String(value)] || String(value)
}

function paramStep(field: any) {
  if (field.step !== undefined) return Number(field.step)
  const value = singleForm.params[field.key]
  if (typeof value === 'number' && Math.abs(value) < 1) return 0.01
  return 1
}

function paramPrecision(field: any) {
  const step = String(paramStep(field))
  return step.includes('.') ? step.split('.')[1].length : 0
}

function listParamValue(key: string) {
  const value = singleForm.params[key]
  return Array.isArray(value) ? value.join(', ') : String(value ?? '')
}

function updateListParam(key: string, value: string | number) {
  const text = String(value || '')
  singleForm.params[key] = text
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => {
      if (key.includes('codes')) return item.padStart(6, '0')
      const numberValue = Number(item)
      return Number.isFinite(numberValue) ? numberValue : item
    })
  markParamsEdited()
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

function stabilityLabel(stability?: BacktestSignalStability) {
  if (!stability || !Object.keys(stability).length) return '-'
  const parts: string[] = []
  const kept = Array.isArray(stability.kept) ? stability.kept : []
  if (kept.length) parts.push(`保留 ${kept.join(', ')}`)
  if (stability.skipped_by_turnover) parts.push(`小换仓 ${pct(stability.turnover)}`)
  return parts.join(' | ') || `换手 ${pct(stability.turnover)}`
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

const returnAttributionRows = computed(() => {
  const rows = singleResult.value?.diagnostics?.return_attribution || []
  return rows.map((item) => ({
    ...item,
    name: item.name || etfName(item.code)
  }))
})

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

function heatmapXParam(item: MiningTrial) {
  if (item.strategy_id === 'fibonacci_retracement_rotation') return item.params.lookback
  return item.params.momentum_window || item.params.lookback || item.params.fast_ema || '-'
}

function heatmapYParam(item: MiningTrial) {
  if (item.strategy_id === 'ema_momentum_rotation') return item.params.slow_ema
  if (item.strategy_id === 'fibonacci_retracement_rotation') return item.params.trend_ema || item.params.fib_high
  return item.params.trend_ma || item.params.slow_ma || item.params.lookback || item.params.higher_low_window || '-'
}

const heatmapOption = computed<EChartsOption>(() => {
  const trials = miningTrials.value
  const xs = Array.from(new Set(trials.map((item) => String(heatmapXParam(item)))))
  const ys = Array.from(new Set(trials.map((item) => String(heatmapYParam(item)))))
  const data = trials.map((item) => [
    xs.indexOf(String(heatmapXParam(item))),
    ys.indexOf(String(heatmapYParam(item))),
    Number(item.score || 0)
  ])
  return {
    tooltip: { position: 'top' },
    grid: { left: 64, right: 24, top: 24, bottom: 48 },
    xAxis: { type: 'category', data: xs, name: '窗口' },
    yAxis: { type: 'category', data: ys, name: '过滤' },
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

.concept-explain-list {
  display: grid;
  gap: 8px;
  margin-top: 12px;
}

.concept-explain-item {
  border-left: 3px solid var(--el-color-primary-light-5);
  background: var(--el-fill-color-lighter);
  padding: 8px 10px;

  strong {
    display: block;
    color: var(--el-text-color-primary);
    font-size: 13px;
  }

  p {
    margin: 4px 0;
    color: var(--el-text-color-regular);
    font-size: 12px;
    line-height: 1.45;
  }

  small {
    display: block;
    color: var(--el-text-color-secondary);
    font-size: 12px;
    line-height: 1.4;
  }
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
.param-panel,
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

.small-control {
  width: 120px;
}

.etf-editor {
  margin-bottom: 10px;
}

.table-band .el-tag + .el-tag {
  margin-left: 4px;
}

.template-actions {
  display: inline-flex;
}

.param-source-bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  border-top: 1px solid var(--el-border-color-lighter);
  margin-top: 8px;
  padding-top: 10px;
}

.param-source-main {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;

  strong {
    flex: 0 0 auto;
    font-size: 13px;
  }

  span:last-child {
    min-width: 0;
    overflow: hidden;
    color: var(--el-text-color-secondary);
    font-size: 12px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.param-source-stats {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  min-width: 180px;

  span {
    border-radius: 999px;
    background: var(--el-fill-color-light);
    padding: 2px 8px;
    color: var(--el-text-color-regular);
    font-size: 12px;
    white-space: nowrap;
  }
}

.inline-hint {
  margin-left: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.param-editor-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 10px 12px;
}

.param-editor-item {
  display: grid;
  grid-template-rows: auto 32px;
  gap: 4px;
  min-width: 0;

  label {
    overflow: hidden;
    color: var(--el-text-color-secondary);
    font-size: 12px;
    line-height: 18px;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
}

.param-control {
  width: 100%;
}

.param-switch {
  align-self: center;
}

.section-title {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 10px;
  font-weight: 650;

  small {
    color: var(--el-text-color-secondary);
    font-weight: 400;
  }
}

.muted-cell {
  display: block;
  margin-top: 2px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.result-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 280px;
  gap: 12px;
}

.mining-results-grid {
  grid-template-columns: 1fr;

  .chart-panel,
  .metric-panel {
    min-width: 0;
  }

  .section-title {
    margin-bottom: 8px;
  }
}

.equity-chart {
  height: 360px;
}

.heatmap-chart {
  height: 320px;
}

.mining-results-grid .heatmap-chart {
  height: 300px;
}

.mining-trials-panel {
  overflow: hidden;
}

.trial-table {
  width: 100%;

  :deep(.el-table__cell) {
    vertical-align: middle;
  }
}

.trial-actions {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  white-space: nowrap;

  .el-button {
    margin-left: 0;
  }
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

.auto-mining-explain,
.mining-policy-grid,
.trial-explain-grid {
  display: grid;
  gap: 10px;
}

.auto-mining-explain {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  margin-top: 10px;
}

.auto-mining-step,
.policy-metric {
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 6px;
  background: var(--el-fill-color-lighter);
  padding: 8px 10px;
}

.auto-mining-step {
  display: grid;
  gap: 4px;

  strong {
    color: var(--el-text-color-primary);
    font-size: 13px;
  }

  span {
    color: var(--el-text-color-secondary);
    font-size: 12px;
    line-height: 1.4;
  }
}

.mining-policy-grid {
  grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
}

.policy-metric {
  display: grid;
  gap: 4px;

  span {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }

  strong {
    font-size: 14px;
  }
}

.trial-explanation {
  display: grid;
  gap: 10px;
  padding: 4px 8px 10px;
}

.trial-explanation-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;

  strong {
    font-size: 13px;
  }

  span {
    color: var(--el-text-color-secondary);
    font-size: 12px;
  }
}

.trial-explain-grid {
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));

  h4 {
    margin: 0 0 6px;
    font-size: 12px;
    font-weight: 650;
  }

  .el-tag {
    margin: 0 6px 6px 0;
  }
}

.score-chip {
  display: inline-block;
  border-radius: 999px;
  margin: 0 6px 6px 0;
  padding: 2px 8px;
  font-size: 12px;

  &.positive {
    background: var(--el-color-success-light-9);
    color: var(--el-color-success);
  }

  &.penalty {
    background: var(--el-color-warning-light-9);
    color: var(--el-color-warning-dark-2);
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

  .param-source-bar,
  .param-source-main {
    align-items: flex-start;
    flex-direction: column;
  }

  .param-source-stats {
    justify-content: flex-start;
  }

  .wide-control {
    width: 100%;
  }
}
</style>
