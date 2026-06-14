# ETF 回测实验室阶段说明

## 当前范围

本阶段新增了一套轻量 ETF 回测与策略研究能力，面向研究和筛选，不作为实盘收益承诺。

- 后端接口：单策略回测、策略对比、自动挖掘、入场偏移稳定性实验。
- 数据层：ETF 基本信息、日线行情、复权因子缓存到 MongoDB。
- 策略层：策略实现和策略元数据分离，策略说明、默认参数、参数 schema 放在 `strategy_catalog.py`。
- 前端：回测实验室页面包含策略选择侧边栏、单策略、策略对比、入场稳定性、自动挖掘。

## 核心文件

- `app/services/backtest/engine.py`：纯回测引擎和策略信号实现。
- `app/services/backtest/strategy_catalog.py`：策略目录、中文描述、默认参数和参数 schema。
- `app/services/backtest/backtest_service.py`：数据获取、回测编排、稳定性实验。
- `app/services/backtest/etf_data_service.py`：ETF 数据缓存、Tushare/AKShare 降级、复权因子验证。
- `app/services/backtest/mining_service.py`：模板化参数搜索和候选策略保存。
- `app/routers/backtest.py`：回测 API。
- `frontend/src/views/Backtest/Lab.vue`：前端实验室页面。
- `scripts/cache_etf_history.py`：慢速缓存 ETF 日线和复权因子的辅助脚本。

## 默认行业动量策略

当前默认的“行业 ETF 增强动量轮动”不是均线策略，而是多窗口动量打分：

```text
score = 40日收益 * 0.3 + 120日收益 * 0.5 + 250日收益 * 0.2 - 60日波动率惩罚
```

默认入场过滤已改为趋势确认：

- 价格站上 120 日均线。
- 20 日均线高于 120 日均线。
- 60 日绝对动量为正。
- 月度调仓，默认 Top K = 1。

`score_gt_0` 仍保留为可选研究参数，但不再作为默认空仓规则。

## 数据口径

- 默认使用 `qfq` 前复权价格。
- 有 Tushare token 时优先使用 Tushare `fund_daily + fund_adj` 计算复权行情。
- Tushare 不可用时降级到 AKShare 东方财富 ETF 历史行情。
- `qfq` 不再降级使用未复权 Sina 数据。
- 复权因子可通过脚本缓存并用 `none * factor ~= qfq` 验证。

## 风险控制和实验

- 无合格标的统一空仓。
- 空仓后可每日扫描，但默认要求连续确认，并且距离下次调仓日大于指定交易日才入场。
- 入场偏移稳定性实验用于检查建仓日期敏感性。
- 自动挖掘为模板化参数搜索，会保存所有 trial，并按样本外、成本压力和交易数等规则筛选。

## 已知限制

- 510300 只是默认基准，后续应增加多基准展示：510300、选股池等权、最佳/最差 ETF、现金。
- 周频策略对手续费和滑点敏感，当前高换手实验策略不宜直接看裸收益。
- 缠论和 RSRS 仍是简化模板，需要继续验证信号定义和交易约束。
- 前端回测页面已经可用，但后续可以继续拆分成更小组件。

## 验证方式

当前阶段常用验证：

```powershell
.\.venv\Scripts\python.exe -m compileall app\routers\backtest.py app\services\backtest tests\backtest\test_backtest_engine.py
npm.cmd run type-check
git diff --check
```

如果沙箱内 NumPy/Pandas DLL 被拒绝访问，需要在非沙箱环境执行测试文件中的 `test_` 函数。
