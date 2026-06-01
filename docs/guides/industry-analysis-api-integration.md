# 行业/概念分析 API 集成说明

这份文档配合 `examples/industry_analysis_api_client.py` 使用，面向：

1. AI Agent / 飞书机器人
2. 飞书服务端 / 自动化工作流
3. 定时任务 / 批量分析

目标是完整覆盖 **行业分析** 的所有 API 能力，支持两种使用模式：
- **同步模式**（推荐飞书）：一次调用，等待返回结果
- **异步模式**：提交 → 轮询 → 获取结果

---

## 结论

推荐链路（飞书/Bot）：

```
POST /api/industry-analysis/run  ← 同步模式，一次调用返回结果
```

如需异步：

```
POST /api/industry-analysis/submit  → task_id
GET  /api/industry-analysis/result/{task_id}  (轮询)
GET  /api/industry-analysis/{task_id}/download?format=markdown
```

---

## 现成脚本

```bash
python examples/industry_analysis_api_client.py --help
```

支持命令：
- `login` - 登录获取 token
- `run` - **同步模式：提交并等待结果**（推荐飞书使用）
- `submit` - 异步提交
- `status` - 查询状态
- `wait` - 等待完成
- `result` - 获取结果
- `download` - 下载报告
- `history` - 查看历史
- `delete` - 删除记录

---

## API 端点一览

| 方法 | 路径 | 说明 | 适用场景 |
|------|------|------|----------|
| POST | `/api/industry-analysis/run` | 同步执行（阻塞等待结果） | 飞书Bot/服务端 |
| POST | `/api/industry-analysis/submit` | 异步提交 | 前端/需要进度展示 |
| GET | `/api/industry-analysis/result/{task_id}` | 查询状态和结果 | 轮询 |
| GET | `/api/industry-analysis/history?limit=20` | 分析历史 | 历史查询 |
| DELETE | `/api/industry-analysis/{task_id}` | 删除任务 | 清理 |
| GET | `/api/industry-analysis/{task_id}/download?format=markdown` | 下载报告 | 生成文件 |

---

## 请求参数

```json
{
  "concept": "AI相关",
  "detail_level": "detailed",
  "top_n": 5,
  "market": "A"
}
```

| 字段 | 类型 | 必填 | 默认值 | 说明 |
|------|------|------|--------|------|
| concept | string | ✅ | - | 行业/概念关键词（支持模糊概念） |
| detail_level | string | - | "detailed" | 分析粒度：`brief` 或 `detailed` |
| top_n | int | - | 5 | 推荐股票数量（1-10） |
| market | string | - | "A" | 市场：`A` |

### concept 支持的概念类型

- 标准行业：`银行`、`半导体`、`医药生物`
- 模糊概念：`AI相关`、`高股息`、`新能源`
- 投资主题：`国产替代`、`数字经济`、`一带一路`
- 风格策略：`低估值蓝筹`、`小盘成长`

---

## 同步模式（推荐飞书使用）

### 请求

```http
POST /api/industry-analysis/run
Authorization: Bearer <token>
Content-Type: application/json

{
  "concept": "AI相关",
  "detail_level": "detailed",
  "top_n": 5
}
```

### 响应（成功）

```json
{
  "success": true,
  "data": {
    "task_id": "abc-123",
    "concept": "AI相关",
    "status": "completed",
    "result": {
      "concept": "AI相关",
      "mapped_boards": ["人工智能", "大数据", "软件开发"],
      "candidate_count": 45,
      "filtered_count": 25,
      "due_diligence_report": "# AI行业尽调报告\n...(完整Markdown)",
      "stock_selection_report": "# AI概念选股报告\n...(完整Markdown)",
      "recommendations": [
        {
          "rank": 1,
          "code": "002230",
          "name": "科大讯飞",
          "score": 88,
          "summary": "AI语音龙头，技术壁垒深厚",
          "industry": "软件开发",
          "recommendation_logic": "...",
          "main_advantages": "...",
          "main_risks": "...",
          "suitable_style": "成长型"
        }
      ],
      "market_overview": "...",
      "selection_reasoning": "...",
      "risk_warning": "...",
      "exclusion_reasons": "...",
      "portfolio_advice": "...",
      "tracking_indicators": "...",
      "conclusion": "...",
      "analysis_time": 156.32,
      "llm_calls": 3,
      "data_date": "2025-01-15"
    }
  },
  "message": "行业分析完成"
}
```

### 响应（失败）

```json
{
  "success": false,
  "data": {
    "task_id": "abc-123",
    "status": "failed",
    "error": "错误描述"
  },
  "message": "错误描述"
}
```

---

## 异步模式

### 1. 提交任务

```http
POST /api/industry-analysis/submit
Authorization: Bearer <token>
Content-Type: application/json

{
  "concept": "高股息",
  "top_n": 5
}
```

响应：

```json
{
  "success": true,
  "data": {
    "task_id": "xxx-yyy-zzz",
    "status": "pending",
    "concept": "高股息"
  }
}
```

### 2. 轮询状态

```http
GET /api/industry-analysis/result/{task_id}
Authorization: Bearer <token>
```

响应（进行中）：

```json
{
  "success": true,
  "data": {
    "task_id": "xxx-yyy-zzz",
    "status": "running",
    "progress": 45,
    "progress_message": "正在生成行业尽调报告（深度研究）"
  }
}
```

### 3. 下载报告

```http
GET /api/industry-analysis/{task_id}/download?format=markdown
Authorization: Bearer <token>
```

支持格式：`markdown`、`json`、`pdf`

---

## 结果数据结构

### recommendations 数组（Top N 推荐股）

| 字段 | 类型 | 说明 |
|------|------|------|
| rank | int | 排名 |
| code | string | 6位股票代码 |
| name | string | 股票名称 |
| score | float | 综合评分（0-100） |
| summary | string | 推荐理由摘要 |
| industry | string | 所属行业 |
| recommendation_logic | string | 推荐逻辑 |
| main_advantages | string | 主要优势 |
| main_risks | string | 主要风险 |
| suitable_style | string | 适合的投资风格 |
| score_breakdown | dict | 评分明细 |

### 报告字段

| 字段 | 说明 |
|------|------|
| due_diligence_report | 行业尽调报告（完整Markdown） |
| stock_selection_report | 选股推荐报告（完整Markdown） |
| market_overview | 市场概况 |
| selection_reasoning | 选股逻辑 |
| risk_warning | 风险提示 |
| exclusion_reasons | 排除原因 |
| portfolio_advice | 组合建议 |
| tracking_indicators | 跟踪指标 |
| conclusion | 结论 |

---

## 认证

所有接口需要 Bearer Token：

```http
Authorization: Bearer <access_token>
```

获取 Token：

```http
POST /api/auth/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=your-password
```

响应：

```json
{
  "access_token": "eyJ...",
  "token_type": "bearer"
}
```

---

## 飞书 Bot 集成建议

### 推荐架构

```
用户发消息 → 飞书Bot → 解析概念关键词 → POST /api/industry-analysis/run → 解析结果 → 回复消息
```

### 推荐回复格式

根据返回的 `recommendations` 数组构造消息：

```
📊 AI相关 行业分析完成

🏆 Top 5 推荐：
1. 科大讯飞(002230) - 评分88 - AI语音龙头
2. 海康威视(002415) - 评分85 - AI视觉龙头
3. ...

📋 完整报告已生成，需要查看详细尽调报告吗？
```

### 超时处理

同步模式 `/run` 端点的分析通常需要 2-4 分钟。建议：

1. 飞书 Bot 先回复"正在分析中..."
2. 设置 HTTP 超时为 360 秒
3. 超时后改用异步模式（submit → 轮询）

### 异步模式下的飞书推送

```
用户发消息 → Bot回复"分析中"
              → submit → task_id
              → 后台轮询 result/{task_id}
              → 完成后主动推送消息给用户
```

---

## 使用脚本示例

### 一键同步分析（推荐）

```bash
python examples/industry_analysis_api_client.py run \
  --base-url http://127.0.0.1:8000 \
  --username admin \
  --password 'your-password' \
  --concept "AI相关" \
  --top-n 5 \
  --detail-level detailed
```

### 分步异步

```bash
# 1. 登录
python examples/industry_analysis_api_client.py login \
  --base-url http://127.0.0.1:8000 \
  --username admin \
  --password 'your-password'

# 2. 提交
python examples/industry_analysis_api_client.py submit \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --concept "高股息"

# 3. 等待完成
python examples/industry_analysis_api_client.py wait \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --task-id '<task_id>'

# 4. 获取结果
python examples/industry_analysis_api_client.py result \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --task-id '<task_id>'

# 5. 下载报告
python examples/industry_analysis_api_client.py download \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --task-id '<task_id>' \
  --format markdown
```

---

## 与单股分析的差异

| 项目 | 单股分析 | 行业/概念分析 |
|------|---------|-------------|
| 入参 | stock_code + 多参数 | concept（一个关键词） |
| 耗时 | 3-8分钟 | 2-4分钟 |
| 结果 | 单股报告 | 尽调报告 + Top N选股 |
| 同步端点 | 无 | `/run`（本次新增） |
| 报告下载 | `/api/reports/{id}/download` | `/api/industry-analysis/{id}/download` |

---

## 常见问题

### 1. 概念填什么？

任意中文关键词。系统会通过LLM将模糊概念映射到实际板块：
- "AI相关" → 人工智能、大数据、机器学习
- "高股息" → 银行、煤炭、公用事业
- "新能源" → 光伏设备、锂电池、风电设备

### 2. 分析超时怎么办？

同步模式超时（>6分钟）时返回 500。建议改用异步模式。

### 3. 数据来源？

系统自动选择可用数据源：
- 板块成分：AKShare → LLM推荐
- 行情数据：MongoDB → AKShare → DataSourceManager(BaoStock/Tushare)
- 财务数据：AKShare → BaoStock

### 4. 模型选择？

后端自动使用已配置的模型（通过管理后台设置），不需要前端/客户端指定。
