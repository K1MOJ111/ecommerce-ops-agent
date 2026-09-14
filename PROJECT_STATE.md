# PROJECT_STATE

> 更新：2026-09-14。先读本文件，再按任务读 [架构](docs/architecture.md)、[运行说明](README.md) 和相关代码。最新用户指令、已验证实际状态优先于本摘要；发现冲突须指出并同步。历史使用 Git，不新建重复文档备份。

## Project Goal

建设电商智能运营 Agent：模型提出查询，确定性业务代码负责权限、数据归属、规则和数据读取。覆盖商品、SKU、库存、订单、物流及售后规则问答；本地模拟验证不代表生产能力。

## Current Phase

**Phase 05 completed / awaiting Phase 06**。

- Phase 04 基线为 `5721ef8`；本轮进入时 Git 工作区干净。
- Phase 05 售后 RAG 完整本地链路已实现、353 项完整测试及真实 PostgreSQL Fake RAG smoke 通过，用户已审核通过。
- Phase 05 正式关闭，本文件随阶段关闭提交保存；提交号见 Git 历史。Phase 06 尚未开始，不发布或部署。

## Confirmed Architecture

- 沿用 V0.2 单体分层，Service 直接使用 SQLAlchemy，无通用 Repository；原 Business Services/ORM/迁移及可信 RequestContext 未改，Registry 最小扩展第七工具。
- 真实 LangGraph 单 Agent：START → plan → execute_tools/answer/clarify/reject；工具分支有界返回 plan，终结节点到 END。
- plan 通过可替换 Model 读取用户消息与工具结果，提出原生 Tool Calls 或类型化终结动作。执行只能走七个只读工具的 Registry；第七项为售后规则检索。
- State 不含 Session、客户端或可信身份；AgentContext 通过 LangGraph runtime context 注入身份、Model、Session 工厂、Settings 与可选 Embedding Provider。
- answer 使用模型选择的成功证据编号，由代码引用完整 Tool data，不接受模型提供的事实值；追问/拒绝使用受控类型。
- HTTP 仍只有健康接口，正式身份依赖默认拒绝；无业务 HTTP、HITL、checkpoint、业务写操作、前端或 Multi-Agent；RAG 为内部只读工具。

## Confirmed Tech Stack

- 本地 Python 3.12.9；FastAPI 0.141.1、Uvicorn 0.52.4、SQLAlchemy 2.0.52、asyncpg 0.31.0、Alembic 1.20.0、Pydantic 2.13.5、pydantic-settings 2.15.0、pgvector Python 0.5.0。
- Phase 04 新增 LangGraph 1.2.11；传递依赖 langchain-core 1.6.3。复用 httpx 0.28.1 并列入运行依赖，无供应商 SDK。
- PostgreSQL 镜像 `pgvector/pgvector:0.8.2-pg17`；Phase 02 实查 PostgreSQL 17.10、vector 0.8.2、pg_trgm 1.6。本轮在现有 PostgreSQL 执行测试，未升级数据库。
- pytest 9.1.1、pytest-asyncio 1.4.0；Docker Compose 仅 API/DB，本机端口，非 root API。
- `requirements.lock` 为 Phase 04 固定版本快照，该阶段独立 Linux 镜像安装通过；Phase 05 未改依赖，本地 pip check 通过，未重新构建镜像。不是带哈希的跨平台锁。
- langgraph-checkpoint 等包是 LangGraph 传递依赖，项目没有配置 checkpointer 或持久化会话。

## Repository Structure

| 路径 | 职责 |
|---|---|
| `app/main.py`、`app/api/` | 应用生命周期、依赖、健康接口 |
| `app/core/config.py`、`security.py` | Settings、不可变 RequestContext |
| `app/db/base.py`、`session.py`、`models/` | 12 表、Engine、短期 AsyncSession |
| `app/schemas/commerce.py`、`tools.py` | Service 返回结构、Tool 输入和类型化 ToolResult |
| `app/services/catalog.py`、`inventory.py`、`orders.py` | 六个基础查询函数 |
| `app/tools/registry.py` | 七工具固定白名单、Service 适配、可信依赖注入、错误转换、Schema 导出 |
| `app/agent/llm.py`、`state.py`、`graph.py` | 模型协议/Adapter、类型化 State、真实 LangGraph 和证据约束回答 |
| `app/rag/` | 文档/引用 Schema、分块入库、Embedding Adapter、Metadata Filter、向量/关键词召回与 RRF |
| `data/knowledge/` | 10 份模拟文档与 13 条 Eval 查询 |
| `scripts/ingest_knowledge.py`、`rag_eval.py`、`rag_smoke.py` | 显式入库、评估、事务回滚的完整 RAG 冒烟 |
| `docs/rag_eval_results.json` | 本轮实际 Fake Eval 报告 |
| `scripts/agent_smoke.py` | Fake Model + 真实图/工具/数据库，只读开发 Seed 冒烟 |
| `scripts/seed_data.py` | 显式开发/测试 Seed 命令 |
| `migrations/versions/0001_initial_schema.py` | 首迁移，配合 env.py/alembic.ini |
| `tests/unit/`、`tests/integration/` | 基础、数据库、Seed/Service、迁移测试 |
| `pyproject.toml`、`requirements.lock`、Docker/Compose 配置 | 工程与运行依赖 |
| `docs/architecture.md`、`README.md` | 架构细节与可复制命令 |

初始 Git 基线：`b06d86a`；Phase 02 收口：`6acea32 feat: complete phase 02 data and query services`。Phase 03 开始时工作区干净，4 个新文件、3 个文档修改随 `feat: complete phase 03 business tools` 阶段关闭提交纳入版本控制。未修改全局 Git 配置、配置远程或推送。`.env`、`.venv`、缓存、IDE/临时/数据库及常见凭据文件被忽略；历史文档由 Git 保留，不新建重复副本。

## Data / Storage Design

- 12 表：users、products、product_skus、inventory、orders、order_items、logistics、logistics_items、refunds、knowledge_documents、knowledge_chunks、audit_logs；另有 Alembic 自有版本表。
- UUID 主键、独立业务编号、TIMESTAMPTZ、NUMERIC(18,2)/Decimal、CNY 币种和历史快照；交易外键全部 RESTRICT，无删除级联。
- 实查 32 CHECK、13 外键、12 业务 UNIQUE、8 额外非唯一索引；含业务/版本表主键索引共 33 索引。
- `vector` 不固定维度，无近似向量索引；EMBEDDING_DIM 可空。Phase 05 校验实际响应维度与有限非零向量，SQL CASE 确保只计算同模型/同维度距离。换向量空间须显式重建向量；本轮不修改 ORM/迁移。
- 2026-09-13 最终逐库实查：`ecommerce_ops`、`ecommerce_ops_test`、`ecommerce_ops_migration_test` 均为 0001；两个测试库业务记录均为空。
- 开发库 Seed 合计 64 条：3 用户（2 customer/1 operator）、3 商品、12 SKU、12 库存、6 订单、11 明细、5 包裹、9 包裹明细、1 历史退款、2 draft 知识文档；分块、向量、审计日志均为 0。
- `SEED-O001` 至 `006` 依次覆盖待支付、待履约、部分发货、已发货、已完成、已取消；奇数归消费者甲，偶数归乙。含多包裹、active/inactive、正常/低/零可售库存。固定时间从 2026-09-01 UTC 起，均是模拟资料。

## Core Workflows

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

- Phase 02.1 infrastructure/database baseline：工程、Settings、FastAPI、12 表 ORM、Alembic、Docker 和健康检查完成，并获用户审核通过。
- Phase 02.2 seed data：64 条确定性模拟记录；本轮再次连续运行两次均新增 0/已有 64，无重复数据。
- Query services：六个查询 Service、结构化返回、权限/归属及物流时间测试完成；Phase 03 复用，未修改 Service。
- Migration round-trip verification：专用空库的 upgrade/downgrade/upgrade/current/check 在本次完整回归中重新通过。
- Phase 02 PostgreSQL integration testing：2026-09-13 收口回归 67 项通过；本轮完整回归包含这些既有测试。
- Git baseline：初始基线 b06d86a 已建立；Phase 02.2 源码、测试与收口文档经范围/凭据检查纳入最终提交，未新增功能。
- Phase 03 Business Tools：search_products、get_product、list_product_skus、get_inventory、get_order、get_logistics；类型化输入/输出、不可变 Registry、Schema 导出和安全错误转换。
- Phase 03 验证：新增 102 项单元用例、41 项 PostgreSQL 集成用例；总计 210 项通过，含跨用户拒绝、可信权限矩阵、身份伪造拒绝、真实表锁超时转换及 SELECT-only 检查。当前容器运行环境的六工具冒烟验证通过。
- Phase 03 阶段关闭：用户审核通过，按授权核对改动范围并保存 Git 提交；未增加功能或进入 Phase 04。

- Phase 04 Agent Core：可替换 OpenAI-compatible Adapter、真实 LangGraph、最小 State、可信 Runtime Context、顺序多 Tool 调用、有限循环、受控 answer/clarify/reject。
- Phase 04 验证：新增 85 项用例，完整 295 项通过；本地与独立新镜像内 Agent 六工具冒烟通过，无 live LLM 调用。
- Phase 04 阶段关闭：用户审核通过；核对改动、凭据与范围后按授权提交，未增加功能。


- Phase 05 RAG：10 份显式模拟文档、完整规则段落分块、SHA-256 重复识别、草稿原子更新、已发布版本保护、OpenAI-compatible/Fake Embedding、真实 pgvector 精确检索、关键词与 RRF、必要范围/有效期过滤和引用。
- Phase 05 Tool/Agent：原 Registry 第七个只读工具；注入可信 Provider，原图/State/Evidence 保持，订单 → 商品 → SKU 核对 → 政策组合通过；文档注入不能修改身份或工具边界。
- Phase 05 验证：完整 **353 passed in 51.50s**（原 295 + 52 RAG 专项 + 第七工具 6 项身份字段验证）；完整 RAG smoke 通过。13 条 Fake Eval：Hit@3=1.0、MRR=1.0、无结果准确率=1.0、范围正确率=1.0。
- Phase 05 阶段关闭：用户审核通过，核对范围与敏感信息后按授权提交；353 passed 后实现代码未变，不重复完整测试，未增加功能。

## In Progress

无。Phase 05 已审核通过并关闭，等待 Phase 06 明确任务。

## Not Started

- 正式认证、数据库运行/迁移角色分离、业务 HTTP 接入和端到端身份测试。
- 真实 Embedding/LLM 的兼容性和业务质量 Eval；RAG 本地实现已完成，没有 Reranker。
- 通用写入、退款/取消执行、并发写规则、HITL、幂等操作、业务审计、checkpoint/持久会话。
- live Embedding 与 Phase 04 遗留 live LLM smoke：本地均未配置 Key，本轮未执行。

## Decisions

1. 沿用 V0.2 和已审核的 0001，不重构模型。迁移往返仅用无业务行/未知表、名称以 `_migration_test` 结尾的专用库。
2. downgrade 删除业务表/约束/索引，按原迁移保留可能共享的扩展和 Alembic 空版本表，不宣称完全清空数据库。
3. Seed 选择固定业务键/UUID 的只补缺失策略：保留已有修改及非 Seed 数据，业务键冲突使整轮回滚；为单进程开发维护设计，不提供并发重试。
4. 商品搜索为转义通配符的名称字面子串匹配，SKU 按 JSONB 规格过滤；有输入长度/条数限制，无语义检索或新增文本索引。
5. `orders:read:self` 必须附加 actor 归属条件，`orders:read:any` 才能跨用户读取；operator 标签不自动授权。无权限/他人订单/不存在统一 `OrderNotAccessible`，不泄露存在性。
6. 物流明细另外限制同订单关系，防止异常关联泄露；这不替代未来写入一致性约束。当前身份依赖默认 401，仅接受未来认证层或测试显式注入。
7. 后续版本交给 Git，不新建 README_v2 等文档副本；按用户授权冻结 Phase 02 源码和验证基线。
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
23. 根据本轮要求，政策工具不接受 order_id；relevant_date 是显式查询条件而非可信政策事件日期。这替代架构旧文中直接由 order_id 派生日期的本阶段设想，历史政策适用未完整解决。
24. 知识数据仅进入 tool 消息，固定系统消息、权限与白名单不受文本影响。Embedding 缺配置/失败返回 temporarily_unavailable，不自动退化成成功；无适用候选返回 not_found。
25. 当前不加入 Reranker：“现有 Fake Eval 没有显示排序瓶颈，因此暂无证据支持增加 Reranker；真实 Embedding + 真实业务 Query Eval 后再决定。”

## Known Issues

- 无已知阻断本轮本地实现验收的故障；正式认证、数据库最小权限及业务 HTTP 尚未落实，不代表生产就绪。
- live Embedding 尚未验证；live LLM Tool Calling 尚未验证。本地 Key 未配置，Mock/Fake 通过不证明供应商兼容、真实语义召回、模型工具选择或语言体验。
- 当前 Retrieval Eval 只有 13 条模拟样本（7 正样本、6 无结果边界）；Hit@3 / MRR = 1.0 仅代表 Fake Embedding 回归结果，不代表真实检索质量。真实中文别名/错字、阈值和长文需后续实测。
- relevant_date 仅过滤；未自动决定订单应按创建/付款/签收哪个事件选规则，使用当前商品品类，未处理历史品类快照、下架商品映射或不同文档的规则冲突。引用不等于退款批准。
- Embedding 模型/版本标签需稳定；服务商若在相同标签下变更向量空间，不能仅靠维度发现，须主动换版本标签并重建。没有近似索引或大规模负载验证。
- 超长单段保持完整，可能超出供应商输入限制；入库失败保留旧数据。没有复杂解析、自动拆分超长规则或分批供应商请求。
- 原文版本不可变，但显式重建 chunk 会变更 chunk_id；当前不保存历史会话，持久引用寿命需在后续持久化阶段处理。
- Agent 仍输出完整证据，可能冗长；不保证模型已查全问题、选对所有对象或识别每个语义注入。测试验证权限/白名单/系统消息不可由知识文本提升，不宣称模型完全免疫提示注入。
- 单请求无 checkpoint/恢复。超时为 asyncio 协作取消，未改变原运行服务或部署。

## Validation Status

Phase 05 实际验证：**2026-09-14（Asia/Shanghai）**；下列 python 指 `.venv/Scripts/python.exe`。

| 实际执行 | 真实结果 |
|---|---|
| `python -m pytest -q` | **353 passed in 51.50s**，0 failed、0 skipped；含真实 PostgreSQL 和专用空库迁移往返 |
| RAG 专项 | 52 项通过，覆盖入库/重复/版本/内容变更/原子失败、过滤/有效期边界、vector/keyword/RRF/Top-K、引用对应、异维异模型隔离、Tool 状态、Agent 多工具与注入边界 |
| `python -m pip check` | No broken requirements found，退出码 0 |
| `python -m compileall app scripts tests` | 退出码 0 |
| `docker compose config --quiet` | 退出码 0 |
| `git diff --check` | 通过；Windows LF/CRLF 提示不是空白错误 |
| `git diff --exit-code -- app/db app/services app/schemas app/core/security.py migrations pyproject.toml requirements.lock` | 退出码 0；原模型/Service/Schema/身份/迁移/依赖未变 |
| `python -m scripts.rag_smoke --report docs/rag_eval_results.json` | 真实 PostgreSQL/pgvector + Fake Embedding + 原 Registry/LangGraph/Evidence 全链路通过；事务回滚 |
| Retrieval Eval | `data/knowledge/retrieval_eval.json`：7 正样本、6 无结果样本，K=3；Hit@3=1.0、MRR=1.0、无结果准确率=1.0、范围正确率=1.0；逐条结果见 `docs/rag_eval_results.json` |
| live Embedding | 未执行：EMBEDDING_API_KEY 未配置，不记为通过或失败 |
| live LLM | 未执行：LLM_API_KEY 未配置，Phase 04 遗留项仍未验证 |
| 测试后逐库只读计数 | `ecommerce_ops_test`、`ecommerce_ops_migration_test` 业务表行数均为 0，确认未遗留测试记录 |

pytest 子进程从 Settings 安全派生既有 `ecommerce_ops_test` 和 `ecommerce_ops_migration_test` URL，不输出凭据；迁移往返仅作用于专用空库。RAG smoke 同样在测试库外层事务内运行并回滚，未提交开发数据。未执行新镜像构建、部署、真实模型质量评估、正式认证端到端、负载或静态类型检查。

阶段关闭核对：353 passed 后没有修改实现代码，仅更新文档/生成 Eval 报告；当前 app/scripts/tests 的 Python 源码修改时间均早于该次 pytest 缓存更新时间，与本任务执行记录一致。本轮仅更新阶段关闭文档，不重复完整测试。22 个阶段文件均属于 Phase 05，未发现本地凭据值、常见密钥模式、待提交临时文件或提前实现的 HITL/Checkpoint/业务写操作；知识入库写入属于已审核的 Phase 05 范围。原 Business Services、ORM、迁移、业务 Schema、可信身份及依赖文件未改。

## Next Recommended Step

**等待 Phase 06 明确任务**。Phase 05 已获用户审核并正式关闭，具备下一阶段基础；本轮到此停止，不开始 HITL、Checkpoint 或业务写操作。live API 和真实检索质量保持未验证，Reranker 决策遵循第 25 项。

## Change Log

- 2026-09-12：V0.2 架构落盘；Phase 02.1 实现、40 项测试通过，随后获用户审核。
- 2026-09-12：建立基线 b06d86a；Phase 02.2 迁移往返、64 条 Seed、六个 Service、67 项测试完成，改动未提交待审核。
- 2026-09-13：按最新项目状态规范整理为 15 节，区分已有验证与恢复时的运行环境变化；未修改业务代码或进入下一阶段。

- 2026-09-13：按用户授权执行最终完整回归，67 项通过；Seed 两次无新增、健康与三库状态正常；冻结并提交 Phase 02，状态为 completed / awaiting Phase 03，未进入下一阶段。
- 2026-09-13：按授权完成 Phase 03 六个只读 Tools、结构化结果和固定白名单；新增 143 项测试，完整 210 项通过，现有容器环境冒烟检查通过；未改 Phase 02 Service/模型/迁移，未提交或进入 LangGraph。
- 2026-09-13：用户审核通过 Phase 03；仅做阶段关闭，测试后未修改代码、不重复完整 pytest；以 `feat: complete phase 03 business tools` 提交本阶段改动，状态更新为 completed / awaiting Phase 04，未开始 LangGraph/LLM/RAG。

- 2026-09-14：完成 Phase 04 Read-only LangGraph Agent Core；新增 85 项测试，完整 295 项通过，本地和独立容器六工具冒烟通过；未配置真实 LLM，未执行 live smoke；更新架构/README，工作区待用户审核，停止在本阶段。

- 2026-09-14：用户审核通过 Phase 04；仅更新阶段关闭状态并按授权以 `feat: complete phase 04 langgraph agent core` 提交。295 passed 后实现代码未变，不重复完整 pytest；状态为 completed / awaiting Phase 05，后续阶段未开始。

- 2026-09-14：Phase 05 RAG 本地链路完成；未改原 ORM/迁移/Business Services，新增第七只读 Tool，353 项完整测试与真实 PostgreSQL Fake smoke 通过，13 条 Eval 指标见报告。未配置 live API，工作区待审核，未提交/部署/进入下一阶段。

- 2026-09-14：用户审核通过 Phase 05；仅做阶段关闭，保留 Known Issues 和 Reranker 决策，按授权以 `feat: complete phase 05 rag knowledge retrieval` 提交。353 passed 后实现代码未改，不重复完整测试；状态为 completed / awaiting Phase 06，未开始后续功能。
