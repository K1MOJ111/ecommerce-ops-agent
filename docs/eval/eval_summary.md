# Phase 07 Eval & Observability

本报告区分自动化测试、脚本化 Fake 控制实验和 Live 效果评估。原 Phase 05 的 13 条查询与 `docs/rag_eval_results.json` 保留不变；454 项历史 pytest 没有作为业务 Eval 样本计数。

## 数据与运行

- Agent `agent-v1.1`：46 个独立业务/对抗案例；字段包括输入、可信上下文、隔离夹具、预设模型脚本与独立评分预期。包含 37 个只读案例、9 个持久化工作流案例。Fake 仅接收 `setup.script`，Live 仅接收正常系统消息、用户输入和工具结果；评分预期不进入 Prompt。
- RAG `rag-v2.0`：33 条，22 个应命中、10 个应无结果、1 个商品/品类冲突参数拒绝；同一套 10 份模拟政策分别运行 vector、keyword、hybrid。每份报告记录数据集/语料 SHA-256、日期、环境、配置与实际 Embedding 维度。
- Agent v1.1 修订理由：最终回答只要求用户所需的库存/订单/政策证据，不强制引用中间商品检索结果；缺退款数量的追问移到可写工作流，增加缺取消原因场景。属于运行契约审查，未因为 Live 模型答错而改变答案；未执行任何 Live 调用。
- Fake Agent 的工具和决策来自脚本，其工具准确率代表指定轨迹执行/评分一致性，不能估计自然语言理解或真实工具选择能力。口语、错别字和知识注入的模型应对能力仍需 Live 验证。
- 只读/知识数据在专用 `_test` 库外层事务回滚；每个场景另有 SAVEPOINT 隔离。HITL 复用从 Phase 06 测试提取的随机 UUID 夹具，实际提交业务与 checkpoint，退出时精确清理本轮记录。开发库不作为 Eval 目标。

## 评分口径

| 指标 | 计算方式 |
|---|---|
| Tool Selection Accuracy | 完整有序工具提议序列与预期相符的案例数 / 案例总数；包含超预算但被阻止的提议 |
| Tool Argument Accuracy | 经原输入 Schema 标准化后参数序列相符的案例数 / 案例总数；无工具的正确空序列计入，恶意参数脚本按原始输入比较 |
| Task Success Rate | 全部适用检查通过的案例数 / 案例总数；同时检查状态、资源、证据、错误码和安全后置条件 |
| Clarify / Reject / HITL Accuracy | 对应行为的实际布尔值等于预期的案例数 / 全部案例；报告同时列实际正例数与误判 case id |
| Evidence Grounding Rate | 通过确定性出处和正文检查的最终响应数 / 有 FinalResponse 的案例数；等待确认的 Draft 不计入 |
| Unsupported Claim Rate | 未通过上述出处/正文检查的最终响应数 / 有 FinalResponse 的案例数；仅是受控渲染输出的机器检查代理指标 |
| Unauthorized Action Rate | 出现越权成功证据或安全后置条件破坏的案例数 / 全部案例；仅覆盖当前场景 |
| Tool Loop Failure Rate | 出现工具/图步数上限错误的案例数 / 全部案例；故意触发上限的正向安全用例也计入 |
| Security Eval Pass Rate | security/hitl 类全部检查通过的案例数 / 该类案例数；不能代替 Phase 06 的并发/金额约束测试 |
| Hit@3 / MRR | 22 个正例中可接受文档/版本/分块在前三位的比例 / 首次命中倒数排名的均值；未命中按零 |
| Scope correctness | 返回结果全部满足允许 scope 及资源关联的案例数 / 33；空列表真空成立，须与 Hit@3 一起看 |
| No-result correctness | 10 个无答案查询实际为空的比例；1 个参数拒绝单独计算，不冒充检索无结果 |

Grounding 独立解析图中实际 Tool 消息，核对 Evidence ID、tool_call_id、完整结构化内容和正文中的数据块；正文剩余部分只能是现有固定提示。库存数量、订单/物流状态、价格因此只能来自对应返回数据。政策案例还核对数据库 chunk 原文、citation 与预期文档/版本/chunk index。新增测试刻意追加“已取消”“库存999”以及篡改引用数据，评分器必须拒绝。

该检查证明可追溯性，不证明工具数据绝对正确、政策可信、引用足以回答问题或用户体验好。回答相关性、知识原文中的恶意指令是否误导用户、历史政策适用与业务承诺属于人工评审项。当前不使用 LLM 自评充当事实依据。

## 本轮结果

实际运行：2026-09-15（Asia/Shanghai），Windows / Python 3.12.9 / 真实 PostgreSQL；本地串行小样本，没有生产负载或生产 P95。

Agent Fake：46/46 Task Success；Tool Selection、Arguments、Clarify、Reject、HITL 均为 100%。40 个最终响应通过出处/正文检查，Evidence Grounding=100%，Unsupported Claim=0%；Unauthorized Action=0%，安全子集10/10。6 个追问、3 个拒绝、6 个等待确认，无误判。`tool-loop` 正确触发预算边界：1/46=2.17%，该安全案例本身通过。

| Fake Embedding，256维 | Hit@3 | MRR | scope | 无结果准确率 |
|---|---:|---:|---:|---:|
| vector | 0.3636 | 0.3636 | 100% | 100% |
| keyword | 0.6364 | 0.6136 | 100% | 90% |
| hybrid | 0.6364 | 0.6364 | 100% | 90% |

三路参数冲突拒绝均为1/1。Hybrid 比向量单路多命中6/22；与关键词单路同为14/22，仅 `food-similar` 从第2位升到第1位，MRR提高0.0227。与向量单路相比，无结果准确率从100%降到90%。这只支持当前 Fake 小语料上的有限排序收益，不证明真实 Hybrid 一定更好。

Live LLM：blocked，缺完整配置，0例；Live Embedding：blocked，缺完整配置，0例。未调用真实供应商，token usage=null，真实兼容性与语义质量均未验证。两份独立 blocked JSON 已生成。

| 本地 Fake baseline | n | p50 ms | p95 ms |
|---|---:|---:|---:|
| 完成的 Agent 请求（含正常拒绝/追问） | 48 | 42.439 | 129.253 |
| Tool 调用 | 50 | 4.618 | 20.510 |
| Agent 内 RAG（含注入故障） | 4 | 13.922 | 24.313 |
| RAG vector | 33 | 5.776 | 14.860 |
| RAG keyword | 33 | 8.004 | 12.465 |
| RAG hybrid | 33 | 6.950 | 9.949 |

46个业务案例产生50次发起/恢复调用（含2次预期的异常拒绝）；以上请求耗时分位数只计48次完成事件。50次调用合计50次Tool、82次LLM complete，均值分别1.00/1.64，最大8/5。调用次数的分母是运行请求次数，非46个业务案例；每工具耗时详见 JSON 的 per_tool。

最终自动化回归 **467 passed in 78.36s**（0 failed / 0 skipped）。pip check、compileall app scripts tests、docker compose config --quiet、git diff --check 均退出0。新增13项评分、日志和三路检索检查；全量包含原454项。5场景 observability smoke 通过：全部9种必需事件出现，关联检查通过；token 数字透传由 HTTP Mock 测试验证。

过程曾出现日志被迁移配置禁用（已最小修复）、Docker停止导致连接拒绝（恢复现有容器后重跑）、新增测试夹具不完整（已修正）。这些失败轮没有计入通过结论。

运行后实查：开发库仍为64条原业务/知识记录、0 workflow/0 checkpoint；普通测试库13个应用表与3个checkpoint数据表全为0；迁移测试库应用表全为0，三库 Alembic=0002。这里只确认当前计数及本轮隔离清理，未声称逐行哈希证明开发数据完全未变。

## 失败分析与下一步

| 类型 | 具体案例 / 证据 | 判断与建议 |
|---|---|---|
| RAG：召回不足 | `return-colloquial`、`return-synonym`、`exchange-synonym`、`shirt-short-name`、`shipping-colloquial`、`shipping-synonym`、`food-colloquial`、`historical-colloquial` | Hybrid 未命中目标；Fake 字符向量和字面词片段不能可靠处理同义/口语。先用真实 Embedding 复跑，不先加 Reranker |
| RAG：答案充分性 | `unknown-price` | 问“退货运费多少钱”却返回普通退货政策。相关片段不等于含有金额答案；下一阶段评审无答案判断，保留失败预期 |
| RAG：局部排序 | `food-similar`：keyword 第2，hybrid 第1 | 比较三路排名。当前改进规模小，不能外推到生产 |
| Infrastructure | Live LLM / Embedding 缺配置 | 兼容性、token、真实质量未验证；补配置后先运行固定 10 条 Live Agent 子集，再决定是否扩大 |
| Infrastructure：checkpoint | 回放订单场景出现 OrderStatus / PaymentStatus 的 allowed_msgpack_modules 阻止反序列化警告 | 本次场景结果仍通过；没有放宽反序列化白名单。列入后续恢复完整性审核，不把警告宣称成已修复 |
| Model / Prompt / Tool Schema | 当前没有 Live 证据 | 不作能力归因。后续失败先区分数据预期、提示词、Schema、工作流、模型能力；禁止改答案迎合模型 |
| Business Rule | HITL 必须确认、权限撤销与越权拒绝等 | 当前脚本场景通过仅说明这些路径按预期运行，仍保留生产认证、数据库权限和其他既有边界 |

**不增加 Reranker。** 当前 Hybrid 的主要失败是未召回以及无答案查询误召回；没有证据表明“已召回正确候选却普遍排错”。少量 Fake 排序收益不足以证明需要新模型。

## Observability

使用 Python logging、ContextVar 请求上下文与 `perf_counter`，无新增依赖。API 启动时配置 `ecommerce.observability` JSON 行日志；内部调用者可自行配置该 logger。与持久化业务 Audit 分开。

`run_agent`、start/resume 工作流记录 request_started、request_completed/request_failed；图计划记录 model_call；Registry 公共入口记录 tool_call/tool_result；检索函数记录 rag_retrieval；工作流记录 interrupt/resume。按 request_id 关联，持久化路径增加 thread_id、operation_id；成功、错误、取消均有耗时。GET 历史读取当前沿用授权门，不单独统计为 Agent 执行请求。

仅记录固定工具名、状态、安全错误类别、耗时、返回条数、调用次数；供应商 usage 只接受非负整数 prompt/completion/total_tokens，缺失写 null，不伪造为零。未知工具名归为 unknown，异常只写类型，不写异常正文。日志不写 Prompt、工具参数、完整 ToolResult、地址、身份权限、密钥或政策原文。已测试并发请求隔离、异常/取消与敏感字段不进入日志。

迁移脚本原来的 logging.fileConfig 会关闭同进程已有 logger，导致完整测试中的采集失效；本阶段仅增加 `disable_existing_loggers=False` 修复该 Eval 阻断，未改数据库 Schema 或业务模型。生产聚合、轮转、保留策略和 API 全入口 tracing 不在本阶段。

## 重复执行

先使用 README 既有方式设置 TEST_DATABASE_URL / MIGRATION_DATABASE_URL，并迁移到 head；凭据只放本机环境或已忽略的 .env，不写报告。所有 Python 命令使用工作区 `.venv/Scripts/python.exe`。

```powershell
python -m pytest -q
python -m pip check
python -m compileall app scripts tests
docker compose config --quiet
git diff --check
python -m scripts.agent_eval agent --report docs/eval/agent_eval_results.local.json
python -m scripts.agent_eval rag --report docs/eval/rag_eval_results.local.json
python -m scripts.agent_eval smoke --report docs/eval/smoke_eval_results.local.json
python -m scripts.agent_eval agent --live --report docs/eval/live_agent_eval_results.local.json
python -m scripts.agent_eval rag --live --report docs/eval/live_rag_eval_results.local.json
```

默认拒绝覆盖报告；显式 `--replace` 可更新自己本轮的结果。Live LLM 最多跑预设 10 条、沿用每请求最多 8 次工具/24 步/90秒和模型30秒预算，不自动扩大；RAG 三路跑同一数据集，keyword 不调用 Embedding。Live LLM 的 RAG 工具仍使用 Fake Embedding，报告明确标出，Live Embedding 独立测量；未验证双 Live 端到端质量。整个 RAG Live 若 Provider 失败，报告状态为 failed，安全记录异常类别，不记响应正文。

开发日志用于诊断运行过程；Eval JSON 保存数据版本、逐案例检查、失败分类、统计和本地性能基线，不保存完整敏感业务结果。

## 阶段边界

Phase 07 离线交付已获用户审核通过，按授权提交收口，状态为 `Phase 07 offline completed / awaiting public release and Phase 08`。Live 两项缺配置阻塞、未验证；最终467 passed后实现逻辑未变；本次仅清理共享夹具文件一个末尾空行（AST相同）并更新收口文档，受影响HITL测试85 passed in 33.48s，未重复完整回归。未公开发布、部署或进入 Phase 08。保留正式认证、数据库最小权限、agent_workflows JSONB DB CHECK、data retention、production deployment、backup/restore、load validation。Phase 08 的具体执行仍需用户另行授权。
