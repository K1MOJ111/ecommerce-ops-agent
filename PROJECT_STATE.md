# PROJECT_STATE

> 更新：2026-09-15。技术状态与验证摘要；入口见 [README](README.md)、[架构](docs/architecture.md) 和 [Eval Summary](docs/eval/eval_summary.md)。以最新明确范围和已验证仓库事实为准，历史版本由 Git 保存。

## Project Goal

建设电商智能运营 Agent：模型提出查询，确定性业务代码负责权限、数据归属、规则和数据读取。覆盖商品、SKU、库存、订单、物流及售后规则问答；本地模拟验证不代表生产能力。

## Current Phase

**Phase 07 offline completed / awaiting public release and Phase 08**。

- Phase 07 稳定提交：`75da7718e2ac35e55f072d36bd90c28c19f7b75a`；本次公开准备开始时 `master` 工作区干净。
- Agent 46 条（agent-v1.1）、RAG 33 条（rag-v2.0）、三路消融与结构化日志已实现；阶段关闭时完整 467 项测试通过。
- Live LLM / Embedding 均 blocked by missing configuration，兼容性与真实质量未验证。
- Public Release Check 已审核通过；MIT LICENSE、公开展示文档与忽略规则纳入本地收口提交 `docs: prepare public preview release`。未配置 remote、push、创建 tag/Release、部署或开始 Phase 08。

## Confirmed Architecture

- 沿用 V0.2 单体分层；Service 直接 SQLAlchemy，无通用 Repository、Multi-Agent 或前端。原 12 表与首迁移不变；订单查询和历史回放复用同一 Service 授权规则。
- 复用真实 LangGraph 的 plan → execute_tools → plan/answer/clarify/reject；新增 confirm_operation → END。七个只读 TOOLS 与两个 WRITE_TOOLS 分开，写工具只生成持久化 Draft。
- 旧 run_agent 保持无 checkpoint 的只读调用；新 start_workflow/get_workflow/resume_workflow 使用官方 PostgreSQL checkpoint 和可信 Runtime Context。模型、Session、权限不放 State；State 增加 draft/operation_result。
- agent_workflows 一表保存用户归属、初始请求键、最多一个操作、首次确认及事务结果；官方 checkpoint 四表独立在 agent_checkpoints schema。
- 实际写入前 interrupt，确认后锁内重新校验；业务变更、Audit、最终结果同事务。业务已提交但 checkpoint 失败时读持久化结果恢复。
- FastAPI 提供发起/查看/恢复接口，身份默认 401；仅显式 development/test DEV_ACTOR_ID 可启用本机固定身份，production 拒绝该配置。无正式认证、真实支付或生产部署。

## Confirmed Tech Stack

- 本地 Python 3.12.9；FastAPI 0.141.1、Uvicorn 0.52.4、SQLAlchemy 2.0.52、asyncpg 0.31.0、Alembic 1.20.0、Pydantic 2.13.5、pydantic-settings 2.15.0、pgvector Python 0.5.0。
- Phase 04 新增 LangGraph 1.2.11；传递依赖 langchain-core 1.6.3。复用 httpx 0.28.1 并列入运行依赖，无供应商 SDK。
- PostgreSQL 镜像 `pgvector/pgvector:0.8.2-pg17`；Phase 02 实查 PostgreSQL 17.10、vector 0.8.2、pg_trgm 1.6。本轮在现有 PostgreSQL 执行测试，未升级数据库。
- pytest 9.1.1、pytest-asyncio 1.4.0；Docker Compose 仅 API/DB，本机端口，非 root API。
- `requirements.lock` 为固定版本快照，Phase 06 已补新增 checkpoint 依赖；本地安装/pip check 通过。本阶段未重新构建 Linux 镜像，不是带哈希的跨平台锁。
- Phase 06 新增 langgraph-checkpoint-postgres 3.1.2、psycopg/psycopg-binary 3.3.5、psycopg-pool 3.3.1；锁文件同步必要依赖。复用官方同步 PostgresSaver + asyncio.to_thread 兼容 Windows Proactor，无全局事件循环修改。

## Repository Structure

| 路径 | 职责 |
|---|---|
| `app/main.py`、`app/api/` | 应用生命周期、可信身份、健康与 Agent 发起/查看/Resume 接口 |
| `app/core/config.py`、`security.py` | Settings、不可变 RequestContext |
| `app/db/base.py`、`session.py`、`models/` | 原 12 表 + agent_workflows、Engine、短期 AsyncSession |
| `app/schemas/commerce.py`、`tools.py` | Service 返回结构、Tool 输入和类型化 ToolResult |
| `app/services/catalog.py`、`inventory.py`、`orders.py` | 六个基础查询函数 |
| `app/tools/registry.py` | 七项只读与两项 Draft 独立白名单、可信依赖注入、错误转换、Schema 导出 |
| `app/services/operations.py`、`workflows.py`、`app/schemas/operations.py` | 业务规则、Draft、事务/Audit/回执、持久化运行与 API 合约 |
| `app/agent/checkpoint.py`、`scripts/setup_checkpoints.py`、`hitl_smoke.py` | 官方 PostgresSaver 桥接、显式初始化及三组真实 PostgreSQL 冒烟 |
| `app/agent/llm.py`、`state.py`、`graph.py` | 模型协议/Adapter、类型化 State、真实 LangGraph 和证据约束回答 |
| `app/rag/` | 文档/引用 Schema、分块入库、Embedding Adapter、Metadata Filter、向量/关键词召回与 RRF |
| `data/knowledge/` | 10 份模拟文档与 13 条 Eval 查询 |
| `scripts/ingest_knowledge.py`、`rag_eval.py`、`rag_smoke.py` | 显式入库、评估、事务回滚的完整 RAG 冒烟 |
| `docs/eval/`、`scripts/agent_eval.py` | Phase07独立数据集、评分器、消融、报告与Live配置检查 |
| `app/core/observability.py`、`scripts/eval_support.py` | 结构化运行日志与测试/Eval共享HITL隔离夹具 |
| `docs/rag_eval_results.json` | Phase 05 已验证的 Fake Eval 报告，Phase 06 未重写 |
| `scripts/agent_smoke.py` | Fake Model + 真实图/工具/数据库，只读开发 Seed 冒烟 |
| `scripts/seed_data.py` | 显式开发/测试 Seed 命令 |
| `migrations/versions/` | 保留 0001，新增 0002_agent_workflows，配合 env.py/alembic.ini |
| `tests/unit/`、`tests/integration/` | 基础、数据库、Seed/Service、迁移测试 |
| `pyproject.toml`、`requirements.lock`、Docker/Compose 配置 | 工程与运行依赖 |
| `docs/architecture.md`、`README.md` | 架构细节与可复制命令 |

初始 Git 基线：`b06d86a`；Phase 02 收口：`6acea32`。`.env`、`.venv`、缓存、IDE/临时/数据库、常见凭据文件及本地 Eval 报告被忽略；正式 Eval 报告保留追踪。历史版本由 Git 保存。

## Data / Storage Design

- Phase 06 schema change：Alembic 0002 新增 agent_workflows（owner 外键、actor/request_key 联合唯一、operation_id 唯一、状态/草稿/结果约束），不修改 0001 和原业务表。官方 checkpoint setup 独立，当前自有 migrations 为 0–9。
- 2026-09-14 本轮实查：开发库 64 条原记录、0 workflow；两个测试库应用表均为 0；开发/普通测试库 checkpoint 数据表均为 0（迁移记录保留 10 条），迁移测试库无 checkpoint schema。三库版本均为 0002。
- 下列 12 表和约束/索引数量为原 0001 基线历史，不含新增工作流表。

- 12 表：users、products、product_skus、inventory、orders、order_items、logistics、logistics_items、refunds、knowledge_documents、knowledge_chunks、audit_logs；另有 Alembic 自有版本表。
- UUID 主键、独立业务编号、TIMESTAMPTZ、NUMERIC(18,2)/Decimal、CNY 币种和历史快照；交易外键全部 RESTRICT，无删除级联。
- 实查 32 CHECK、13 外键、12 业务 UNIQUE、8 额外非唯一索引；含业务/版本表主键索引共 33 索引。
- `vector` 不固定维度，无近似向量索引；EMBEDDING_DIM 可空。Phase 05 校验实际响应维度与有限非零向量，SQL CASE 确保只计算同模型/同维度距离。换向量空间须显式重建向量；Phase 06 不修改知识 ORM/向量迁移。
- 2026-09-13 最终逐库实查：`ecommerce_ops`、`ecommerce_ops_test`、`ecommerce_ops_migration_test` 均为 0001；两个测试库业务记录均为空。
- 开发库 Seed 合计 64 条：3 用户（2 customer/1 operator）、3 商品、12 SKU、12 库存、6 订单、11 明细、5 包裹、9 包裹明细、1 历史退款、2 draft 知识文档；分块、向量、审计日志均为 0。
- `SEED-O001` 至 `006` 依次覆盖待支付、待履约、部分发货、已发货、已完成、已取消；奇数归消费者甲，偶数归乙。含多包裹、active/inactive、正常/低/零可售库存。固定时间从 2026-09-01 UTC 起，均是模拟资料。

## Core Workflows

- POST /agent/requests 接收 request_key/message；用户与 key 唯一，输入哈希不同拒绝复用。thread_id、operation_id 由可信代码生成。
- 所有 WorkflowResponse 返回共用 replay authorization：检查当前 active actor，从订单/物流成功 evidence 提取真实订单 ID，复用 orders Service 按当前权限和数据库 ownership 授权。GET、相同 request_key、终态 Resume 均经过检查；拒绝整个响应，避免 text/evidence 泄露。不调用 LLM、不重跑 Agent；公开商品证据不要求订单权限。
- 写意图 → 业务授权/规则检查 → 持久化原 Draft → LangGraph interrupt → waiting_for_confirmation；此时订单/退款/Audit 尚未改变。
- Resume：先查 active actor、当前权限和 owner，再加载 checkpoint，核对 operation_id、等待节点、原 Draft 和显式 confirm/reject；首次选择单独保存，不能改选。
- 同 thread 的图调用由 PostgreSQL advisory lock 串行；业务事务锁 workflow → order → 可选 order_item。锁内重读状态和累计额度，失败返回明确冲突。
- 取消仅本人 pending_payment/unpaid/零收款且无物流退款；退款仅足额付款订单的明细申请，校验剩余数量、按数量比例取分的明细金额、整单剩余已付额。只插入 requested，不打款、不改支付状态。
- 成功/拒绝/冲突/业务失败均保存结果与 Audit；业务 SQL 失败回滚 SAVEPOINT，Audit 失败回滚整个业务事务，允许同一确认重试；已提交结果始终幂等返回。
- 下列为保留的查询/RAG 调用链；其只读 Session 规则不代表写服务没有事务。

- 应用 lifespan 管理 Engine/sessionmaker；健康接口保持原状，SELECT 1 失败返回 503。
- `run_agent(message, context=AgentContext(...))` 只接受用户文本和服务端上下文，每次新建空 State；不接受客户端提交的 State、角色消息或 evidence。
- plan → Model.complete(messages, tools) → 原生 Tool Calls / 已校验 Decision。OpenAICompatibleModel 用 Settings 中 LLM_* 发 Chat Completions 请求；Fake Model 可替换。
- execute_tools → 每调用独立 AsyncSession → 原 invoke_tool → Pydantic 输入校验 → Service SQL/授权 → 原 ToolResult；不提交事务，结束关闭/回滚。非法/未知调用也计入工具尝试预算。
- Tool Results 含证据编号回传模型，成功数据与全部失败记录保存在 State。answer 仅呈现合法成功引用及强制失败提示；不从历史文本或模型字段补业务事实。
- 默认工具最多 8 次、图最多 24 步、单模型 30 秒、整请求 90 秒。达到工具上限后允许一次无工具模型汇总；超额不执行。整请求超时/图步数耗尽保留部分证据并补中断 Tool 消息，代码错误和主动取消继续传播。
- 商品/SKU 空列表为 not_found；库存缺记录未知而非零；已授权订单空包裹为成功空列表。self 范围他人/不存在订单同为 forbidden，orders:read:any 才能跨用户或区分缺失。
- Seed 与知识入库均为显式 development/test 命令。Phase 05 在专用测试库事务内 Seed、导入 10 份模拟文档/10 个 chunk、检索和 Agent 验证，结束回滚；未导入开发业务库。
- 政策查询：发布/有效期/范围过滤 → 精确余弦与简单关键词各取 4K → RRF 去重取 K → 原文/locator/citation → ToolResult → 原 Evidence 引用。
- 订单组合：get_order 授权 → 名称快照 search_products → list_product_skus 核对订单 sku_id → search_after_sales_policy；没有改变原业务 Service 合约。

## Completed

- Phase 02.1 infrastructure/database baseline：工程、Settings、FastAPI、12 表 ORM、Alembic、Docker 和健康检查完成，并获审核通过。
- Phase 02.2 seed data：64 条确定性模拟记录；本轮再次连续运行两次均新增 0/已有 64，无重复数据。
- Query services：六个查询 Service、结构化返回、权限/归属及物流时间测试完成；Phase 03 复用，未修改 Service。
- Migration round-trip verification：专用空库的 upgrade/downgrade/upgrade/current/check 在本次完整回归中重新通过。
- Phase 02 PostgreSQL integration testing：2026-09-13 收口回归 67 项通过；本轮完整回归包含这些既有测试。
- Git baseline：初始基线 b06d86a 已建立；Phase 02.2 源码、测试与收口文档经范围/凭据检查纳入最终提交，未新增功能。
- Phase 03 Business Tools：search_products、get_product、list_product_skus、get_inventory、get_order、get_logistics；类型化输入/输出、不可变 Registry、Schema 导出和安全错误转换。
- Phase 03 验证：新增 102 项单元用例、41 项 PostgreSQL 集成用例；总计 210 项通过，含跨用户拒绝、可信权限矩阵、身份伪造拒绝、真实表锁超时转换及 SELECT-only 检查。当前容器运行环境的六工具冒烟验证通过。
- Phase 03 阶段关闭：审核通过，按授权核对改动范围并保存 Git 提交；未增加功能或进入 Phase 04。

- Phase 04 Agent Core：可替换 OpenAI-compatible Adapter、真实 LangGraph、最小 State、可信 Runtime Context、顺序多 Tool 调用、有限循环、受控 answer/clarify/reject。
- Phase 04 验证：新增 85 项用例，完整 295 项通过；本地与独立新镜像内 Agent 六工具冒烟通过，无 live LLM 调用。
- Phase 04 阶段关闭：审核通过；核对改动、凭据与范围后按授权提交，未增加功能。


- Phase 05 RAG：10 份显式模拟文档、完整规则段落分块、SHA-256 重复识别、草稿原子更新、已发布版本保护、OpenAI-compatible/Fake Embedding、真实 pgvector 精确检索、关键词与 RRF、必要范围/有效期过滤和引用。
- Phase 05 Tool/Agent：原 Registry 第七个只读工具；注入可信 Provider，原图/State/Evidence 保持，订单 → 商品 → SKU 核对 → 政策组合通过；文档注入不能修改身份或工具边界。
- Phase 05 验证：完整 **353 passed in 51.50s**（原 295 + 52 RAG 专项 + 第七工具 6 项身份字段验证）；完整 RAG smoke 通过。13 条 Fake Eval：Hit@3=1.0、MRR=1.0、无结果准确率=1.0、范围正确率=1.0。
- Phase 05 阶段关闭：审核通过，核对范围与敏感信息后按授权提交；353 passed 后实现代码未变，不重复完整测试，未增加功能。

- Phase 06：两项固定 Draft 工具、持久化 LangGraph interrupt/resume、请求/操作唯一身份、owner/active/permissions 校验、状态重检、订单锁内金额数量约束、原子业务/Audit/回执、真实调用 API 完成。
- Phase 06 验证：新增 79 项（63 PostgreSQL HITL + 16 输入/注册/配置）；完整 432 passed，HITL/restart/concurrency smoke 均通过；独立 Python 进程恢复成功。
- Phase 06 复审修复：P1 新增 12 项回归，覆盖订单/物流撤权、any 降 self、GET/request_key、恢复权限、本人查询、公开商品和真实归属变更；拒绝 HTTP 正文精确为安全错误且不含历史证据。P2 新增 10 项，覆盖七种状态、多行/混合数量金额、整单额度和同订单不同 item 的真实 PostgreSQL 竞争。
- Phase 06 正式收口：独立复审通过；Durable HITL、PostgresSaver checkpoint、thread ownership、replay authorization、cancel order、refund request、operation draft、resume revalidation、idempotency、transaction/row locking、audit 与 API 已实现。跨 item concurrent refund cap 和状态累计/整单额度验证通过；最终完整回归及三组 smoke 已重新执行，按阶段范围提交关闭。

- Phase 07：46条独立Agent场景、33条RAG查询与离线/Live独立Runner；Fake Task/Tools/Clarify/Reject/HITL全100%，40个FinalResponse出处检查100%，安全10/10，未经授权动作与不支持声明代理率0。工具上限1/46为预期对抗场景。
- Phase 07三路检索：Vector Hit@3/MRR=0.3636/0.3636；Keyword=0.6364/0.6136；Hybrid=0.6364/0.6364。Hybrid与Keyword无结果准确率90%，Vector100%；范围均100%。主要失败为8条语义召回、1条答案不充分。
- Phase 07日志：request/model/tool/rag/interrupt/resume/completed/failed关联与耗时、调用次数、安全错误类别；Provider token数字透传由Mock验证。全量467项及离线Eval/Smoke已实际通过；Live缺配置阻塞。

- Phase 07正式收口：已审核通过离线Agent/RAG Eval与Observability，授权提交阶段成果；保留全部未验证项与Known Issues，等待公开发布和Phase08。

## In Progress

无进行中的功能开发。首次 Public Release 本地准备已审核通过，许可确定为 MIT；等待实际 GitHub 发布的明确授权。Phase 08 未开始，Live LLM/Embedding 仍未验证。

## Not Started

- 正式认证、运行/迁移数据库角色分离、Audit 只追加数据库权限、公开部署。
- 已付款订单取消、库存预留释放、复杂审批/真实退款打款、运费退款、多操作工作流、checkpoint/回执保留与归档策略。
- live LLM/Embedding 兼容性和真实质量 Eval、负载测试、当前依赖的 Linux 镜像构建；不因本地通过假定这些已验证。

## Decisions

1. 沿用 V0.2 和已审核的 0001，不重构模型。迁移往返仅用无业务行/未知表、名称以 `_migration_test` 结尾的专用库。
2. downgrade 删除业务表/约束/索引，按原迁移保留可能共享的扩展和 Alembic 空版本表，不宣称完全清空数据库。
3. Seed 选择固定业务键/UUID 的只补缺失策略：保留已有修改及非 Seed 数据，业务键冲突使整轮回滚；为单进程开发维护设计，不提供并发重试。
4. 商品搜索为转义通配符的名称字面子串匹配，SKU 按 JSONB 规格过滤；有输入长度/条数限制，无语义检索或新增文本索引。
5. `orders:read:self` 必须附加 actor 归属条件，`orders:read:any` 才能跨用户读取；operator 标签不自动授权。无权限/他人订单/不存在统一 `OrderNotAccessible`，不泄露存在性。
6. 物流明细另外限制同订单关系，防止异常关联泄露；这不替代未来写入一致性约束。当前身份依赖默认 401，仅接受未来认证层或测试显式注入。
7. 后续版本交给 Git，不新建 README_v2 等文档副本；按阶段范围冻结 Phase 02 源码和验证基线。
8. Phase 03 只增加受控 Tool 适配，不修改 Service、ORM、首迁移、依赖或认证入口。白名单为显式不可变映射，无插件、自动发现、动态导入或任意函数名执行。
9. 输入拒绝所有额外字段；字符串长度、UUID、specs 最多 8 项和 limit 1–100 由 Pydantic 校验。category 在调用 Service 时映射为 category_code；不接受模型身份、权限、角色或 SQL。
10. `ToolResult[T]` 使用 status/data/source/queried_at/request_id/error；成功必须有类型化 data，无 error；失败无 data，仅固定安全错误。商品/SKU 空结果为 not_found，库存 0 与未知库存明确区分；已授权订单无包裹为成功空列表，物流保留 synced_at。
11. Service 的 `OrderNotAccessible` 保持不变：self 范围下他人/缺失订单一律 forbidden；仅已有可信 orders:read:any 时缺失订单转 not_found。Tool 不探测隐藏订单，不复制 SQL 归属规则。
12. 参数错误、权限拒绝、无结果、已识别临时数据库/Service 故障分开。代码错误、非临时数据库错误和错误输出结构继续抛出，由未来调用边界处理；不自动重试、不吞掉取消信号、不提交事务。

13. Phase 04 删除重复的 resolved_entities，新增实际路由所需 Decision；messages 保留调用上下文，Evidence 保存带编号的原 ToolResult。
14. 用已有 httpx 实现 Chat Completions Adapter，不增加供应商 SDK；仅新增 LangGraph 及必要传递依赖。Model Protocol 支持 Fake Model，测试不依赖外部 API。
15. 业务事实采用模型选择证据、代码引用完整 data 的受控输出；不以提示词或单独的“有引用”标记作为事实保证。受控问题/拒绝类型阻止自由文案绕过。
16. 每工具独立 Session；预算计入非法/未知调用。超额、图步数、模型和整请求超时分别记录，保留已完成证据；程序缺陷和主动取消不伪装成临时故障。
17. Phase 04 当时未新增自动重试器、HTTP 业务入口、RAG/HITL/checkpoint 或写操作；该阶段新镜像只用于临时验证。Phase 05 RAG 扩展见下方决策，现有运行服务未部署更新。


18. Phase 05 复用现有知识模型和 Vector()，不固定猜测维度、不新增依赖或迁移；真实向量响应校验模型、维度和数值，Fake 字符二元组算法固定为 256 维。
19. 空行段落作为完整规则单元，目标 800 字符、整段重叠预算 100；超长单段保留完整。locator 使用规范化文档字符偏移和段落范围，引用原文不由模型生成。
20. 同 document_key/version 使用 SHA-256 加元数据判断重复；事务锁保护业务键、SAVEPOINT 保证更新失败回滚，调用方整批提交。仅草稿可修改内容/元数据，published/archived 变更须新版本；相同原文可显式重建派生 chunk。
21. 两路共同过滤 published、有效期 [valid_from, valid_to)、global/category/product，取同 key 在本次范围和日期有效的最高版本。商品当前品类从真实 Product 读取，冲突参数拒绝；scope 不代表优先级，不裁决不同文档规则冲突。
22. 向量通道精确余弦（默认最低 0.2），关键词为中文二元组/英文词/整问字面子串；每路 4K 候选，RRF sum(1/(60+rank))，最终 K 默认 5、最多 100。无 Reranker；先用真实模型/业务样本评估后再决定。
23. 政策工具不接受 order_id；relevant_date 是显式查询条件而非可信政策事件日期。这替代架构旧文中直接由 order_id 派生日期的本阶段设想，历史政策适用未完整解决。
24. 知识数据仅进入 tool 消息，固定系统消息、权限与白名单不受文本影响。Embedding 缺配置/失败返回 temporarily_unavailable，不自动退化成成功；无适用候选返回 not_found。
25. 当前不加入 Reranker：“现有 Fake Eval 没有显示排序瓶颈，因此暂无证据支持增加 Reranker；真实 Embedding + 真实业务 Query Eval 后再决定。”

26. Phase 06 经设计审计以一张 agent_workflows 合并归属/操作/幂等回执，替代原“本阶段不新增表”的历史限制；没有修改已确认业务模型。
27. 本阶段一请求最多一个不可编辑的操作，首次 confirm/reject 不可翻转。状态变化需新请求、新确认；不自动修改原 Draft。
28. paid pending_fulfillment 的取消需要订单级库存预留归属，当前没有可靠释放数据，因此仅允许未付款取消，不凭总 reserved 推算。
29. refund_no 使用 OP-{operation_id} 复用现有 UNIQUE；workflow 行锁、唯一 operation_id 与同事务回执形成幂等保证，订单锁串行化不同退款申请的累计额度校验。
30. official PostgresSaver 的同步方法用标准库线程桥接，避免 Windows Proactor 异步 psycopg 错误；基础表由独立 setup 显式初始化。Audit 失败必须业务全回滚，失败节点仅在原草稿/同一持久化确认匹配时重试。
31. Reject 不更改业务订单/退款，但写审计和拒绝回执；预草稿失败保留 ToolResult/检查点，数据库整体失败不能保证额外失败 Audit，API 不回显底层异常。
32. 历史缓存不是授权凭证。公共 response 入口按 evidence source 映射受保护资源，去重后调用 authorize_order_access，复用 _authorized_order 的 any/self 与真实 ownership 检查，不加载明细或重建历史结果；新增受保护 source 时在此扩展其所属 Service 授权。
33. 退款 requested/approved/processing/succeeded 占用数量和金额，rejected/failed/cancelled 不占用。整单独立上限测试显式构造数据库允许的历史不一致：整单折扣未分摊到 item，使整单剩余额小于明细剩余额；这是防御性约束验证，不改变当前退款业务规则。
34. P3 draft JSONB 与列字段完整绑定 CHECK 留给 Final Hardening；本轮保留应用层保护，不新增 Schema 修改。

35. Eval Dataset与测试分开；Fake预设脚本只能验证执行轨迹，不能推导语言理解能力。评分oracle不进入Live Prompt；最终证据不强制包含中间查询。数据版本及修改理由记录在dataset。
36. 复用原RAG函数增加内部vector/keyword/hybrid选择，业务工具仍默认Hybrid且不暴露mode；不改变现有检索阈值或模型行为来迎合Eval。
37. 当前不增加Reranker：Fake仅1个查询排序改善，主要瓶颈是漏召回和无答案误召回；待真实Embedding证据。
38. 使用标准库logging/ContextVar、白名单字段与perf_counter，不永久记录完整ToolResult。开发日志、业务Audit和Eval报告分开；修复迁移fileConfig关闭已有logger的Eval阻断，未修改数据库Schema。
39. HITL评估复用从Phase06提取的隔离夹具；只读Eval事务回滚，持久化场景按本轮UUID清理。Live LLM固定10条子集，不自动扩大，Live Embedding与Fake分开入库回滚。

## Known Issues

- 正式认证、DB 最小权限角色、Audit 防篡改尚未实现；DEV_ACTOR_ID 只供本机模拟，不等于登录系统。production deployment、backup / restore、load validation 尚未完成。
- JSONB CHECK hardening（P3 deferred）：agent_workflows.draft JSONB 内 operation_type、actor、operation_id 与列字段缺少完整数据库绑定 CHECK；保留现有应用层校验和已有数据库约束，留给 Final Hardening，不作为本轮关闭条件，未为此修改 Schema。
- 已付款取消不支持；取消不释放库存。退款仅申请，非审批/打款；不退运费，按数量分摊向下取分，可能保守留下一分以内余数。每请求一个操作，待确认参数不能编辑。
- 未来支付/物流/审批等写入必须遵守父订单锁与重新校验协议；直接 SQL/数据库管理员绕过不在保证内。回执/checkpoint 未设计保留清理策略，不能随意删除幂等记录。
- data retention：模型/用户消息和必要查询数据会存入 checkpoint；尚无业务隐私保留/归档策略；可信 Context、API Key、Session 不序列化。仅允许的 State 类型可反序列化，pickle 关闭。
- live LLM compatibility 未验证：缺配置，报告为 blocked；Fake Agent 46/46 仅代表确定性离线工作流测试，不代表真实模型能力。
- live Embedding / real retrieval quality 未验证：缺配置，报告为 blocked。
- RAG conversational/synonym recall 不足：口语/同义表达漏召回，当前 Hybrid 正例漏8/22。
- unknown-price / answer sufficiency 问题：相关政策片段不含所问金额答案，无结果判断仍有不足。当前瓶颈主要在 Recall 和 answer sufficiency，没有证据支持增加 Reranker。
- checkpoint enum deserialization warning：Phase07运行中出现对OrderStatus/PaymentStatus枚举的反序列化白名单警告；本轮场景通过但未修复恢复完整性隐患，待后续单独审查，不直接放宽白名单。
- Grounding保证当前结构化资料可追溯，不证明知识内容可信、足以回答问题或适用历史订单；这些需要人工/真实模型评审。当前日志覆盖Agent执行入口，历史GET无独立执行span；没有生产日志保留/聚合方案。
- RAG 历史事件日期、商品品类快照、政策冲突和下架映射仍未完整解决；引用不等于退款批准。向量空间/长文/引用生命周期限制延续 Phase 05，详见架构与 README。
- 当前依赖组合尚未重新构建/部署 Linux API 镜像。

## Validation Status

### Public Release 本地准备（2026-09-15）

- 起始 HEAD 为 `75da7718e2ac35e55f072d36bd90c28c19f7b75a`，`master` 工作区干净；仓库非 shallow。检查全部本地对象（含所有引用、reflog 与悬空对象）：7 commit、118 tree、167 blob，无二进制 blob；`git fsck --full --no-reflogs` 无损坏，仅报告悬空对象。历史没有删除文件记录，所有历史版本仍逐对象扫描。
- 凭据格式、赋值、连接 URL、私钥、手机号/证件、邮箱、本地路径及高熵字符串检查，并复核命中内容与 Seed/Fixture 来源：未发现真实凭据、客户数据或个人绝对路径。本地实际数据库密码与全部历史 blob 比对无命中；示例密码和 Mock 字符串保留。提交身份为昵称与 example.com 示例邮箱，公开提交仍会展示该昵称。
- 公开追踪内容与已忽略本机配置分开；扫描不是凭据有效性验证，也不代表未来新增文件自动安全。未重写历史或清理 Git 对象。
- 静态检查：20 个 Markdown 本地链接/标题目标与代码围栏、全部追踪 JSON 解析、Eval 指标与语料校验、25 项忽略/保留断言、README 4 个 PowerShell 代码块语法、Eval CLI help、Compose 配置、差异范围及 `git diff --check` 均通过。没有新增运行依赖。
- 公开准备最终范围为 4 个 Markdown 文件、`.gitignore` 及 MIT LICENSE，未改业务代码、数据集或报告；未重跑 467 tests、Live API、首次安装/启动流程或 Linux 镜像构建，也未做 GitHub 页面实际渲染验证。
- Public Release Check 已审核通过，MIT 许可已确认并添加；本地收口提交消息为 `docs: prepare public preview release`。未配置 remote、push、创建 tag/Release 或开始 Phase 08。
- MIT 收口检查：标准许可正文与本地已安装包的 MIT 原文一致，README 入口有效，6 文件范围核对通过；`git diff --check` 与 `docker compose config --quiet` 实际执行均退出 0。纯文档与许可改动未重跑完整测试。

### Phase 07 验证记录

以下为 **Phase 07 阶段关闭验证：2026-09-15（Asia/Shanghai）**，不是公开文档准备重新运行的结果。Python 使用工作区 `.venv/Scripts/python.exe`。详细指标与计算方法见 [Eval Summary](docs/eval/eval_summary.md)，历史 Phase 06 的454项仍包含在完整回归中。

| 执行 | Phase 07 保存的真实结果 |
|---|---|
| `python -m pytest -q` | **467 passed in 78.36s**，0 failed / 0 skipped；包含真实 PostgreSQL、HITL安全及迁移往返 |
| `python -m pip check` | No broken requirements found，退出0 |
| `python -m compileall app scripts tests` | 退出0 |
| `docker compose config --quiet` / `git diff --check` | 退出0；仅LF/CRLF提示 |
| `python -m scripts.agent_eval agent --replace` | agent-v1.1，46/46通过；脚本化控制实验，不是模型理解准确率 |
| `python -m scripts.agent_eval rag --replace` | rag-v2.0，33查询×3路；Fake 256维，Hybrid Hit@3=14/22、MRR=0.6364，范围100%，无结果9/10，参数拒绝1/1 |
| `python -m scripts.agent_eval smoke` | 5场景通过，9种必需事件与关联检查通过 |
| `python -m scripts.agent_eval agent --live` | blocked by missing configuration，0例；未调用付费API |
| `python -m scripts.agent_eval rag --live` | blocked by missing configuration，0例；未验证真实语义召回 |
| 本地性能 | 48次完成请求p50=42.439ms / p95=129.253ms；50次发起/恢复调用共50次Tool、82次LLM complete；token=null，非生产P95 |
| 运行后数据库检查 | 开发库64条、0workflow/0checkpoint；两个测试库应用表全0、普通测试库checkpoint数据全0；三库Alembic=0002 |

收口核对：最终467 passed后实现逻辑未变；本轮为通过暂存差异检查，仅移除 scripts/eval_support.py 的一个末尾空行，Python AST核对相同。补跑受影响的 `python -m pytest -q tests/integration/test_hitl.py`：**85 passed in 33.48s**；未重复完整测试。其余仅更新收口文档，并检查Git差异、范围、报告一致性与敏感信息。

过程中日志配置禁用logger、Docker停止和新测试夹具不完整曾导致失败；已修复/恢复后重新完整运行，上表仅为最终结果。未构建/部署镜像，未执行生产认证、真实API、负载或备份恢复验证。

## Next Recommended Step

**等待 GitHub 实际发布的明确授权。** Public Release Check 已通过，许可为 MIT。推荐以 `v0.7-preview` 表示 Phase 07 的 Stable Preview；这是候选 Git 标签，尚未创建。`pyproject.toml` 包版本仍为 `0.2.0`，本次未改，不能声称已发布 0.7 包。

随后另行明确授权 GitHub 实际发布；Phase 08 仍未开始。优先待验证项仍为 Live 兼容性与真实检索质量，待解决问题仍为口语/同义召回、unknown-price 答案充分性和 checkpoint 枚举警告；其余 Final Hardening 保留在 Known Issues，不随公开准备实施。

## Change Log

- 2026-09-15：公开准备审核通过，添加标准 MIT LICENSE（Copyright 2026 K1MOJ1）及 README 许可入口，以 `docs: prepare public preview release` 本地提交收口；仅文档/忽略规则/许可，无核心代码变更。未配置 remote、push、创建 tag/Release 或开始 Phase 08。
- 2026-09-15：首次公开准备，整理 README、架构和 Eval 说明，补充缓存及本地报告忽略规则；完整本地 Git 对象检查未发现真实凭据或客户资料。改动未提交，LICENSE 未添加，未配置远程或发布；Phase 08 未开始。
- 2026-09-15：Phase 07 在 `75da771` 关闭；Agent 46 / RAG 33、三路消融、结构化日志和 smoke 完成。完整 467 passed，之后仅夹具末尾空行调整，AST 不变，HITL 补跑 85 passed；Live 两项 blocked。
- 2026-09-15：Phase 06 在 `d570374` 正式关闭；历史证据回放授权与跨明细退款额度复审通过，完整 454 passed，HITL / restart / concurrency smoke 为 4 / 3 / 5 passed；P3 JSONB CHECK 加固延期。
- 2026-09-14：Phase 05 在 `39ca227` 关闭；第七个只读工具、RAG、353 项测试与 13 条 Fake Eval 完成，未执行 Live 验证。
- 2026-09-14：Phase 04 在 `5721ef8` 关闭；只读 LangGraph Agent、295 项测试及本地/独立容器 smoke 完成，未调用真实 LLM。
- 2026-09-13：Phase 03 在 `0090e3b` 关闭；六个只读工具、210 项测试及容器 smoke 完成。
- 2026-09-13：Phase 02 在 `6acea32` 关闭；数据库、64 条模拟 Seed、查询服务、迁移往返及 67 项测试完成。
- 2026-09-12：V0.2 设计与基础设施基线 `b06d86a` 建立；原 Phase 01 文档保留作历史设计快照。
