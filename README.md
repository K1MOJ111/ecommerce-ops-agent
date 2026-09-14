# ecommerce-ops-agent

基于 FastAPI、LangGraph 和 PostgreSQL 的电商智能运营 Agent 项目。目标是让模型理解业务请求，通过受控工具查询真实业务结构的数据，并依据有出处的知识资料回答售后规则问题。

## 项目入口

- [PROJECT_STATE.md](PROJECT_STATE.md)：唯一项目状态来源；后续阶段和新对话先读此文件。
- [docs/architecture.md](docs/architecture.md)：完整架构、目标目录、ER 模型、安全与 RAG 边界。

## 已确认目标

首个业务闭环覆盖商品咨询、SKU 查询、库存查询、订单查询、物流查询和售后规则问答。模型负责选择工具和组织回答，服务端业务代码负责权限、数据归属和确定性规则。

已确认技术栈：Python 3.11+、FastAPI、LangGraph、PostgreSQL、SQLAlchemy 2.x、Pydantic 2.x、pgvector、pg_trgm、Docker Compose、pytest。模型通过 OpenAI Compatible API 访问，供应商和模型由环境变量及 Settings 配置。

## 已确认边界

- 单体分层、单 Agent、显式 State、有限工具循环；首个业务闭环只读。
- 不开发前端，不引入 Multi-Agent、Redis、消息队列、微服务或通用 Repository。
- intent 仅用于可观测性、日志和 Eval，不参与授权或安全决策。
- Phase 02 不实现完整 JWT 登录，但保留 actor_id、permissions、request_id 的可信服务端上下文；订单查询必须验证数据归属。
- RAG 首版采用向量检索、必要过滤和简单关键词/模糊检索，不加入 Reranker。
- pg_trgm 只是辅助模糊匹配能力；中文检索效果须通过真实测试数据和 Eval 验证。
- Phase 06 已实现持久化 HITL 和两类受控写，运行方式见下方 Phase 06 节；旧 run_agent 保持只读。

## 阶段规划

先完成架构设计与确认，再按确认范围建设工程基础，逐步实现六类只读业务场景。后续再增加取消订单/退款申请、HITL、受控写操作、幂等控制、审计日志和 Agent Eval。

每个阶段以确认后的交付范围推进，不一次实现整个项目。具体进度、验收状态、下一阶段建议和未完成事项只在 PROJECT_STATE.md 中维护。

## 本地运行（PowerShell）

前提：Python 3.11+、Docker Desktop Linux 引擎和 Docker Compose。已测版本与测试结果只在 PROJECT_STATE.md 中记录。所有命令在项目根目录执行。

```powershell
py -3.12 -m venv .venv
.venv/Scripts/python.exe -m pip install -c requirements.lock -e '.[test]'

# 仅首次生成本地配置；不会覆盖已有 .env，也不会输出密码。
if (-not (Test-Path .env)) {
    $localPassword = [guid]::NewGuid().ToString('N')
    $configText = [IO.File]::ReadAllText((Join-Path $PWD '.env.example'))
    $configText.Replace('example-local-only', $localPassword) | Set-Content -Encoding utf8 .env
}

docker compose config --quiet
docker compose up -d db --wait --wait-timeout 90
.venv/Scripts/python.exe -m alembic upgrade head
docker compose up -d --build api --wait --wait-timeout 90
Invoke-RestMethod http://127.0.0.1:8000/health
```

API 只映射本机 8000，PostgreSQL 默认只映射本机 55432。`.env` 是本地私密配置，已在 Git/Docker 排除清单中；`.env.example` 只含示例值。Compose 内部数据库地址使用 `db:5432`，宿主机使用 `127.0.0.1:55432`。生成的密码是 URL 安全字符；手动设置含保留字符的密码时需要正确处理连接 URL。

迁移必须显式执行，应用启动不会建表。也可用容器执行迁移：`docker compose run --rm api alembic upgrade head`。不使用容器运行 API 时，执行 `.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000`，与 Compose API 二选一以避免端口冲突。

`/health/live` 为 API 存活检查；`/health` 为数据库连接就绪检查，失败返回 503；两者均不调用模型。Phase 06 业务接口见文末，正式认证仍未实现。

## 数据库测试

测试使用独立 PostgreSQL 数据库，名称必须以 `_test` 结尾。未设置 `TEST_DATABASE_URL` 时集成测试明确 skip，不会被当作通过；设置后连接或迁移失败即测试失败。

```powershell
# 仅首次创建；已存在时跳过此命令。
docker compose exec -T db createdb -U ecommerce ecommerce_ops_test

$env:TEST_DATABASE_URL = & .venv/Scripts/python.exe -c 'from app.core.config import Settings; from sqlalchemy.engine import make_url; print(make_url(Settings().database_url.get_secret_value()).set(database="ecommerce_ops_test").render_as_string(hide_password=False))'
.venv/Scripts/python.exe -m pytest -q
Remove-Item Env:\TEST_DATABASE_URL

.venv/Scripts/python.exe -m alembic current
.venv/Scripts/python.exe -m alembic check
.venv/Scripts/python.exe -m pip check
```

测试 fixture 先通过 Alembic 迁移独立测试库，然后为每个测试开启外层事务并在结束时回滚，既不清空业务数据库，也不保留测试业务记录。没有 SQLite 替代验证。若修改 PostgreSQL 用户名/数据库名，相应修改命令参数。

## Seed 与完整回归

Seed 只能在 `APP_ENV=development` 或 `test` 时显式执行，应用启动不执行 Seed：

```powershell
.venv/Scripts/python.exe -m scripts.seed_data
.venv/Scripts/python.exe -m scripts.seed_data
```

使用固定 `SEED-*` 业务编号、固定 UUID 和 UTC 时间。第一次向空开发库写入模拟记录；后续按固定 UUID 只补缺失记录，不覆盖已有修改、不删除其他数据。一轮写入在同一事务提交；同业务键被其他 UUID 占用时，数据库唯一约束使整轮失败回滚，不悄悄接管数据。此脚本用于单进程开发维护，不保证并发 Seed 的重试成功。

查询示例编号：`SEED-P001` 纯棉短袖、`SEED-P002` 连帽卫衣、`SEED-P003` 下架外套；`SEED-O001` 至 `SEED-O006` 依次为待支付、待履约、部分发货、已发货、已完成、已取消。奇数订单属于 `customer-a`，偶数属于 `customer-b`；UUID 可通过 `scripts.seed_data.seed_id("customer-a")` 等固定键获取。仅为模拟资料，不代表真实客户、商品或政策。

Migration 往返使用第三个专用空库，避免清理已经 Seed 的开发库或普通集成测试库：

```powershell
# 仅首次创建；已经存在时不要重复创建。
docker compose exec -T db createdb -U ecommerce ecommerce_ops_migration_test

$env:TEST_DATABASE_URL = & .venv/Scripts/python.exe -c 'from app.core.config import Settings; from sqlalchemy.engine import make_url; print(make_url(Settings().database_url.get_secret_value()).set(database="ecommerce_ops_test").render_as_string(hide_password=False))'
$env:MIGRATION_DATABASE_URL = & .venv/Scripts/python.exe -c 'from app.core.config import Settings; from sqlalchemy.engine import make_url; print(make_url(Settings().database_url.get_secret_value()).set(database="ecommerce_ops_migration_test").render_as_string(hide_password=False))'
.venv/Scripts/python.exe -m pytest -q
Remove-Item Env:\TEST_DATABASE_URL,Env:\MIGRATION_DATABASE_URL
```

往返测试实际依次运行 `alembic upgrade head`、`downgrade base`、`upgrade head`、`current`、`check`，并对比前后的约束和索引。只有名称以 `_migration_test` 结尾、没有业务记录及未知表的数据库才允许降级。按既有 `0001` 的设计，降级删除全部业务表及其约束/索引，保留共享扩展和 Alembic 自己的空版本表，不是删除整个数据库。没有配置该环境变量时此测试会明确 skip。

## 基础查询 Service 合约

`app/services/catalog.py` 提供商品搜索、详情和 SKU 筛选；商品搜索为转义通配符的名称子串匹配。默认仅返回 active 商品及 active SKU，不存在或不可展示商品返回 `None`，列表无匹配返回空列表。

`app/services/inventory.py` 提供 SKU 库存查询，返回各仓 `on_hand`、`reserved`、`available`、`updated_at` 和查询时间。不可展示或不存在 SKU 返回 `None`，存在 SKU 但无匹配仓库存记录返回空 `stocks`，不能解释成确定的零库存。

`app/services/orders.py` 提供订单和物流查询，必须传入服务端 `RequestContext`；`order_id`/`order_no` 二选一。`orders:read:self` 在 SQL 中限制用户归属，`orders:read:any` 才允许跨用户查询；数据库角色标签 operator 本身不授予权限。无权限、他人订单、不存在订单统一抛出 `OrderNotAccessible("order_not_accessible")`。返回类型定义于 `app/schemas/commerce.py`，不返回完整地址或用户身份字段。物流明细另外过滤同订单关系，避免异常关联泄露其他订单明细。

Service 接收短期 AsyncSession，返回 Pydantic 结构；不提交事务、不生成自然语言、不依赖 Agent/LLM。Phase 06 已提供业务 HTTP 路由，可信身份依赖默认拒绝；显式本机身份开关见文末。正式认证和运行数据库最小权限仍是对外开放业务前的前置项。

`requirements.lock` 是本轮解析出的直接和传递依赖版本约束快照；安装时配合 `-c` 使用，不包含本地路径或凭据。它不是带哈希的跨平台完整供应链锁文件。运行镜像只安装运行依赖；httpx 用于模型 Adapter，pytest 等放在 `test` 可选依赖中。

原有 [Phase 01 快照](docs/history/phase01/PROJECT_STATE.md) 继续保留；后续历史版本统一使用 Git 管理，不再生成重复文档副本。当前进度始终以根目录 PROJECT_STATE.md 为准。

## 只读 Business Tools

`app/tools/registry.py` 的固定白名单包含 `search_products`、`get_product`、`list_product_skus`、`get_inventory`、`get_order`、`get_logistics`、`search_after_sales_policy`。`get_tool(name)` 查找工具，未注册名称抛出 `KeyError`；模型调用统一经过 `invoke_tool`，未注册名称返回 `invalid_argument / unknown_tool`。`tool_schemas()` 返回输入和输出 JSON Schema；Agent 将输入 Schema 交给 OpenAI-compatible Adapter。

```python
from app.tools.registry import invoke_tool, tool_schemas

schemas = tool_schemas()
# session 和 context 只能由服务端提供；context 是已认证的 RequestContext。
result = await invoke_tool(
    "get_order", {"order_no": "SEED-O001"}, session=session, context=context,
)
payload = result.model_dump(mode="json")
```

| Tool | 参数边界 |
|---|---|
| search_products | `query` 1–200 字符，`category` 可选品类编码 1–100 字符，`limit` 1–100，默认 20 |
| get_product | 必填 `product_id` UUID |
| list_product_skus | 必填 `product_id` UUID；可选 `specs` 最多 8 项，键 1–64、值 1–100 字符；`limit` 默认 100、范围 1–100 |
| get_inventory | 必填 `sku_id` UUID；可选 `warehouse_code` 1–100 字符 |
| get_order / get_logistics | 必填 `order_no` 1–100 字符；当前 Tool 不暴露 `order_id` |
| search_after_sales_policy | `query` 1–200 字符；可选 `product_id`、`category`、带时区的 `relevant_date`、`limit` 1–100（默认 RAG_TOP_K） |

字符串过滤值去除首尾空白；`limit` 不接受布尔值、浮点数或数字字符串。所有额外字段均拒绝，包括 `actor_id`、`permissions`、`request_id`、`role`、`context` 和 `sql`。`category` 仅在适配 Service 时转换为 `category_code`。

统一 `ToolResult[T]` 包含 `status`、具体类型的 `data`、工具名 `source`、UTC `queried_at`、可信 `request_id` 和安全 `error {code, message}`。成功有 data、无 error；失败 data 为 null，并携带 error，不回显原始输入、SQL 或数据库异常。

- 商品/库存实体缺失或不可展示、商品/SKU 搜索空列表：`not_found`。
- 库存 0：`success` 且 `available=0`；缺仓库记录：`success` 且 `stocks=[]`，表示未知，不能解读成 0。
- 已授权订单无物流：`success` 且 `packages=[]`；物流保留每个包裹的 `synced_at`，外层查询时间沿用 Service 的查询时间。
- 订单 Service 始终执行授权。customer/self 范围下，他人订单和不存在订单均为 `forbidden`，不泄露存在性；可信 `orders:read:any` 范围下的缺失订单为 `not_found`。operator 标签不授权。
- 参数校验和 Service 参数错误：`invalid_argument`；连接/连接池/命令超时、断连及已识别 PostgreSQL 临时故障：`temporarily_unavailable`。代码错误、非临时数据库错误和错误输出结构继续抛出，由未来调用边界处理，不伪装成可重试故障。

Tool 不创建或提交事务，不重写 SQL/业务规则。Agent 按查询创建短期 AsyncSession，异常后关闭/回滚该会话，不在失败事务上继续查询；现有 Engine 的连接、命令和连接池超时仍生效。Phase 05 增加 RAG，没有自动重试器或新增业务 HTTP 接口，正式认证仍默认拒绝。

单元测试可运行 `.venv/Scripts/python.exe -m pytest -q tests/unit/test_tool_contracts.py`。完整 PostgreSQL 测试使用前文两个测试库环境变量执行 `pytest -q`；包含真实表锁等待超时转换和六工具只执行 SELECT 的检查。依赖、编译及 Compose 验证命令为 `python -m pip check`、`python -m compileall app tests`、`docker compose config --quiet`。

## LangGraph Read-only Agent Core

内部入口是 `app.agent.graph.run_agent(message, context=...)`，返回类型化 State；用户可见结果在 `state["final_response"]`。调用方只能提交一条用户文本，不能提交 State、Tool evidence 或任意 role 消息；追问后的新请求应附上必要的原始查询内容，实时数据重新查询。

```python
from app.agent.graph import AgentContext, run_agent
from app.agent.llm import OpenAICompatibleModel
from app.core.config import Settings
from app.db.session import create_session_factory

# engine 和 request_context 由服务端生命周期/可信身份层提供。
settings = Settings()
state = await run_agent(
    "查询订单 SEED-O001 的状态",
    context=AgentContext(
        request_context, OpenAICompatibleModel(settings),
        create_session_factory(engine), settings,
    ),
)
response = state["final_response"]
```

真实调用要求已有 `LLM_BASE_URL`（API 根路径，如带 `/v1`，不带 `/chat/completions`）、`LLM_API_KEY`、`LLM_MODEL`。缺配置不是自动化测试失败，也不会自动创建密钥。Adapter 使用 [OpenAI Chat Completions 合约](https://developers.openai.com/api/reference/resources/chat)，通过 HTTP Mock 验证消息、Tool Schema、结果关联、超时和错误转换；兼容供应商仍需支持原生 function tool_calls 和终结 JSON 指令。

图结构为 START → plan → execute_tools/answer/clarify/reject → END；工具分支可回 plan。采用 [LangGraph Runtime Context 与图步数限制](https://docs.langchain.com/oss/python/langgraph/graph-api)。`AGENT_MAX_TOOL_CALLS=8`、`AGENT_MAX_GRAPH_STEPS=24`、`AGENT_TIMEOUT_SECONDS=90`，单次模型 `LLM_TIMEOUT_SECONDS=30`；超额工具不执行，图步数/整请求超时会返回已有的部分证据。取消信号、代码缺陷继续向上传播。

模型终结输出示例：`{"action":"answer","evidence_ids":[1,2]}`、`{"action":"clarify","question":"size"}`、`{"action":"reject","reason":"write_operation"}`。问题类型为 product/sku/color/size/order/query；拒绝原因是 write_operation/policy_unavailable/unsupported。问题和拒绝文案由代码控制，intent 可选且不参与路由或授权。

回答直接引用所选成功 Tool Result 的完整 data，带来源和查询时间；不把模型生成的数字、状态、自由答案或用户自述当作证据。错误结果强制返回，部分成功为 partial，无证据为 unconfirmed；forbidden 不揭示存在性，空库存不解释为 0，物流保留同步时间。该保守模式可能较长，尚未验证真实模型的对象选择、问题相关性和语言体验。

自动化测试全部使用 Fake Model 或 httpx MockTransport；数据库仍为真实 PostgreSQL。测试入口：

```powershell
.venv/Scripts/python.exe -m pytest -q tests/unit/test_agent_core.py tests/unit/test_llm_adapter.py
# 完整回归先按前文设置 TEST_DATABASE_URL 和 MIGRATION_DATABASE_URL。
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m scripts.agent_smoke
```

`scripts.agent_smoke` 使用 Fake Model 读取已有开发 Seed，不运行 Seed、不调用外部模型。若缺少开发样例则断言失败。容器检查使用独立镜像 `ecommerce-ops-agent:phase04-check` 和临时容器，不替换已有 API。具体已运行命令见 PROJECT_STATE.md。

以上描述旧 run_agent 只读入口；Phase 06 新增的持久化 HITL/业务写接口见下节，不通过旧入口执行写入。

## Phase 05 售后知识检索

代码位于 `app/rag/`，复用现有知识表、httpx 和 pgvector，无新依赖或迁移。`data/knowledge/simulated_policies.json` 的 10 份文档全部是开发测试模拟规则，`fixture://` 是本地来源标识，不是官方网站或可访问链接。

显式入库（默认使用已配置的真实 Embedding，`--fake` 明确选择模拟向量）：

```powershell
# 仅 development/test；模拟商品范围依赖已有 Seed，不会由入库脚本自动运行 Seed。
.venv/Scripts/python.exe -m scripts.ingest_knowledge --fake
# 自备同结构 JSON；不传 --fake 时要求已有 EMBEDDING_* 配置。
.venv/Scripts/python.exe -m scripts.ingest_knowledge --source data/knowledge/simulated_policies.json
```

同一 document_key/version 使用内容 SHA-256 和元数据判断重复；一致时跳过。草稿变更会在同一事务替换旧 chunk，Embedding 失败保留旧内容；已 published/archived 版本不允许改内容或元数据，须新增版本。同内容可因模型或分块配置变化显式重建 chunk。命令整批提交，任何异常整批回滚，应用启动不执行入库。

空行分隔完整规则，目标 `RAG_CHUNK_SIZE=800` 字符、`RAG_CHUNK_OVERLAP=100` 字符；重叠仅复用整段。单段超长仍完整保留，可能超过供应商输入限制，此时入库失败而非截断规则。locator 记录规范化文档中的字符起止位置（左闭右开）及段落范围。

Embedding 配置为 `EMBEDDING_BASE_URL`（不带 `/embeddings`）、`EMBEDDING_API_KEY`、`EMBEDDING_MODEL`、可选 `EMBEDDING_DIM`、`EMBEDDING_TIMEOUT_SECONDS=30`。维度从实际响应验证，不传猜测维度；同时校验响应索引、条数、非零有限向量和模型标识。模型/版本标签必须稳定，换向量空间须重新生成；Fake 的 256 维由字符二元组哈希算法定义，不代表真实语义能力。使用 Fake 时 DIM 留空或为 256。

检索的两路候选都应用 published、`valid_from <= date < valid_to`、global/category/product 范围过滤；同 document_key 取对查询范围和日期有效的最高版本。传商品 ID 时从真实商品读取当前品类，冲突品类参数拒绝，未知或下架商品返回无结果。未提供范围时只搜全局规则。

向量通道仅计算相同模型/维度的精确余弦相似度，默认下限 `RAG_MIN_SIMILARITY=0.2`；关键词通道使用绑定并转义的整问、英文词和中文二元组子串。各取 `4 × K` 候选，通过 RRF `sum(1/(60+rank))` 去重排序，最终 K 默认 5、上限 100。没有 Reranker、复杂全文搜索或近似索引。阈值及中文召回质量需在真实模型和业务数据上重新评估。

Tool 返回文档/分块 ID、版本、title、原文、locator、source_uri、citation、适用范围、有效期、检索日期、候选来源/名次和融合分数；外层保留 queried_at。分数不是正确概率。无候选为 not_found，Embedding 未配置或不可用且需要检索时为 temporarily_unavailable，不静默降级成成功。

Agent 继续使用原图和 Evidence：订单 → 按名称快照搜索商品 → 查询 SKU 并核对订单 SKU ID → 商品政策；不能核对时不认定商品归属。`relevant_date` 是可选的带时区查询条件，省略时用现在；不是可信历史事件日期。没有历史品类快照、政策冲突自动裁决或退款批准。知识内容只进入 tool 消息，不能改变可信身份、Registry 或系统消息。

完整 Fake RAG smoke 与 Eval（先按前文配置测试库并运行迁移；结果数据回滚，不写开发业务库）：

```powershell
# TEST_DATABASE_URL 指向既有 ecommerce_ops_test。
.venv/Scripts/python.exe -m scripts.rag_smoke
# 如需记录本次结果，显式给出报告文件；已有报告请另命名以保留历史。
.venv/Scripts/python.exe -m scripts.rag_smoke --report docs/rag_eval_results.local.json
.venv/Scripts/python.exe -m compileall app scripts tests
```

Eval 数据集为 `data/knowledge/retrieval_eval.json`：7 个正常/历史查询、6 个无结果边界。正样本报告 Hit@3 和 MRR，负样本单独报告无结果准确率，另报范围正确率。实际本轮结果见 [Eval 报告](docs/rag_eval_results.json) 和 PROJECT_STATE；Fake 指标仅验证本地检索实现，不能证明真实 Embedding 或 LLM 质量。


## Phase 06 HITL 与受控写操作

本地实现只支持未付款订单取消及退款申请，不进行真实退款支付。规则、Schema 审计和事务边界见 [Phase 06 架构](docs/architecture.md#phase-06-设计审计与实现)，验证记录见 PROJECT_STATE。

```powershell
.venv/Scripts/python.exe -m pip install -c requirements.lock -e '.[test]'
.venv/Scripts/python.exe -m alembic upgrade head
.venv/Scripts/python.exe -m scripts.setup_checkpoints

# 明确启用本机固定身份；不设置时业务接口返回 401，production 禁用此选项。
$env:DEV_ACTOR_ID = & .venv/Scripts/python.exe -c 'from scripts.seed_data import seed_id; print(seed_id("customer-a"))'
.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001
# 停止该本地 API 后清理本次 shell 配置：Remove-Item Env:\DEV_ACTOR_ID
```

正常 Agent 请求需要配置已有 LLM；无 Key 时不调用付费模型，下面的 Fake smoke 可验证整个流程。固定身份不是正式登录，不应公网开放。启动命令不会自动迁移、导入或修改业务数据。

另一个 PowerShell 窗口调用（第一次请求保留 request_key，网络重试复用同一个值）：

```powershell
$requestKey = [guid]::NewGuid().ToString()
$body = @{request_key=$requestKey; message='请取消订单 SEED-O001，原因：暂时不需要了'} | ConvertTo-Json
$draft = Invoke-RestMethod http://127.0.0.1:8001/agent/requests -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
$draft | ConvertTo-Json -Depth 10
# 阅读 draft；确认时才执行下面的 confirm，也可显式改为 reject。
$confirmation = @{operation_id=$draft.operation_id; decision='confirm'} | ConvertTo-Json
Invoke-RestMethod "http://127.0.0.1:8001/agent/threads/$($draft.thread_id)/resume" -Method Post -ContentType 'application/json' -Body $confirmation
```

退款请求须明确订单号、订单明细 UUID、数量、CNY 金额和原因；缺一项先追问。一个 thread 最多一个写操作；终态后需要新 request_key 发起另一操作。重新启动 API 后，同一可信用户可 GET 原 thread 并 Resume 原 operation_id。确认后重复 Resume 返回同一结果；修改已确认选择返回 409。

真实 PostgreSQL Fake smoke 复用测试库中按随机 UUID 隔离的测试数据，实际提交事务后只清理本轮数据；不写开发订单。先按前文设置 TEST_DATABASE_URL；迁移测试还需 MIGRATION_DATABASE_URL。

```powershell
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/python.exe -m scripts.hitl_smoke hitl
.venv/Scripts/python.exe -m scripts.hitl_smoke restart
.venv/Scripts/python.exe -m scripts.hitl_smoke concurrency
.venv/Scripts/python.exe -m pip check
.venv/Scripts/python.exe -m compileall app scripts tests
docker compose config --quiet
git diff --check
```

Checkpoint infrastructure 位于 agent_checkpoints schema，显式 setup 可重复运行。测试后保留空 checkpoint 表及自有迁移版本；应用业务表迁移仍由 Alembic 0002 管理。不要通过清理 checkpoint 来“重置”已执行操作，幂等回执需要保留。当前没有数据保留/归档任务，也没有生产认证、支付、前端或复杂审批流。
