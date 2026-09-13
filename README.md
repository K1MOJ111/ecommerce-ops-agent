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
- 持续会话和 Postgres checkpoint 留到 HITL 阶段。

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

`/health/live` 为 API 存活检查；`/health` 为数据库连接就绪检查，失败返回 503；两者均不调用模型。业务接口和完整认证不在本轮范围。

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

Service 接收短期 AsyncSession，返回 Pydantic 结构；不提交事务、不生成自然语言、不依赖 Agent/LLM。不新增业务 HTTP 路由，现有可信身份依赖仍默认拒绝。正式认证和运行数据库最小权限仍是对外开放业务前的前置项。

`requirements.lock` 是本轮解析出的直接和传递依赖版本约束快照；安装时配合 `-c` 使用，不包含本地路径或凭据。它不是带哈希的跨平台完整供应链锁文件。运行镜像只安装运行依赖，pytest/httpx 等放在 `test` 可选依赖中。

原有 [Phase 01 快照](docs/history/phase01/PROJECT_STATE.md) 继续保留；后续历史版本统一使用 Git 管理，不再生成重复文档副本。当前进度始终以根目录 PROJECT_STATE.md 为准。
