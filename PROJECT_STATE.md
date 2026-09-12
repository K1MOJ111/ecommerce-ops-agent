# ecommerce-ops-agent 项目状态

> 本文件是整个项目跨阶段、跨对话的唯一项目状态来源。架构细节见 [docs/architecture.md](docs/architecture.md)，README 只提供项目入口，不维护另一份进度。后续任务先读本文件，再按需读取架构和相关代码。用户最新明确指令优先；发生变更时应同步更新本文件。

## 项目目标

构建基于 FastAPI、LangGraph 和 PostgreSQL 的电商智能运营 Agent。模型理解请求并提出工具调用，确定性的业务代码执行权限检查、查询和规则校验。初期覆盖商品咨询、SKU 查询、库存查询、订单查询、物流查询及售后规则问答。

采用生产级设计思路逐步实现；设计文档、模拟数据和本地检查均不等于真实生产验证。

## 当前架构版本

- 版本：V0.2（架构收口版）。
- 更新日期：2026-09-12。
- 用户于 2026-09-12 明确授权按 V0.2 开始 Phase 02 数据库与基础设施，覆盖原“等待确认、不得实现”的旧状态。
- Phase 02.1 工程、数据库与基础设施基线已获用户审核通过。用户授权 Phase 02.2：Git 基线、Migration 往返、Seed 和基础查询 Service；Phase 02 整体尚未结束。
- 原三份文档完整保留于 [Phase 01 快照](docs/history/phase01/PROJECT_STATE.md)，其旧进度不再作为当前状态。

## 已确认技术栈

- Python 3.11+、FastAPI、LangGraph。
- PostgreSQL、SQLAlchemy 2.x、Pydantic 2.x。
- pgvector；pg_trgm 仅用于辅助模糊匹配。
- Docker Compose、pytest。
- LLM 使用 OpenAI Compatible API；供应商、模型及连接参数通过环境变量和 Settings 管理。
- Chat 模型与 Embedding 模型分别配置；Settings 使用 pydantic-settings，数据库迁移使用 Alembic。
- 本地 Python 3.12.9；容器 Python 3.12 系列；PostgreSQL 17.10，镜像 `pgvector/pgvector:0.8.2-pg17`，vector 扩展 0.8.2、pg_trgm 1.6。
- 已安装 FastAPI 0.141.1、Uvicorn 0.52.4、SQLAlchemy 2.0.52、asyncpg 0.31.0、Alembic 1.20.0、Pydantic 2.13.5、pydantic-settings 2.15.0、pgvector Python 0.5.0；测试使用 pytest 9.1.1、pytest-asyncio 1.4.0、httpx 0.28.1。
- `requirements.lock` 固定本轮直接/传递依赖版本，已在 Windows 本地安装及 Linux Docker 构建中使用；不是带哈希的完整跨平台锁文件。未安装 LangGraph 或模型调用依赖。

## 当前目录结构

以下为实际工程目录，省略缓存、虚拟环境内部文件：

```text
项目根目录/
├── PROJECT_STATE.md
├── README.md
├── pyproject.toml
├── requirements.lock
├── .env.example / .gitignore / .dockerignore
├── Dockerfile / compose.yaml / alembic.ini
├── app/
│   ├── __init__.py / main.py
│   ├── core/（config.py、security.py）
│   ├── api/（dependencies.py、routes/health.py）
│   └── db/
│       ├── base.py / session.py
│       └── models/（__init__.py、commerce.py、knowledge.py、audit.py）
├── migrations/
│   ├── env.py / script.py.mako / README
│   └── versions/0001_initial_schema.py
├── tests/
│   ├── conftest.py
│   ├── unit/test_foundation.py
│   └── integration/test_database.py
└── docs/
    ├── architecture.md
    └── history/phase01/（原三份文档，保留原目录关系）
```

项目标识为 ecommerce-ops-agent，当前工作区目录名为“电商智能运营 Agent”。未创建同名嵌套项目目录。另有本地 `.venv` 和私密 `.env`；`.env` 已列入 Git/Docker 排除清单，本文不记录凭据。当前目录没有 `.git`，本轮未初始化 Git、提交或发布。未来业务目录按需创建，未生成占位文件。

## 数据库设计摘要

保留 12 张表：users、products、product_skus、inventory、orders、order_items、logistics、logistics_items、refunds、knowledge_documents、knowledge_chunks、audit_logs。

- UUID 主键；业务编号另设唯一约束；金额 NUMERIC(18,2)/Decimal；带时区时间字段。
- 商品与 SKU 分离，库存按 SKU 和仓库编码唯一，可售库存由在库数量减预占数量计算。
- 订单保留下单价格、商品规格和收货信息快照；订单、支付、物流、退款状态分开。
- 支持一单多商品、一单多包裹；logistics_items 记录包裹商品数量。
- refunds 初步按订单明细设计部分退款申请；未来写操作再实现跨行额度与并发约束。
- 知识文档保留版本、适用范围和有效期；分块保存出处定位及不固定维度的 `vector`，暂不创建向量索引或 pg_trgm 文本索引。
- audit_logs 已建立追加事件表结构，只保留 created_at；尚无业务审计服务或数据库级只追加权限限制。
- 开发库 `ecommerce_ops` 和独立测试库 `ecommerce_ops_test` 均实际完成首迁移 `0001`，各有上述 12 张业务表及 Alembic 自有 `alembic_version` 表。
- 实查 32 个 CHECK、13 个外键、12 个业务 UNIQUE、12 个业务主键和 8 个额外非唯一索引；连同 Alembic 主键索引共 33 个索引。所有业务外键 `ON DELETE RESTRICT`，无删除级联。
- 测试结束后逐表计数，两库各 12 张业务表均为 0 行；没有 Seed Data。测试数据在事务内生成并回滚。

## LangGraph 设计摘要

- 单 Agent、显式 State、有限 Tool Loop。
- 节点：plan、execute_tools、answer、clarify、reject。
- intent 仅用于可观测性、日志和未来 Eval；不作为权限、工具授权、安全判断或流程路由的依据。
- 路由读取经过结构校验的下一步动作和工具调用；权限由服务端可信上下文及业务服务判断。
- 可信上下文包含 actor_id、permissions、request_id，与模型可生成的状态分离。
- 不使用持久化 checkpoint；持续会话和 Postgres checkpoint 留到 HITL 阶段。

## 当前 Tool 列表

以下为已确认设计，全部尚未实现：

| Tool | 用途 |
|---|---|
| search_products | 搜索候选商品 |
| get_product | 查询商品详情 |
| list_product_skus | 查询和筛选具体规格 |
| get_inventory | 查询 SKU 库存 |
| get_order | 经权限及数据归属校验后查询订单明细 |
| get_logistics | 经权限及订单归属校验后查询包裹 |
| search_after_sales_policy | 检索适用售后规则并返回出处 |

## 已确认的关键架构决策

1. 单体分层架构，API、Agent、Tool、业务服务、数据库和 RAG 解耦；路由不承载业务逻辑。
2. 业务服务直接使用 SQLAlchemy，不增加通用 Repository 或其他无必要的抽象。
3. 首个业务闭环仅开放只读工具；模型不能执行任意 SQL、业务写操作或自行授予权限。
4. Phase 02 不实现完整 JWT 登录。保留服务端可信上下文；正式认证后续实现。
5. 订单和物流查询均必须校验数据归属。订单号、UUID、用户提示词或模型 intent 均不能替代授权。
6. 开发身份只能由服务端固定配置或测试依赖注入，不信任客户端身份/权限字段；正式认证缺失时禁止作为公网业务接口运行。
7. RAG 第一版为向量检索、必要过滤和简单关键词/模糊检索；不加入 Reranker。
8. pg_trgm 只定义为商品名称和文本的辅助模糊匹配；中文检索效果未验证。
9. 只有真实测试数据和 Eval 显示明显排序问题后，才评估 Reranker；不预先安装或搭建相关模块。
10. 不加入持久化 checkpoint；持久会话和 Postgres checkpoint 留到 HITL 阶段。
11. 不增加 Multi-Agent、Redis、消息队列、微服务、前端或供应商绑定。
12. 后续 Python 代码须有明确类型注解；非简单逻辑须有可运行检查，数据库特有行为使用真实 PostgreSQL 集成测试。
13. 按用户最新要求，Phase 02 首迁移使用不固定维度 `vector`，EMBEDDING_DIM 默认空；覆盖原架构首版固定 `vector(D)` 的安排。实际验证可存不同维度，异维距离运算被拒绝；后续同一检索集合须保证模型/版本和维度一致，必要时通过迁移固定维度，换模型/维度须重建向量。
14. 单行规则明确为数据库 CHECK：金额非负并排除 NaN、订单优惠不超小计、paid_amount 不超 payable_amount、金额等式、CNY 币种和 JSON 对象快照；跨行规则仍留在未来业务事务。
15. `/health/live` 只检查 API 存活；`/health` 检查数据库连接并在失败时返回 503，不检查模型，也不冒充迁移完整性检查。迁移必须独立执行，禁止应用启动 create_all。
16. 应用生命周期管理 Engine/sessionmaker；请求依赖创建短期 AsyncSession，业务事务不自动提交。可信上下文为不可变类型，默认依赖返回 401，不建立模拟身份系统。
17. 本轮 Compose 仅 API 和 PostgreSQL，端口只映射 127.0.0.1；API 使用非 root 用户。迁移账号与运行账号尚未分离，正式业务读取阶段必须落实最小权限；本地验证不等于生产安全验证。

## 当前阶段

Phase 02.1 已完成并通过审核；Phase 02.2 开始实施。禁止进入 Agent、Tool、RAG、LLM、HITL 或 Phase 03。

## 已完成事项

- 保留 Phase 01 的分层设计、12 表和 7 个只读 Tool 设计；没有提前实现业务流程。
- 创建 Python 工程配置、依赖版本快照、私密配置示例、Dockerfile 和双服务 Compose。
- 实现统一 Settings、FastAPI 入口、API 存活/数据库就绪检查、可信服务端上下文类型和默认拒绝的依赖接口。
- 实现 SQLAlchemy 2.x AsyncEngine/AsyncSession/sessionmaker、12 张 ORM 表、命名约束和必要索引。
- 正式初始化 Alembic，首迁移显式创建 vector/pg_trgm 扩展和全部表；迁移不引用当前 ORM 的 create_all。
- 使用真实 PostgreSQL 验证连接、迁移、约束、关系、金额/规格快照及向量存储边界。
- 完成 API 容器构建/启动及宿主机 HTTP 验证；README 补齐本地运行、迁移和独立数据库测试命令。
- 更新架构中的维度安排及本文件真实状态；原始文档保留历史副本。

## 未完成事项

- 当前 Phase 02 交付的用户审核。
- Seed Data：明确不在本轮范围，放到下一小步；没有创建 seed 脚本。
- 正式认证、运行/迁移数据库角色分离、业务归属校验、跨行及并发约束。
- 模型 API 封装、七个只读工具、LangGraph、RAG 导入/检索及 Agent Eval：本轮全部未实现。
- 取消/退款操作、HITL、幂等控制、业务审计和持久会话：后续范围。

## 验证结果与真实命令（2026-09-12）

下表 `python` 指项目 `.venv/Scripts/python.exe`；所有验证只在本机完成。测试库连接由本地 Settings 派生后通过 `TEST_DATABASE_URL` 注入，不在日志或文档中记录密码，完整可复现命令见 README。

| 实际命令/检查 | 真实结果 |
|---|---|
| `py -0p`、`py -3.12 --version` | 存在 Python 3.12.9、3.14；本项目使用 3.12.9 |
| `git status --short` | 失败：当前目录及上级不是 Git 仓库；未初始化 Git |
| `docker version` | 首次失败：Docker Linux 引擎命名管道不存在 |
| `docker desktop start`；`docker info --format '{{.ServerVersion}}'` | 启动成功，Docker Server 29.7.2 |
| `docker compose version` | v5.4.0 |
| `py -3.12 -m venv .venv` | 成功创建项目虚拟环境 |
| `python -m pip install -e '.[test]'` | 成功安装运行和测试依赖 |
| `python -m pip install -c requirements.lock -e '.[test]'` | 按版本快照再次安装成功，版本未变化 |
| `python -m pip freeze --exclude ecommerce-ops-agent` | 输出保存为 requirements.lock，无本地 editable 路径 |
| `docker compose config --quiet` | 成功，无配置错误 |
| `docker compose up -d db --wait --wait-timeout 90` | 成功拉取镜像并启动 PostgreSQL，healthy |
| `python -m alembic init -t async migrations` | 成功初始化，随后配置 Settings 与完整 metadata |
| `python -m alembic revision --autogenerate --rev-id 0001 -m initial_schema` | 成功生成；应用前补齐两个扩展及 Vector 类型导入，人工核对 DDL |
| `python -m alembic upgrade head` | 开发库成功从空库升级到 0001 |
| `python -m alembic current` | `0001 (head)` |
| `python -m alembic check` | `No new upgrade operations detected.`；此命令不替代约束行为测试 |
| `docker compose exec -T db createdb -U ecommerce ecommerce_ops_test` | 成功建立独立测试库 |
| 设置测试库后 `python -m pytest -q` | 首次 40 passed / 2 条测试客户端弃用警告；改用现有 httpx 异步客户端后最终 **40 passed，0 failed，0 skipped，无警告，3.57s** |
| `python -m pip check` | `No broken requirements found.` |
| `python -m compileall -q app migrations tests` | 成功，所有 Python 文件可编译 |
| `docker compose build api` | 成功构建 Linux API 镜像 |
| `docker compose up -d --build api --wait --wait-timeout 90` | 最终代码重新构建成功；API 与 DB 均 healthy |
| `docker compose run --rm api alembic upgrade head` | 容器内迁移命令成功，已在 head，无新增变更 |
| `Invoke-RestMethod http://127.0.0.1:8000/health` | HTTP 成功，`{"api":"ok","database":"ok"}` |
| `Invoke-RestMethod http://127.0.0.1:8000/health/live` | HTTP 成功，`{"api":"ok"}` |
| `docker compose ps` | 两容器 healthy，端口分别只绑定 127.0.0.1:8000 / 55432 |
| `docker compose exec -T api id -u` | 1000，运行进程不是 root |
| `docker compose exec -T api python -m pip check` | 无依赖冲突 |
| 容器 psql 查询版本、扩展、pg_tables、pg_constraint、pg_indexes | PostgreSQL 17.10；vector 0.8.2 / pg_trgm 1.6；12 业务表 + 版本表，约束/索引数量见上文 |
| 使用 SQLAlchemy 对两库的 12 张表逐表 `COUNT(*)` | 所有业务表均 0 行，测试事务已回滚，无 Seed |
| Python 检查交付文件的私密密码泄漏、Markdown 相对链接/围栏；rg 检查排除项 | 33 份交付文件检查通过；未发现私密密码泄漏、断链或 create_all/删除级联/被排除业务依赖导入 |

40 项测试包含 12 项单元测试、28 项 PostgreSQL 集成测试：Settings 加载/非法配置、健康成功/错误/超时、可信身份拒绝与测试注入、真实健康连接、独立会话、真实迁移和表/扩展、SKU 唯一、库存范围、明细数量、金额非负/NaN/等式、非法状态/币种、用户订单外键、限制删除、历史快照、知识范围/有效期，以及不固定维度存储和异维距离拒绝。

未执行迁移 downgrade（会删除表）；健康失败/超时分支通过模拟异常验证，未实施真实数据库停机故障演练；未执行生产部署、负载测试、备份恢复、真实模型/检索或业务授权测试。容器构建时 pip 提示以 root 安装依赖，属于构建阶段提示；最终 API 运行用户已实查为 UID 1000。

## 已知问题

- 本阶段没有遗留阻断错误；本地运行与测试通过，不代表生产验收。
- 正式认证未实现；未来开发用固定身份不能证明生产身份安全。
- 物流暂按本地已同步数据设计，尚未接入真实物流数据源。
- 无必须重构 12 表才能落地的架构问题。已显式解决两处旧描述冲突：Phase 02 未授权状态、首迁移固定向量维度安排；均按用户本轮指令更新。
- 跨订单包裹关联、跨明细合计、累计发货/退款限制、发布完整性和版本重叠仍只在设计层；数据库普通 CHECK 不保证这些跨行条件。尚无业务写入口。
- `updated_at` 的自动更新由 SQLAlchemy 执行；直接 SQL 更新须自行维护时间。audit_logs 暂无禁止修改的数据库权限限制。
- API/DB 容器保持本机运行，数据在项目独立 Docker volume 中；本轮没有删除 volume，也没有修改其他项目容器。

## 待验证假设

- 单商家、自营实物商品、人民币、初期单仓是否覆盖首批样例。
- 所选兼容 API 的工具调用和 Embedding 能力、向量维度及依赖版本是否匹配。
- 真实中文商品与售后语料下，向量及简单关键词/模糊检索的召回和排序效果。
- 售后规则是否有可靠来源、适用范围和历史版本；缺失时不能推断订单权益。
- 库存新鲜度、物流同步周期及模拟数据与实际业务的差异。
- 模型可能生成错误调用或无依据文本；具体拦截和回归效果待实现与测试。

## 下一阶段

先等待用户审核本轮交付。审核通过后，下一小步仍属 Phase 02：明确最小模拟电商数据集，再实现可重复执行、保持业务一致性的 Seed Data 及校验。尚未开始。

不进入 Agent/Tool 阶段。未来开放业务查询前落实认证来源/运行数据库权限与数据归属测试；不引入完整 JWT、checkpoint 或 Reranker，除非对应阶段另有明确授权。

## 重要变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-09-12 | V0.1 | 在对话中完成总体设计；单体分层、单 Agent、12 表方向获用户确认 |
| 2026-09-12 | V0.2 | 架构落盘；新增唯一状态入口；intent 限定为观测用途；明确 pg_trgm 与中文检索边界；排除 Reranker、完整 JWT 登录和持久化 checkpoint；未进入实现 |
| 2026-09-12 | V0.2 / Phase 02 | 用户明确授权基础设施实现；保留 Phase 01 原版；首迁移使用可变维度 vector；完成工程、12 表、Alembic、Docker、本地 API 和 40 项测试；未做 Seed，等待审核 |

后续维护：阶段切换、范围变化或验证完成时更新本文件，并记录真实证据及未验证边界；架构有变更时同时更新 docs/architecture.md。不要在 README 或其他交接文档维护冲突的进度副本。
