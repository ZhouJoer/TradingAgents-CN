# TradingAgents-CN 报告 API 集成说明

这份文档配合 `examples/report_api_client.py` 使用，面向：

1. AI Agent
2. 飞书机器人 / 飞书服务端
3. 定时任务 / 工作流平台
4. 你自己的中台服务

目标是完整覆盖 **单股分析页 `frontend/src/views/Analysis/SingleAnalysis.vue` 的参数面**，并说明后端实际支持的提交、进度、结果、下载几种方式。

## 结论

如果你要把分析能力接进飞书服务，推荐直接走 **WebAPI**，不要复用前端页面逻辑。

最推荐的链路：

1. 登录：`POST /api/auth/login`
2. 提交任务：`POST /api/analysis/single`
3. 跟踪进度：轮询 `GET /api/analysis/tasks/{task_id}/status` 或 SSE `GET /api/stream/tasks/{task_id}`
4. 获取结构化结果：`GET /api/analysis/tasks/{task_id}/result`
5. 下载文件报告：`GET /api/reports/{report_id}/download?format=...`

---

## 现成脚本

文件：

```bash
examples/report_api_client.py
```

这个脚本现在支持：

1. `login`
2. `submit-single`
3. `task-status`
4. `wait-task`
5. `task-sse`
6. `task-result`
7. `download-report`
8. `run-single`

### 查看帮助

```bash
python examples/report_api_client.py --help
python examples/report_api_client.py run-single --help
```

---

## 与前端单股分析页对齐的参数

前端提交分析时实际发送的是：

```json
{
  "symbol": "...",
  "stock_code": "...",
  "parameters": {
    "market_type": "...",
    "analysis_date": "...",
    "research_depth": "...",
    "selected_analysts": ["..."],
    "include_sentiment": true,
    "include_risk": true,
    "language": "zh-CN",
    "quick_analysis_model": "...",
    "deep_analysis_model": "..."
  }
}
```

脚本已经对齐这套字段，并额外支持：

1. `custom_prompt`
2. `--use-server-default-models`

### 参数映射表

| 前端字段 | API 字段 | 脚本参数 | 默认值来源 |
| --- | --- | --- | --- |
| 股票代码 | `symbol` / `stock_code` | `--symbol` | 必填 |
| 市场 | `parameters.market_type` | `--market-type` | 初始表单默认 `A股`，页面运行时可能被用户偏好覆盖 |
| 分析日期 | `parameters.analysis_date` | `--analysis-date` | 今天 |
| 研究深度 | `parameters.research_depth` | `--research-depth` / `--research-depth-level` | 初始表单默认 `标准` / `3`，页面运行时可能被用户偏好覆盖 |
| 分析师 | `parameters.selected_analysts` | `--analyst` | 初始表单默认 `market,fundamentals`，页面运行时可能被用户偏好覆盖 |
| 情绪分析开关 | `parameters.include_sentiment` | `--include-sentiment` / `--no-include-sentiment` | `true` |
| 风险分析开关 | `parameters.include_risk` | `--include-risk` / `--no-include-risk` | `true` |
| 语言 | `parameters.language` | `--language` | `zh-CN` |
| 快速模型 | `parameters.quick_analysis_model` | `--quick-analysis-model` | 页面先读 `/api/config/settings`，失败才回退 `qwen-turbo` |
| 深度模型 | `parameters.deep_analysis_model` | `--deep-analysis-model` | 页面先读 `/api/config/settings`，失败才回退 `qwen-max` |
| 自定义提示词 | `parameters.custom_prompt` | `--custom-prompt` | 空 |

### 页面运行时默认值说明

`SingleAnalysis.vue` 的“默认值”分两层：

1. **初始表单默认值**：`A股`、今天、`3/标准`、`市场分析师+基本面分析师`、`zh-CN`
2. **页面启动后再覆盖**
   - 市场 / 深度 / 分析师：优先取 `/api/auth/me` 里的 `preferences`，其次取本地 `appStore.preferences`
   - quick/deep 模型：取 `/api/config/settings`，失败才回退到 `qwen-turbo/qwen-max`

示例脚本默认不自动读取用户偏好，所以如果你想复现某个用户在页面里看到的默认市场 / 深度 / 分析师，最好显式传：

```bash
--market-type ...
--research-depth-level ...
--analyst ...
```

如果你想让脚本像页面一样先取服务端默认模型，再回退到 qwen，可以加：

```bash
--use-server-default-models
```

### 研究深度映射

前端是数字，发给后端时会转成中文描述：

| 层级 | 后端值 |
| --- | --- |
| 1 | `快速` |
| 2 | `基础` |
| 3 | `标准` |
| 4 | `深度` |
| 5 | `全面` |

脚本同时支持：

```bash
--research-depth 标准
--research-depth 3
--research-depth-level 3
```

### 分析师映射

前端中文名称会被转换成后端 ID：

| 前端名称 | 后端 ID |
| --- | --- |
| 市场分析师 | `market` |
| 基本面分析师 | `fundamentals` |
| 新闻分析师 | `news` |
| 社媒分析师 | `social` |

脚本支持两种写法：

```bash
--analyst market --analyst fundamentals
--analyst 市场分析师 --analyst 基本面分析师
```

也支持逗号分隔：

```bash
--analyst market,fundamentals,news
```

---

## 支持的方式

### 1. 提交方式

| 方式 | Endpoint | 脚本支持 |
| --- | --- | --- |
| 单股分析 | `POST /api/analysis/single` | 是 |
| 批量分析 | `POST /api/analysis/batch` | 本脚本暂未封装 |

当前示例脚本只封装 **单股分析**，因为它最适合飞书服务的单次问答场景。

### 2. 进度方式

| 方式 | Endpoint | 前端当前是否使用 | 脚本支持 |
| --- | --- | --- | --- |
| 轮询 | `GET /api/analysis/tasks/{task_id}/status` | 是 | 是 |
| SSE | `GET /api/stream/tasks/{task_id}` | 否 | 是 |
| WebSocket | `ws://.../api/analysis/ws/task/{task_id}` | 否 | 文档说明，脚本未封装 |

前端 `SingleAnalysis.vue` 当前实际使用的是：**轮询，每 5 秒一次**。

补充一点：**单任务 SSE 流里没有稳定的 `finished` 事件**。因此脚本里的：

1. `wait-task --wait-method sse` 会在流结束后再补查一次状态
2. `task-sse` 也是按“流事件 + 最后一跳状态查询”判断退出码

### 3. 结果方式

| 方式 | Endpoint | 说明 |
| --- | --- | --- |
| 结构化结果 | `GET /api/analysis/tasks/{task_id}/result` | 推荐给 AI / 服务端消费 |
| 报告详情 | `GET /api/reports/{report_id}/detail` | 更偏页面详情展示 |
| 文件下载 | `GET /api/reports/{report_id}/download?format=...` | 适合附件上传 |

### 4. 报告格式

| 格式 | 参数值 |
| --- | --- |
| Markdown | `markdown` |
| JSON | `json` |
| Word | `docx` |
| PDF | `pdf` |

---

## 推荐用法

## 方式 A：一条命令跑完整链路

```bash
cd /home/yuan/code/stock/TradingAgents-CN
source .venv/bin/activate

python examples/report_api_client.py run-single \
  --base-url http://127.0.0.1:8000 \
  --username admin \
  --password 'your-password' \
  --symbol 600036 \
  --market-type A股 \
  --research-depth-level 3 \
  --analyst market \
  --analyst fundamentals \
  --include-sentiment \
  --include-risk \
  --language zh-CN \
  --use-server-default-models \
  --wait-method poll \
  --download-format markdown
```

这会：

1. 登录
2. 提交任务
3. 等待完成
4. 拉取结构化结果
5. 保存 `result.json`
6. 下载报告文件
7. 把总结 JSON 打印到 stdout

---

## 方式 B：分步调用，适合飞书服务拆分

### 1. 登录

```bash
python examples/report_api_client.py login \
  --base-url http://127.0.0.1:8000 \
  --username admin \
  --password 'your-password'
```

### 2. 提交任务

```bash
python examples/report_api_client.py submit-single \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --symbol 600036 \
  --market-type A股 \
  --research-depth-level 3 \
  --analyst 市场分析师 \
  --analyst 基本面分析师 \
  --use-server-default-models
```

如果你不想跟随后端当前默认模型，而是想强制指定模型，也可以直接传：

```bash
--quick-analysis-model MiniMax-M2.7-highspeed
--deep-analysis-model MiniMax-M2.7
```

### 3. 查状态

```bash
python examples/report_api_client.py task-status \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --task-id '<task_id>'
```

### 4. SSE 看进度

```bash
python examples/report_api_client.py task-sse \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --task-id '<task_id>'
```

### 5. 等待完成

轮询：

```bash
python examples/report_api_client.py wait-task \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --task-id '<task_id>' \
  --wait-method poll
```

SSE：

```bash
python examples/report_api_client.py wait-task \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --task-id '<task_id>' \
  --wait-method sse \
  --print-sse-events
```

### 6. 获取结构化结果

```bash
python examples/report_api_client.py task-result \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --task-id '<task_id>'
```

### 7. 下载报告

```bash
python examples/report_api_client.py download-report \
  --base-url http://127.0.0.1:8000 \
  --access-token '<token>' \
  --report-id '<analysis_id-or-task_id>' \
  --download-format markdown \
  --output-dir ./api_output
```

---

## 脚本输出说明

所有命令都把结果打印成 JSON，适合 AI / 飞书服务直接解析。

### `run-single` 输出示例

```json
{
  "mode": "run-single",
  "request": {
    "symbol": "600036",
    "stock_code": "600036",
    "parameters": {
      "market_type": "A股",
      "analysis_date": "2026-05-28",
      "research_depth": "标准",
      "selected_analysts": ["market", "fundamentals"],
      "include_sentiment": true,
      "include_risk": true,
      "language": "zh-CN",
      "quick_analysis_model": "MiniMax-M2.7-highspeed",
      "deep_analysis_model": "MiniMax-M2.7"
    }
  },
  "task": {
    "task_id": "..."
  },
  "final_status": {
    "status": "completed",
    "progress": 100
  },
  "analysis_id": "...",
  "result_json_path": "api_output/<task_id>.result.json",
  "report_path": "api_output/<file>.md",
  "result": {
    "summary": "...",
    "recommendation": "...",
    "decision": {},
    "reports": {}
  }
}
```

---

## 飞书服务接入建议

推荐服务端流程：

1. 飞书收到用户消息
2. 解析股票代码、市场、深度、分析师、语言、模型
3. 调 `run-single`，或者调 `submit-single` + `wait-task` + `task-result`
4. 解析 stdout JSON
5. 用 `result.summary` / `result.recommendation` 回消息
6. 需要附件时，把 `report_path` 对应文件发到飞书

### 推荐场景

#### 同步回复

适合时长可接受的场景：

```text
run-single
```

#### 异步回复

适合分析较久的场景：

```text
submit-single -> task_id
wait-task / task-sse
task-result
download-report
```

---

## 与前端行为的关系

`frontend/src/views/Analysis/SingleAnalysis.vue` 当前实际行为：

1. `POST /api/analysis/single`
2. 保存 `task_id`
3. 每 5 秒轮询 `GET /api/analysis/tasks/{task_id}/status`
4. 完成后调 `GET /api/analysis/tasks/{task_id}/result`
5. 下载时调 `GET /api/reports/{reportId}/download?format=...`
6. 页面初始化时还会补拉：
   - `GET /api/auth/me`（用户偏好）
   - `GET /api/config/settings`（默认模型）

这份脚本和文档就是按这条链补齐的，只是额外补了：

1. `custom_prompt`
2. SSE 方式
3. 分步命令
4. `--use-server-default-models`

---

## WebSocket 方式

后端也支持：

```text
ws://127.0.0.1:8000/api/analysis/ws/task/{task_id}
```

当前示例脚本没有封装 WebSocket，因为那会引入额外依赖；如果你的飞书服务已经有 WebSocket 客户端基础设施，可以自行接这条链。

---

## CLI 和 API 怎么选

### CLI

仓库内也有交互式 CLI：

```bash
python -m cli.main
python -m cli.main analyze
```

它更适合人工操作，会把报告写到：

```bash
./results/<ticker>/<analysis_date>/reports/*.md
```

### API

如果是飞书服务、机器人、自动化工作流，优先选 API。

---

## 常见问题

### 1. `report_id` 应该传什么？

优先传：

1. `analysis_id`
2. 如果没有，也可以尝试 `task_id`

后端下载接口会兼容多种 ID 形式。

### 2. PDF 下载失败怎么办？

确保系统安装：

```bash
sudo apt install -y pandoc wkhtmltopdf
```

然后重启后端。

### 3. `custom_prompt` 前端没看到，为什么脚本有？

因为：

1. 当前 `SingleAnalysis.vue` 没把它暴露到页面上
2. 但前端 API 类型和后端参数模型都支持它
3. 服务集成场景里它很有用，所以脚本保留了这个入口

### 4. 脚本什么时候该用 `--use-server-default-models`？

推荐在下面两类场景打开：

1. 你想跟随后端当前生效的 quick/deep 默认模型
2. 你已经用 `scripts/set_local_minimax_config.py` 或管理后台改过默认模型，不想在每次调用里重复写模型名

如果你希望每次请求都完全可复现，直接显式传 `--quick-analysis-model` 和 `--deep-analysis-model` 更合适。
