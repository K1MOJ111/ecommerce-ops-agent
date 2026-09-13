# PROJECT_STATE

> 更新：2026-09-13。先读本文件，再按任务读 [架构](docs/architecture.md)、[运行说明](README.md) 和相关代码。最新用户指令、已验证实际状态优先于本摘要；发现冲突须指出并同步。历史使用 Git，不新建重复文档备份。

## Project Goal

建设电商智能运营 Agent：模型提出查询，确定性业务代码负责权限、数据归属、规则和数据读取。覆盖商品、SKU、库存、订单、物流及售后规则问答；本地模拟验证不代表生产能力。

## Current Phase

**Phase 02 completed / awaiting Phase 03**。

- Phase 02.1 基础设施/数据库基线已通过审核；Phase 02.2 已按用户授权完成最终回归和 Git 收口。
- 当前仅等待下一阶段的明确任务；本轮没有开始 Phase 03 或新增功能。

## Confirmed Architecture

- V0.2，单体分层；业务 Service 直接使用 SQLAlchemy，无通用 Repository。
- 当前仅健康 HTTP 接口；六个查询 Service 尚未接入业务 HTTP 或 Agent Tool。
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
| `app/schemas/commerce.py` | 查询返回的 Pydantic 结构 |
| `app/services/catalog.py`、`inventory.py`、`orders.py` | 六个基础查询函数 |
| `scripts/seed_data.py` | 显式开发/测试 Seed 命令 |
| `migrations/versions/0001_initial_schema.py` | 首迁移，配合 env.py/alembic.ini |
| `tests/unit/`、`tests/integration/` | 基础、数据库、Seed/Service、迁移测试 |
| `pyproject.toml`、`requirements.lock`、Docker/Compose 配置 | 工程与运行依赖 |
| `docs/architecture.md`、`README.md` | 架构细节与可复制命令 |

初始 Git 基线：`b06d86a`，`chore: establish phase 02 infrastructure baseline`。Phase 02 收口提交信息：`feat: complete phase 02 data and query services`，包含 Phase 02.2 的 7 个新文件及 3 个文档修改；本文件随该提交保存，准确提交号见 Git 历史。使用既有 Git 身份，未修改全局配置，未配置远程或推送。`.env`、`.venv`、缓存、IDE/临时/数据库及常见凭据文件被忽略。原 Phase 01 快照已在初始基线中，未再创建副本。

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
- Seed：显式命令 → 验证 development/test → 按固定键派生 UUID → 只补缺失 → 整轮事务提交；不在生产或应用启动执行。

## Completed

- Phase 02.1 infrastructure/database baseline：工程、Settings、FastAPI、12 表 ORM、Alembic、Docker 和健康检查完成，并获用户审核通过。
- Phase 02.2 seed data：64 条确定性模拟记录；本轮再次连续运行两次均新增 0/已有 64，无重复数据。
- Query services：六个查询 Service、结构化返回、权限/归属及物流时间测试完成；无业务 HTTP 或 Agent Tool。
- Migration round-trip verification：专用空库的 upgrade/downgrade/upgrade/current/check 在本次完整回归中重新通过。
- PostgreSQL integration testing：2026-09-13 本次完整回归 67 项通过，无失败/跳过；依赖、编译、Compose 与健康检查通过。
- Git baseline：初始基线 b06d86a 已建立；Phase 02.2 源码、测试与收口文档经范围/凭据检查纳入最终提交，未新增功能。

## In Progress

无。Phase 02 已完成；Phase 03 尚未开始。

## Not Started

- 正式认证、数据库运行/迁移角色分离、业务 HTTP 接入和端到端身份测试。
- Agent Tool、LangGraph、模型客户端、RAG/Embedding、售后规则检索及 Agent Eval。
- 通用业务写入、退款/取消执行、跨行与并发写规则、HITL、幂等业务操作、业务审计、持久会话。

## Decisions

1. 沿用 V0.2 和已审核的 0001，不重构模型。迁移往返仅用无业务行/未知表、名称以 `_migration_test` 结尾的专用库。
2. downgrade 删除业务表/约束/索引，按原迁移保留可能共享的扩展和 Alembic 空版本表，不宣称完全清空数据库。
3. Seed 选择固定业务键/UUID 的只补缺失策略：保留已有修改及非 Seed 数据，业务键冲突使整轮回滚；为单进程开发维护设计，不提供并发重试。
4. 商品搜索为转义通配符的名称字面子串匹配，SKU 按 JSONB 规格过滤；有输入长度/条数限制，无语义检索或新增文本索引。
5. `orders:read:self` 必须附加 actor 归属条件，`orders:read:any` 才能跨用户读取；operator 标签不自动授权。无权限/他人订单/不存在统一 `OrderNotAccessible`，不泄露存在性。
6. 物流明细另外限制同订单关系，防止异常关联泄露；这不替代未来写入一致性约束。当前身份依赖默认 401，仅接受未来认证层或测试显式注入。
7. 后续版本交给 Git，不新建 README_v2 等文档副本；按用户授权冻结 Phase 02 源码和验证基线。

## Known Issues

- 正式认证和运行数据库最小权限尚未落实；不得将内部 Service 当作可直接公网开放的业务接口。
- Seed 的金额合计、预占、发货/退款范围和时间已检查，但普通 CHECK 不保护任意跨行业务写入；知识发布完整性/版本重叠亦未实现。
- updated_at 自动更新依赖 SQLAlchemy，直接 SQL 须自行维护；audit_logs 尚无数据库级只追加权限限制。
- Seed 不恢复手动改过的数据，非并发导入系统；物流和政策是本地模拟资料，未接真实来源。

## Validation Status

最终回归实际执行于 **2026-09-13 17:30:43–17:31:13（Asia/Shanghai，UTC+08:00）**；下表 `python` 指项目 `.venv/Scripts/python.exe`，不是引用 9 月 12 日结果。两个测试库连接通过环境变量显式传入，均为真实 PostgreSQL。

| 本次实际执行 | 真实结果 |
|---|---|
| `python -m pytest -q` | **67 passed in 20.22s**；0 failed、0 skipped、无警告；命令退出码 0，17:31:09 结束 |
| 测试内 upgrade → downgrade → upgrade → current → check | 专用空库往返成功；最终 0001 (head)，无 metadata 漂移，表/约束/索引恢复一致；按既有设计保留共享扩展 |
| `python -m pip check` | No broken requirements found；退出码 0，17:31:13 结束 |
| `python -m compileall app scripts tests` | 退出码 0，17:31:13 结束 |
| `docker compose config --quiet`、`docker compose ps` | 配置通过；API/DB 均 healthy |
| HTTP `GET /health` | api=ok、database=ok；17:31 再次请求成功 |
| `python -m scripts.seed_data` 连续两次 | 均 inserted=0、existing=64；17:30:45 完成，无重复新增 |
| 17:31:50 三库逐表计数和 revision 核对 | 开发库各表数量与 Data / Storage Design 一致，合计 64；两测试库业务表全为 0；三库均 revision 0001 |
| `git status`、`git diff`、`git diff --staged`、范围及凭据检查 | 初始暂存区为空；仅预期 10 文件变更，未发现本地凭据、临时调试文件、新 backup/v2/final 或 Phase 03 实现 |
| `git diff --check`、状态文件结构和文档链接检查 | 通过；保留规定的 15 节结构 |

67 项含基础/数据库 40 项、Seed/Service 26 项、迁移往返 1 项。最终收尾未修改业务代码、依赖或数据库设计，未增加 Agent/Tool/LLM/RAG/Embedding 等实现。

验证边界：Phase 02.1 容器构建/运行已验证；本轮新 Service 在宿主机虚拟环境与 PostgreSQL 回归，未重新构建镜像。未执行静态类型检查、真实停机演练、生产部署/负载/备份恢复、并发 Seed、正式认证端到端或模型调用测试。此前已恢复的 Docker 启动及临时端口问题不再列为未解决问题。

## Next Recommended Step

**Phase 03 Business Tools**。仅记录下一阶段方向，具体范围和实施须另有明确任务；本轮停止，不创建 Phase 03 代码。后续开放业务接口前仍需落实正式身份来源和数据库最小权限，不能把 Phase 02 本地验收视为生产就绪。

## Change Log

- 2026-09-12：V0.2 架构落盘；Phase 02.1 实现、40 项测试通过，随后获用户审核。
- 2026-09-12：建立基线 b06d86a；Phase 02.2 迁移往返、64 条 Seed、六个 Service、67 项测试完成，改动未提交待审核。
- 2026-09-13：按最新项目状态规范整理为 15 节，区分已有验证与恢复时的运行环境变化；未修改业务代码或进入下一阶段。

- 2026-09-13：按用户授权执行最终完整回归，67 项通过；Seed 两次无新增、健康与三库状态正常；冻结并提交 Phase 02，状态为 completed / awaiting Phase 03，未进入下一阶段。
