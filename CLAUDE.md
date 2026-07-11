# AI Companion Runtime

## 项目简介

基于 WebSocket 的实时 AI 情绪陪伴 + 通用助手系统。支持情绪识别、风险分级、工具调用、长期记忆、模型热插拔、Pi Agent 编排、全链路 TraceID 观测。

## 技术栈

| 层 | 技术 |
|---|------|
| 前端 | Next.js 14 + TypeScript + TailwindCSS + Zustand |
| 后端 | Python 3.11 + FastAPI + WebSocket |
| 数据库 | PostgreSQL 16 + pgvector + Alembic (migration) |
| 缓存 | Redis 7 |
| 对象存储 | MinIO (archive / attachments / traces 三个 bucket) |
| 异步任务 | Celery + Redis (broker) |
| 观测 | OpenTelemetry + Jaeger, Prometheus + Grafana |
| 模型 | Adapter 模式，支持 Qwen / DeepSeek / OpenAI / Gemini / 本地模型 |
| 部署 | Docker Compose（后续可上 K8s） |

## 项目结构

```
ai-companion-runtime/
├── apps/
│   ├── web/              # Next.js 前端
│   │   ├── app/          # 页面 (chat / traces / login)
│   │   ├── components/   # React 组件
│   │   ├── stores/       # Zustand 状态管理
│   │   └── lib/          # WebSocket 客户端 / API 客户端
│   └── api/              # FastAPI 后端
│       └── app/
│           ├── config/       # 配置文件 (models.yaml / runtime.yaml / personality.yaml / risk_rules.yaml)
│           ├── api/          # HTTP/WS 端点
│           ├── runtime/      # 核心运行时 (gateway / pi_runtime / stream)
│           ├── engines/      # 分析引擎 (intent / emotion / risk / memory / personality / reflection)
│           ├── models/       # 模型层 (router / registry / adapters)
│           ├── tools/        # 工具系统 (weather / search / calculator / reminder)
│           ├── observability/ # 追踪与指标 (trace / metrics / logger / cost)
│           ├── workers/      # Celery 异步任务
│           ├── storage/      # MinIO 客户端
│           └── db/           # SQLAlchemy 模型 + Alembic migrations
├── infra/                # Docker Compose + Prometheus + Grafana
├── data/                 # 本地数据目录
└── docs/                 # 设计文档
```

## 开发规范

### Python 后端

- **Python 版本**: 3.11+
- **异步**: 全链路 async/await，使用 `asyncpg` + `SQLAlchemy 2.0 async`
- **类型标注**: 所有函数必须有类型标注，使用 `from __future__ import annotations`
- **数据模型**: 使用 Pydantic v2 的 `BaseModel` 定义所有接口数据结构
- **接口定义**: 模块间通过 `ABC` 或 `Protocol` 定义接口，不依赖具体实现
- **配置管理**: 运行时配置放 YAML 文件（`config/` 目录），密钥放 `.env`
- **导入顺序**: stdlib → 第三方 → 本项目，各组之间空一行
- **错误处理**: 不静默吞异常；超时用 `asyncio.wait_for`；降级走 runtime fallback 策略（无 Harness 回退）
- **Migration**: 使用 Alembic，修改 `db/models.py` 后运行 `alembic revision --autogenerate`

### TypeScript 前端

- **Node 版本**: 18+
- **框架**: Next.js 14 App Router
- **状态管理**: Zustand（不用 Redux / Context）
- **样式**: TailwindCSS，不用 CSS Modules
- **WebSocket**: 封装在 `lib/ws-client.ts`，通过 `wsStore` 管理连接状态
- **组件**: 函数式组件，用 `interface` 定义 Props
- **命名**: 组件文件 PascalCase（`ChatWindow.tsx`），工具文件 camelCase（`ws-client.ts`）

### 模块边界

每个模块对外只暴露接口类型和工厂函数，不暴露内部实现细节：

| 模块 | 入口接口 | 出口接口 |
|------|----------|----------|
| intent_engine | `AnalyzerInput` | `IntentResult` |
| emotion_engine | `AnalyzerInput` | `EmotionResult` |
| risk_engine | `AnalyzerInput` | `RiskResult` |
| memory_engine | `MemoryQuery` | `MemorySnapshot` |
| personality_engine | `EmotionResult + UserProfile + IntentResult` | `PersonalityConfig` |
| model_router | `PromptPayload` | `ModelStream` |
| model_adapter | `messages: list[dict]` | `AsyncIterator[str]` |
| tool_dispatcher | `ToolRequest` | `ToolResult` |
| trace_service | `TraceEvent` | `TraceDetail` |

### Git 规范

- **分支命名**: `feature/xxx`、`fix/xxx`、`refactor/xxx`
- **Commit 格式**: `<type>(<scope>): <description>`
  - type: feat / fix / refactor / docs / chore / test
  - scope: ws / harness / memory / model / tool / trace / web / infra
  - 示例: `feat(harness): add fast reply race strategy`
- **不要提交**: `.env`、`__pycache__/`、`node_modules/`、`.next/`

### 核心架构原则

1. **首句不等待**: fast reply 不等工具、不等向量召回、不等主模型完整输出
2. **超时即跳过**: Memory L3 召回 300ms 超时跳过，Analyzer 100ms 超时用默认值
3. **异步后处理**: Memory 更新、Embedding 生成、Reflection 总结、Trace 写入都走 Celery
4. **工具不阻塞**: 工具调度与主模型流式输出并行，工具失败不影响主回复
5. **模型可降级**: primary → fallback → 模板回复，三级降级
6. **风险优先**: Risk Engine 检测到 high/critical 立即拦截，不走后续流程

### 配置文件说明

| 文件 | 位置 | 用途 |
|------|------|------|
| `.env` | 项目根目录 | 密钥、数据库连接、API Key |
| `models.yaml` | `apps/api/app/config/` | 模型配置（primary/fallback/fast），修改后自动热加载 |
| `runtime.yaml` | `apps/api/app/config/` | Pi runtime 超时、重试、降级策略 |
| `personality.yaml` | `apps/api/app/config/` | 人格基础配置 + 动态适配矩阵 |
| `risk_rules.yaml` | `apps/api/app/config/` | 风险关键词、正则、分级规则 |
| `prometheus.yml` | `infra/` | Prometheus 采集配置 |
| `docker-compose.yml` | `infra/` | 全部服务编排 |

### Docker 启动

```bash
cd infra && docker compose up -d
```

服务端口：
- 前端: http://localhost:3000
- 后端 API: http://localhost:8000
- MinIO Console: http://localhost:9001
- Jaeger UI: http://localhost:16686
- Prometheus: http://localhost:9090
- Grafana: http://localhost:3001

### WebSocket 协议

连接: `ws://localhost:8000/ws/chat?token=JWT`

消息流顺序: `trace → risk_alert(可选) → first_reply → delta... → tool_status/tool_result(穿插) → final`

### 并行开发策略

本项目设计为支持多个 Claude Code Agent 并行开发。每个 Phase 内的 Agent 负责独立模块，模块间通过 ABC/Protocol 接口解耦。

**开发原则**:
- 先定义接口，再实现模块
- 模块内部自由实现，对外只暴露接口
- 公共类型定义放 `engines/base.py`、`models/adapters/base.py`、`tools/base.py`
- 集成测试验证模块间交互
