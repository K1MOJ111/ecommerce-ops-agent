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

运行和测试命令在对应工程能力建立并验证后补充；本 README 不提供尚不可执行的启动指令。
