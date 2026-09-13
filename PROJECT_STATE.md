# PROJECT_STATE

> 更新：2026-09-13。先读本文件，再按任务读 [架构](docs/architecture.md)、[运行说明](README.md) 和相关代码。最新用户指令、已验证实际状态优先于本摘要；发现冲突须指出并同步。历史使用 Git，不新建重复文档备份。

## Project Goal

建设电商智能运营 Agent：模型提出查询，确定性业务代码负责权限、数据归属、规则和数据读取。覆盖商品、SKU、库存、订单、物流及售后规则问答；本地模拟验证不代表生产能力。

## Current Phase

**Phase 03 completed / awaiting Phase 04**。

- Phase 02 已提交为 `6acea32`；本轮从干净工作区开始，按用户授权完成六个只读 Business Tools、Schema、白名单、权限与错误转换测试。
- Phase 03 本地与容器验证已完成，用户审核通过；本文件随阶段关闭提交保存，提交号见 Git 历史。Phase 04 尚未开始。

## Confirmed Architecture

- V0.2，单体分层；业务 Service 直接使用 SQLAlchemy，无通用 Repository。
- 六个查询 Service 已接入受控只读 Tool；HTTP 仍只有健康接口，没有业务 HTTP 或模型入口。
- 后续设计为单 Agent、显式 State、有限工具循环；intent 只作观测，不决定权限或路由。可信上下文与模型输出分离。
- 不增加 Multi-Agent、Redis、消息队列、微服务、前端；Reranker、持久化 checkpoint 留待对应阶段确认。

## Confirmed Tech Stack

- 已验证：本地 Python 3.12.9；FastAPI 0.141.1、Uvicorn 0.52.4、SQLAlchemy 2.0.52、asyncpg 0.31.0、Alembic 1.20.0、Pydantic 2.13.5、pydantic-settings 2.15.0、pgvector Python 0.5.0。
- PostgreSQL 镜像 `pgvector/pgvector:0.8.2-pg17`；上次实查 PostgreSQL 17.10、vector 0.8.2、pg_trgm 1.6。
- pytest 9.1.1、pytest-asyncio 1.4.0、httpx 0.28.1；Docker Compose 仅 API/DB，端口只绑定本机，API 非 root 运行。
- `requirements.lock` 固定已验证依赖版本，不是带哈希的完整跨平台锁文件。本小步未改依赖、ORM 或迁移；未安装 LangGraph/模型调用依赖。

## Repository Structure

| 路径 | 职责 |
|---|---|
| `app/main.py`、`app/api/` | 应用生命周期、依赖、健康接口 |
| `app/core/config.py`、`security.py` | Settings、不可变 RequestContext |
| `app/db/base.py`、`session.py`、`models/` | 12 表、Engine、短期 AsyncSession |
| `app/schemas/commerce.py`、`tools.py` | Service 返回结构、Tool 输入和类型化 ToolResult |
| `app/services/catalog.py`、`inventory.py`、`orders.py` | 六个基础查询函数 |
| `app/tools/registry.py` | 六工具固定白名单、Service 适配、上下文传递、错误转换、Schema 导出 |
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
- `vector` 暂不固定维度，无近似向量索引；EMBEDDING_DIM 可空。未来同一检索集合必须同模型/版本、同维度，换模型/维度需重建向量，必要时新增迁移固定维度。
- 2026-09-13 最终逐库实查：`ecommerce_ops`、`ecommerce_ops_test`、`ecommerce_ops_migration_test` 均为 0001；两个测试库业务记录均为空。
- 开发库 Seed 合计 64 条：3 用户（2 customer/1 operator）、3 商品、12 SKU、12 库存、6 订单、11 明细、5 包裹、9 包裹明细、1 历史退款、2 draft 知识文档；分块、向量、审计日志均为 0。
- `SEED-O001` 至 `006` 依次覆盖待支付、待履约、部分发货、已发货、已完成、已取消；奇数归消费者甲，偶数归乙。含多包裹、active/inactive、正常/低/零可售库存。固定时间从 2026-09-01 UTC 起，均是模拟资料。

## Core Workflows

- 应用 lifespan 管理 Engine/sessionmaker；每次依赖创建并关闭独立 AsyncSession，不共享全局 Session、不在启动 create_all、不自动提交业务事务。
- `/health/live` 检查 API 存活；`/health` 有超时地执行 SELECT 1，失败 503，不检查模型或冒充迁移完整性检查。
- Catalog：`search_products`、`get_product`、`list_product_skus`；Inventory：`get_inventory`。仅展示 active 商品/SKU；无匹配返回 None/空列表，库存缺记录不等于已知零库存。
- Order：`get_order`、`get_logistics` 共用可信上下文与 SQL 归属检查，订单 ID/编号二选一；只返回结构化数据，省略完整地址/用户身份字段。
- Tool：`invoke_tool(name, arguments, session=..., context=...)` → 固定白名单 → Pydantic 校验 → Service → `ToolResult[T]`；模型参数与可信 actor_id/permissions/request_id 分离。订单 Tool 只暴露 order_no；调用方负责短期 Session 与异常后回滚/关闭。
- Seed：显式命令 → 验证 development/test → 按固定键派生 UUID → 只补缺失 → 整轮事务提交；不在生产或应用启动执行。

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

## In Progress

无。Phase 03 已审核通过并关闭，等待 Phase 04 明确任务。

## Not Started

- 正式认证、数据库运行/迁移角色分离、业务 HTTP 接入和端到端身份测试。
- LangGraph、模型客户端、RAG/Embedding、售后规则检索及 Agent Eval。
- 通用业务写入、退款/取消执行、跨行与并发写规则、HITL、幂等业务操作、业务审计、持久会话。

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

## Known Issues

- 正式认证和运行数据库最小权限尚未落实；不得将内部 Service 当作可直接公网开放的业务接口。
- Seed 的金额合计、预占、发货/退款范围和时间已检查，但普通 CHECK 不保护任意跨行业务写入；知识发布完整性/版本重叠亦未实现。
- updated_at 自动更新依赖 SQLAlchemy，直接 SQL 须自行维护；audit_logs 尚无数据库级只追加权限限制。
- Seed 不恢复手动改过的数据，非并发导入系统；物流和政策是本地模拟资料，未接真实来源。
- Phase 03 无已知阻断问题。Registry Schema 尚未与具体模型供应商对接；不可把本地 Tool 测试视为 LLM/Agent、正式认证或生产验证。临时数据库异常后，调用方须关闭/回滚 Session，不能继续复用失败事务。

## Validation Status

Phase 03 验证实际执行于 **2026-09-13，17:52（Asia/Shanghai，UTC+08:00）收尾核对**。下表 `python` 指项目 `.venv/Scripts/python.exe`。两个测试库连接通过环境变量显式传入，均为真实 PostgreSQL；以下为本轮结果。

| 本次实际执行 | 真实结果 |
|---|---|
| `python -m pytest -q` | **210 passed in 42.33s**；0 failed、0 skipped，退出码 0；包含既有 67 项和新增 143 项 |
| 测试内 upgrade → downgrade → upgrade → current → check | 专用空库往返通过；最终 0001 (head)，无 metadata 漂移；表/约束/索引一致 |
| 新 Tool PostgreSQL 集成测试 | 41 项通过；含真实 lock_timeout → temporarily_unavailable、6 工具只执行 SELECT、customer/operator 权限及身份伪造边界 |
| `python -m pip check` | No broken requirements found；退出码 0 |
| `python -m compileall app tests` | 退出码 0 |
| `docker compose config --quiet` | 退出码 0；开始时 `docker compose ps` 显示 API/DB healthy |
| `docker compose run --rm -T --no-deps --volume "${PWD}/app:/app/app:ro" --volume "${PWD}/scripts:/app/scripts:ro" api python -` | 现有 API 镜像只读挂载当前源码，6 工具、Schema、JSON、synced_at 和订单归属冒烟检查通过；查询既有开发 Seed，未执行 Seed 写入 |
| `git diff --exit-code -- app/services app/db migrations app/core app/schemas/commerce.py pyproject.toml requirements.lock` | 退出码 0，Phase 02 Service、数据模型、迁移、上下文和依赖未修改 |
| `git diff --check`、文档链接/围栏/状态结构检查 | 通过；保留固定 15 节结构，实现收尾时暂存区为空，变更仅限 4 个新文件和 3 个文档 |

阶段关闭核对：210 项测试通过后未修改代码或测试，仅更新文档；代码最后修改时间均早于 17:52:31 的最终 pytest 缓存，内容与已通过版本一致，因此按用户要求不重复完整 pytest。关闭提交仅含 Phase 03 工具、测试及说明文档，不包含敏感信息、临时文件或 Phase 04 实现。

初次回归发现测试模块同名收集冲突，以及脱敏测试把固定提示中的 input 一词误判为泄露；已修正测试文件名与断言，最终完整回归通过。没有把初次失败或静态阅读记为通过。

验证边界：本轮未重建或替换长期运行的 API 容器；容器检查使用临时容器只读挂载新源码，不代表新镜像构建/部署验证。未执行静态类型检查、真实停机演练、生产负载/备份恢复、正式认证端到端或模型调用；未实现 LangGraph/LLM/RAG。Data / Storage Design 中三库行数与版本的逐库快照仍为 Phase 02 收口记录。

## Next Recommended Step

**等待 Phase 04 明确任务**。当前 Tool 合约、可信上下文入口和测试具备后续本地编排接入条件；Phase 03 已正式关闭，本轮到此停止。正式身份来源和数据库最小权限仍是开放业务接口前的前置项，不等于生产就绪。

## Change Log

- 2026-09-12：V0.2 架构落盘；Phase 02.1 实现、40 项测试通过，随后获用户审核。
- 2026-09-12：建立基线 b06d86a；Phase 02.2 迁移往返、64 条 Seed、六个 Service、67 项测试完成，改动未提交待审核。
- 2026-09-13：按最新项目状态规范整理为 15 节，区分已有验证与恢复时的运行环境变化；未修改业务代码或进入下一阶段。

- 2026-09-13：按用户授权执行最终完整回归，67 项通过；Seed 两次无新增、健康与三库状态正常；冻结并提交 Phase 02，状态为 completed / awaiting Phase 03，未进入下一阶段。
- 2026-09-13：按授权完成 Phase 03 六个只读 Tools、结构化结果和固定白名单；新增 143 项测试，完整 210 项通过，现有容器环境冒烟检查通过；未改 Phase 02 Service/模型/迁移，未提交或进入 LangGraph。
- 2026-09-13：用户审核通过 Phase 03；仅做阶段关闭，测试后未修改代码、不重复完整 pytest；以 `feat: complete phase 03 business tools` 提交本阶段改动，状态更新为 completed / awaiting Phase 04，未开始 LangGraph/LLM/RAG。
