# ecommerce-ops-agent 项目状态

> 本文件是整个项目跨阶段、跨对话的唯一项目状态来源。架构细节见 [docs/architecture.md](docs/architecture.md)，README 只提供项目入口，不维护另一份进度。后续任务先读本文件，再按需读取架构和相关代码。用户最新明确指令优先；发生变更时应同步更新本文件。

## 项目目标

构建基于 FastAPI、LangGraph 和 PostgreSQL 的电商智能运营 Agent。模型理解请求并提出工具调用，确定性的业务代码执行权限检查、查询和规则校验。初期覆盖商品咨询、SKU 查询、库存查询、订单查询、物流查询及售后规则问答。

采用生产级设计思路逐步实现；设计文档、模拟数据和本地检查均不等于真实生产验证。

## 当前架构版本

- 版本：V0.2（架构收口版）。
- 更新日期：2026-09-12。
- V0.1 整体方向已获用户确认；V0.2 按用户提出的八项调整形成，等待本轮文档验收。
- 当前文档完成不代表允许进入实现阶段。

## 已确认技术栈

- Python 3.11+、FastAPI、LangGraph。
- PostgreSQL、SQLAlchemy 2.x、Pydantic 2.x。
- pgvector；pg_trgm 仅用于辅助模糊匹配。
- Docker Compose、pytest。
- LLM 使用 OpenAI Compatible API；供应商、模型及连接参数通过环境变量和 Settings 管理。
- Chat 模型与 Embedding 模型分别配置；Settings 使用 pydantic-settings，数据库迁移使用 Alembic。
- 尚未安装依赖、生成锁文件或选定数据库镜像；具体版本组合待实现前验证。

## 当前目录结构

以下为实际存在的项目文件，不是未来代码目录：

```text
项目根目录/
├── PROJECT_STATE.md
├── README.md
└── docs/
    └── architecture.md
```

项目标识为 ecommerce-ops-agent，当前工作区目录名为“电商智能运营 Agent”。未创建同名嵌套项目目录。目标代码目录见架构文档，尚未创建。

## 数据库设计摘要

保留 12 张表：users、products、product_skus、inventory、orders、order_items、logistics、logistics_items、refunds、knowledge_documents、knowledge_chunks、audit_logs。

- UUID 主键；业务编号另设唯一约束；金额 NUMERIC(18,2)/Decimal；带时区时间字段。
- 商品与 SKU 分离，库存按 SKU 和仓库编码唯一，可售库存由在库数量减预占数量计算。
- 订单保留下单价格、商品规格和收货信息快照；订单、支付、物流、退款状态分开。
- 支持一单多商品、一单多包裹；logistics_items 记录包裹商品数量。
- refunds 初步按订单明细设计部分退款申请；未来写操作再实现跨行额度与并发约束。
- 知识文档保留版本、适用范围和有效期；分块保存出处定位及向量。
- audit_logs 只设计追加写入模型，尚无业务审计实现。
- 当前没有数据库实例、迁移文件、DDL 执行记录或数据。

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

## 当前阶段

Phase 01：架构设计与收口。三份文档已落盘，等待用户确认；Phase 02 未开始。

## 已完成事项

- 完成需求分析、分层职责、目标目录、12 表 ER 和 LangGraph 初步设计。
- 按用户要求收紧 intent、pg_trgm、RAG、认证与 checkpoint 边界。
- 创建 PROJECT_STATE.md、docs/architecture.md 和基础 README.md。
- 明确项目状态统一由本文件维护，区分实际文件与未来目录、设计能力与已实现能力。
- 文档静态检查通过：15 项状态栏目齐全、本地链接有效、Markdown 代码围栏成对、ER 包含 12 张表、两份设计清单包含相同 7 个工具；工作区只有上述 3 份文档。未执行应用、数据库或模型测试。

## 未完成事项

- 用户对 V0.2 文档的最终确认。
- 项目代码骨架、Settings、模型 API 封装和依赖配置。
- ORM 模型、数据库迁移、数据库实例和模拟数据。
- 可信身份上下文及业务归属校验实现。
- 七个只读工具、LangGraph 执行与 RAG 导入/检索流程。
- Docker、pytest、运行验证和后续 Agent Eval。
- 正式认证、取消/退款操作、HITL、幂等控制、业务审计和持久会话。

## 已知问题

- 尚无可运行应用，不能执行服务启动、数据库查询或接口联调。
- 正式认证未实现；未来开发用固定身份不能证明生产身份安全。
- 物流暂按本地已同步数据设计，尚未接入真实物流数据源。
- 未发现需要阻断文档收口的设计冲突；无运行测试结论。

## 待验证假设

- 单商家、自营实物商品、人民币、初期单仓是否覆盖首批样例。
- 所选兼容 API 的工具调用和 Embedding 能力、向量维度及依赖版本是否匹配。
- 真实中文商品与售后语料下，向量及简单关键词/模糊检索的召回和排序效果。
- 售后规则是否有可靠来源、适用范围和历史版本；缺失时不能推断订单权益。
- 库存新鲜度、物流同步周期及模拟数据与实际业务的差异。
- 模型可能生成错误调用或无依据文本；具体拦截和回归效果待实现与测试。

## 下一阶段

建议 Phase 02 先完成最小工程基础：项目配置、FastAPI 装配、Settings、可信上下文边界、数据库模型/迁移与最小检查。准确范围由用户下次确认后确定。

Phase 02 不实现完整 JWT 登录，不引入 checkpoint 或 Reranker。若纳入订单读取，数据归属校验与越权测试必须同时完成。此处仅记录建议，不构成开始实施的授权。

## 重要变更记录

| 日期 | 版本 | 变更 |
|---|---|---|
| 2026-09-12 | V0.1 | 在对话中完成总体设计；单体分层、单 Agent、12 表方向获用户确认 |
| 2026-09-12 | V0.2 | 架构落盘；新增唯一状态入口；intent 限定为观测用途；明确 pg_trgm 与中文检索边界；排除 Reranker、完整 JWT 登录和持久化 checkpoint；未进入实现 |

后续维护：阶段切换、范围变化或验证完成时更新本文件，并记录真实证据及未验证边界；架构有变更时同时更新 docs/architecture.md。不要在 README 或其他交接文档维护冲突的进度副本。
