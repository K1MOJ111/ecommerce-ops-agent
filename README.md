# Ecommerce Ops Agent

**Stable Preview · Phase 07 completed · Phase 07.5 Product Frontend CLOSED · Phase 08 Not Started**

基于 FastAPI、LangGraph 和 PostgreSQL 的电商运营 Agent。把商品、库存、订单、物流查询与售后规则检索串成可追溯流程，并对取消订单、退款申请加入人工确认和事务保护。模型提出动作，服务端负责授权、业务规则和实际执行。

仓库内的 Seed、Fixture（测试样例）和 Eval Dataset **全部为 development / test fixtures**：用户、订单、物流、地址和政策均为模拟数据，不来自真实客户或任何电商平台内部数据。

## Architecture

```mermaid
flowchart TD
    U[User] --> API[FastAPI / trusted context]
    API --> G[LangGraph Agent]
    G --> T[Tool Registry]
    T --> B[Business Services]
    B --> DB[(PostgreSQL)]
    T --> R[RAG / scope and date filters]
    R --> V[pgvector / exact cosine]
    R --> K[keyword retrieval]
    V --> F[RRF]
    K --> F
    F --> E[Evidence / source and locator]
    E --> G
```

单体分层、单 Agent、固定工具白名单；业务服务直接使用 SQLAlchemy。实时业务数据走工具，静态售后规则走 RAG。详见 [架构与工程决策](docs/architecture.md)。

## Core Capabilities

- **7 个只读工具**：商品搜索、商品详情、SKU（具体商品规格）、库存、订单、物流、售后规则检索。
- **2 个受控写意图**：未付款订单取消、退款申请；先生成操作草稿，确认后才修改业务数据。
- **有边界的 Agent**：澄清、拒绝、有限工具循环；默认最多 8 次工具尝试、24 个图步骤、单次模型 30 秒、整请求 90 秒。
- **证据约束输出**：模型选择成功工具结果，代码呈现结构化数据、来源和时间；缺数据或部分失败会明确标注。
- **可观测性**：结构化日志关联请求、模型、工具、检索、暂停与恢复；记录耗时、状态和计数，避开完整 Prompt 与业务结果。

## Tech Stack

Python 3.11+（已测 3.12.9） · FastAPI · LangGraph · SQLAlchemy 2.x · Pydantic 2.x · PostgreSQL 17 · pgvector · Alembic · Docker Compose · pytest。

模型与 Embedding（文本向量化）通过 httpx 调用 OpenAI-compatible API；默认测试使用 Fake / Mock，不依赖真实模型。`requirements.lock` 固定直接及传递依赖版本，是版本约束快照，不是带哈希的跨平台锁文件。

## Safety & HITL

HITL（Human-in-the-loop）是在真实业务写入前暂停，让人查看并明确确认操作。模型不能提交身份、权限、SQL 或替代确认。

```mermaid
flowchart TD
    W[Write Intent] --> D[Operation Draft]
    D --> I[HITL Interrupt]
    I --> P[PostgresSaver / durable checkpoint]
    P --> C[Confirm]
    C --> R[Revalidation / authorization and state]
    R --> TX[Idempotent Transaction]
    TX --> A[Audit + business change + receipt]
```

幂等事务指同一操作重试不会重复执行。恢复时重查归属、当前权限与业务状态；订单行锁约束退款累计数量及金额；业务变更、审计与结果回执在同一事务提交。历史查询回放也重新授权。检查点保存与业务事务独立，业务已提交后可通过回执恢复结果。

取消仅支持本人未付款且无物流/退款的订单；退款仅创建 `requested` 申请，不审批、不打款。正式认证尚未接入，业务 API 默认返回 401；`DEV_ACTOR_ID` 仅供本机 development/test 固定身份。

## RAG

RAG（检索增强生成）先查找适用资料，再提供可追溯证据：

- 10 份模拟政策，按完整段落分块，保留文档版本、字符位置与来源；`fixture://` 是样例标识，不是官方链接。
- 两路共同过滤发布状态、有效期、商品/品类/全局范围；pgvector 精确余弦与简单关键词分别召回。
- RRF（倒数排名融合）合并两路结果；没有 Reranker（额外的模型排序环节）。引用返回原文，不把检索相似度当成正确概率。

价格、库存、订单和物流直接查询数据库。历史订单政策适用与规则冲突仍有限制，引用不代表退款获批。

## Evaluation

以下为 **2026-09-15 已保存的离线结果**，不是本次文档调整重新运行的结果。完整计算口径、逐例失败与报告见 [Eval Summary](docs/eval/eval_summary.md)。

- **Agent Fake Eval：46/46**，属于 **deterministic offline workflow evaluation**（脚本化、确定性的离线工作流评估），**不是 live LLM accuracy**。验证指定轨迹、规则与安全后置条件，不能推导真实模型理解能力。
- **PostgreSQL integration testing**：阶段关闭时完整测试 **467 passed / 0 failed / 0 skipped**，包含真实数据库、HITL、并发退款约束及迁移往返。
- **Hybrid retrieval evaluation**：33 个查询，含 22 个应命中、10 个应无结果、1 个参数冲突拒绝；Fake Embedding 为 256 维字符特征，不代表真实语义向量。

| Retrieval | Hit@3（22 个正例） | MRR | 无结果正确率（10 个负例） |
|---|---:|---:|---:|
| Vector | **36.36%** | 0.3636 | 100% |
| Keyword | **63.64%** | 0.6136 | 90% |
| Hybrid | **63.64%** | **0.6364** | 90% |

Hit@3 是前三条结果中命中目标的比例；MRR 是首次命中排名倒数的均值，未命中记零。

主要瓶颈为 **conversational / synonym recall（口语与同义表达召回）**：Hybrid 漏掉 8/22 个正例；另有 `unknown-price` 返回相关政策但不含所问金额。Hybrid 的命中率未超过 Keyword，无结果正确率低于 Vector；不隐藏这些失败，也不据此宣称高准确率。

**Live LLM / Live Embedding 均因缺配置而 blocked，真实兼容性、语言质量与语义检索效果未验证。**

## Quick Start

以下在项目根目录使用 PowerShell 执行。前提：Python 3.12、Docker Desktop Linux 引擎及 Docker Compose。

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -c requirements.lock -e '.[test]'

# 首次生成配置，随机替换示例密码；保留已有 .env，不输出密码。
if (-not (Test-Path .env)) {
    $localPassword = [guid]::NewGuid().ToString('N')
    $configText = [IO.File]::ReadAllText((Join-Path $PWD '.env.example'))
    $configText.Replace('example-local-only', $localPassword) | Set-Content -Encoding utf8 .env
}

docker compose config --quiet
docker compose up -d db --wait --wait-timeout 90
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m scripts.setup_checkpoints
.venv/Scripts/python.exe -m scripts.seed_data
.venv/Scripts/python.exe -m scripts.agent_smoke
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另一个终端执行 `Invoke-RestMethod http://127.0.0.1:8000/health`，或打开 [API 文档](http://127.0.0.1:8000/docs)。上述 Fake smoke 使用开发 Seed，无需模型 Key；HTTP Agent 默认使用 `openai_compatible`，需要配置 `LLM_BASE_URL`、`LLM_API_KEY`、`LLM_MODEL`。本地无 Key 体验可按下方 Frontend 说明显式启用 Fake Provider；默认身份仍拒绝业务请求。

需要本机体验业务 API 时，在启动 Uvicorn 前设置固定模拟身份：

```powershell
$env:DEV_ACTOR_ID = & .venv/Scripts/python.exe -c 'from scripts.seed_data import seed_id; print(seed_id("customer-a"))'
```

接口：`POST /agent/requests` 发起，`GET /agent/threads/{thread_id}` 查看，`POST /agent/threads/{thread_id}/resume` 显式 confirm/reject。请求字段与规则见 [API 与身份](docs/architecture.md#api-与身份)。停止本地 API 后使用 `Remove-Item Env:\DEV_ACTOR_ID` 清理该终端设置。固定身份不是登录系统，不用于公网服务。

Seed 仅在 development/test 显式运行，按固定 UUID 只补缺失数据，不覆盖已有修改。`SEED-O001` 是模拟未付款订单；其他订单与数据构造见 [seed_data.py](scripts/seed_data.py)。应用启动不自动迁移或 Seed。

`.env` 被 Git/Docker 忽略，`.env.example` 仅含示例值。PostgreSQL 映射本机 `55432`；也可用 `docker compose up -d --build api --wait --wait-timeout 90` 替代本机 Uvicorn，避免同时占用 8000 端口。当前依赖组合的 Linux API 镜像尚未重新构建验证。

知识入库可显式运行 `.venv/Scripts/python.exe -m scripts.ingest_knowledge --fake`；该模式仅生成测试向量。真实政策检索需另行配置 `EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL`，并在相同向量空间重新入库；不传 `--fake` 才使用真实 Provider。

## Frontend

`frontend/` 是独立 Vue 3 / Vite / TypeScript 单页应用：左侧会话、中间 Agent 对话与 HITL、右侧业务资料和政策引用。通过原生 `fetch` 调用 FastAPI，没有浏览器业务 Mock、更新订单接口或前端权限配置。前端唯一运行依赖是 Vue。

### Local Development

**Backend**：先完成 Quick Start 的数据库启动、迁移、checkpoint 和 Seed。在项目根目录的 PowerShell 设置本次进程配置，再启动后端：

```powershell
$env:APP_ENV = 'development'
$env:AGENT_PROVIDER = 'fake'
$env:EMBEDDING_PROVIDER = 'fake'
$env:DEV_ACTOR_ID = & .venv/Scripts/python.exe -c 'from scripts.seed_data import seed_id; print(seed_id("customer-a"))'
.venv/Scripts/python.exe -m scripts.ingest_knowledge --fake
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

仅 Provider 被替换，Tool、Service、PostgreSQL、检索、持久化 HITL 与事务仍走真实实现。`APP_ENV=production` 会拒绝任一 Fake Provider 或 `DEV_ACTOR_ID`。Fake Agent 只支持明确的中文模板和参数，不等于真实语言理解；Fake Embedding 不是语义模型。切回真实 Provider 时分别设置 `AGENT_PROVIDER=openai_compatible`、`EMBEDDING_PROVIDER=openai_compatible` 及相应服务配置，真实向量须另行入库。

**Frontend**：Node.js 22.12+（本机验证 24.14.0，前端逻辑测试使用 Node 原生 TypeScript 类型剥离），另开终端：

```powershell
Set-Location frontend
npm install
# 默认 API 为 http://127.0.0.1:8000；需更换时设置公开地址。
$env:VITE_API_BASE_URL = 'http://127.0.0.1:8000'
npm run dev
```

打开 [本地前端](http://127.0.0.1:5173)。也可参考 `frontend/.env.example` 新建本地配置；`VITE_*` 会进入浏览器代码，禁止保存 Key、Token 或密码。开发 CORS 只允许 `http://localhost:5173` 与 `http://127.0.0.1:5173`；生产默认无跨域许可，只能通过 `CORS_ORIGINS` JSON 数组配置明确 HTTPS 来源，不允许 `*`。

可复制输入：

- `查询商品 纯棉短袖` / `查询商品详情 纯棉短袖`
- `查询 SKU 纯棉短袖` / `查询库存 纯棉短袖 白色 M`
- `查询订单 SEED-O003` / `查询物流 SEED-O003`
- `查询七天无理由退货政策`
- `取消我的订单 SEED-O001，原因 不需要了`：先显示草稿，再 Confirm / Reject。
- `申请退款 订单 SEED-O003，明细 <订单查询中展开的明细编号>，数量 1，金额 59.00，原因 尺码不合适`

本地固定用户为模拟消费者甲，只能访问奇数 Seed 订单。取消 Confirm 会真实改变开发库 `SEED-O001`，Seed 重跑不会复原；自动化 E2E 使用单独临时数据库。退款仅创建申请，不审批或打款。

会话历史保存在当前标签页 `sessionStorage`：仅请求文本、幂等 key、thread/Clarify 引用及用户选择，不缓存业务证据；刷新/切换会话重新 GET 并授权。后端保持一请求一 workflow；遇到 Clarify 时可直接回复订单号等缺少的信息，前端通过 `clarification_thread_id` 引用上一请求，后端从持久化 checkpoint 恢复已接受的上下文。格式错误仍等待同一字段，刷新后可继续；普通新问题不继承整段聊天记忆。取消原因、退款明细编号/数量/金额均需用户明确提供，不自动补齐。确认、拒绝和状态刷新沿用对应操作的 thread，失败重试复用原 request_key/decision。页面不会凭按钮点击宣称业务成功。

`/health/live` 与 `/health` 分别探测 API、数据库；新增 `/status` 在可信身份验证后返回用户名与 Provider 配置状态，不返回密钥、数据库地址或权限。`configured` 仅表示配置齐全，不代表真实 Provider 连通性已验证。

业务资料只收录成功的真实实体或有效政策引用。HITL 等待确认时，右栏仅显示与当前 Draft 目标订单身份一致的真实 Evidence；无匹配时显示目标编号与“暂无关联业务资料”，操作结束后恢复普通展示。

### Frontend checks

```powershell
# 在 frontend 目录执行
npm run typecheck
npm run build
npm test
npx playwright test tests/ui.spec.ts
```

真实 E2E：本机需已安装 Chrome、Docker PostgreSQL 健康，5173 和 8010 端口空闲；在项目根目录执行：

```powershell
.venv/Scripts/python.exe -m scripts.frontend_e2e
```

脚本创建本轮随机 `_test` 数据库，运行现有迁移、Seed、知识入库和真实 FastAPI / Vue；使用浏览器验证查询、引用、Confirm / Reject、刷新恢复、响应丢失与退款申请。结束时检查真实订单/退款/Audit 后置条件，仅删除本轮创建的测试库。数据库用户需有本地创建数据库权限。浏览器输出在忽略的 `output/playwright/` 中，不能公开上传其中的会话数据。`tests/ui.spec.ts` 是明确的故障注入 UI 检查，不作为真实业务 E2E 证据。

## Tests

无需数据库或真实模型的单元测试：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit
```

完整回归使用两个专用 PostgreSQL 测试库，不能指向业务库。以下库只需首次创建；已存在时跳过 `createdb`。修改过数据库用户名时同步修改 `-U ecommerce`。

```powershell
docker compose exec -T db createdb -U ecommerce ecommerce_ops_test
docker compose exec -T db createdb -U ecommerce ecommerce_ops_migration_test

$env:TEST_DATABASE_URL = & .venv/Scripts/python.exe -c 'from app.core.config import Settings; from sqlalchemy.engine import make_url; print(make_url(Settings().database_url.get_secret_value()).set(database="ecommerce_ops_test").render_as_string(hide_password=False))'
$env:MIGRATION_DATABASE_URL = & .venv/Scripts/python.exe -c 'from app.core.config import Settings; from sqlalchemy.engine import make_url; print(make_url(Settings().database_url.get_secret_value()).set(database="ecommerce_ops_migration_test").render_as_string(hide_password=False))'
.venv/Scripts/python.exe -m pytest -q

# 独立离线评估；.local.json 不提交，已有同名报告时改用新文件名。
.venv/Scripts/python.exe -m scripts.agent_eval agent --report docs/eval/agent_eval_results.local.json
.venv/Scripts/python.exe -m scripts.agent_eval rag --report docs/eval/rag_eval_results.local.json
.venv/Scripts/python.exe -m scripts.agent_eval smoke --report docs/eval/smoke_eval_results.local.json
Remove-Item Env:\TEST_DATABASE_URL,Env:\MIGRATION_DATABASE_URL
```

未设置对应数据库变量会明确 skip，不能当作完整通过。普通测试事务回滚；持久化 HITL 场景提交后仅清理自己的随机 UUID 数据。迁移往返会删表，仅允许无业务记录/未知表且名称以 `_migration_test` 结尾的专用库。更多评估和 Live 边界见 [重复执行](docs/eval/eval_summary.md#重复执行)。

## Project Status

当前为 **Stable Preview**：Phase 07 离线交付完成并已公开发布，稳定预览标签为 `v0.7-preview`。**Phase 07.5 Product Frontend CLOSED**；Phase 08 保持 **Not Started**。本次阶段提交不修改既有标签、不创建 Release。

技术状态、实际验证结果与边界见 [PROJECT_STATE.md](PROJECT_STATE.md)。

## License

本项目采用 [MIT License](LICENSE)。

## Known Limitations

- 未接入正式认证、数据库运行/迁移最小权限及审计防篡改；未进行生产部署、负载和备份恢复验证。
- Live LLM / Embedding 未验证；Fake 结果不能推导真实模型或线上质量。
- 仅支持未付款取消与退款申请；不释放库存、不实际退款、不支持多操作或编辑待确认草稿。
- RAG 口语/同义召回、答案充分性、历史事件日期/品类快照与政策冲突尚未完整解决。
- Checkpoint 枚举反序列化存在已记录警告；draft JSONB 与列字段的完整数据库绑定约束仍待加固。
- Checkpoint 会保存必要消息及查询数据，尚无隐私保留/归档策略；当前结构化证据输出也未验证真实语言体验。
