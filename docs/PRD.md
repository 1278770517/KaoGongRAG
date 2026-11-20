# 考公 RAG 学习助手：产品需求与技术设计草案

版本：0.2｜日期：2026-11-20｜状态：OCR 命令行基线已实现，RAG 业务待实现

本文将“PR 文档”理解为项目需求文档（PRD），不是 GitHub Pull Request。当前会话仅维护需求、评估技术可行性及处理 Git；不实现业务代码。本版作为 KaoGongRAG 仓库的首次代码与文档基线，后续修改通过独立提交保留回退能力。

## 0. 当前代码进展与基线验证

截至 2026-11-20，已实现 `main.py` 命令行入口和 `pdf_ocr` 模块：配置加载、DashScope OCR 请求、严格布局 JSON 校验、PDF 逐页渲染、按识别顺序生成 Markdown、图片裁剪后 Base64 内嵌。支持页码范围、超时重试、逐页失败记录、文件 SHA256 和 manifest 汇总，拒绝覆盖同名输出目录。默认模型为 `qwen3-vl-plus`，配置由环境变量或本地 `.env` 提供。

当前实现与目标设计的差异：所有选中页均渲染后调用 OCR，尚无文本层优先路径；失败页需指定新输出目录重跑，尚无持久队列或原地断点恢复；输出是页级 Markdown，不是已配对的题目与答案。图片存储目前为本地页图及内嵌数据，未来导入题库时需转换为稳定资源引用。

FastAPI、LangChain、LangGraph、Milvus 和 PostgreSQL 相关依赖已声明，但尚无对应业务服务、数据库 schema、Embedding 索引、随机练习、判题、错题、对话或长期记忆实现。下文接口、数据模型与流程均为目标需求，不代表当前功能。

本次验证：`python -m pytest -q` 为 20 passed；`python -m ruff check main.py pdf_ocr tests` 报告 5 项问题，均位于 `pdf_ocr/converter.py` 的手工调试入口（导入顺序和 Windows 路径转义）。该入口还包含固定本机路径；推荐使用根目录 `main.py`。按本次只更新文档和 Git 的范围，保留代码原状并记录这些已知问题。测试使用模拟 OCR，不能据此认定真实题库识别准确率或在线 API 联调通过。

版本管理排除：任意层级 `output/`、`.env` 及其变体（仅允许脱敏 `.env.example`）、虚拟环境、工具/测试缓存、IDE 配置与 PDF 原始文件。基线提交后创建 `baseline-2026-11-20` 标签；后续用新分支试验，可从该标签另建分支恢复基线，不必覆盖已有历史。

## 1. 目标与范围

建立 PDF 题库导入 → 随机练习 → 作答判定 → 错题积累 → RAG 辅导 → 跨会话学习习惯记忆的闭环。

用户已确认首期支持选择题、一问一答题，未来扩展论述题；还可能扩展数推、申论等考试内容。必须区分“作答形式”和“考试分类”：数推可能是选择题，申论可能包含问答或论述题，不能把二者写成同一枚举。

首期提供后端接口，不包含前端、支付、完整考试系统、模型训练。OCR、Embedding 调用外部 API；讲解和辅助评价还需要 LLM API，供应商、模型、预算待确定。

成功标准：题目来源可追溯；练习不会提前泄露答案；错题记录可重放核对；讲解有依据；长期记忆可查看、纠正和删除；增加题型不要求改写整个练习与对话流程。

## 2. 架构选择与可行性

| 方案 | 收益 | 代价与结论 |
| --- | --- | --- |
| FastAPI 模块化单体 + PostgreSQL + Milvus + 独立任务进程 | 符合指定技术栈，业务边界明确，后续可拆分 | 有双存储一致性成本；推荐，尚待评审 |
| PostgreSQL + 向量扩展 | 部署更简单 | 改变指定 Milvus 选型，仅作为替代方案 |
| 从首期拆微服务 | 各服务独立扩容 | 分布式事务和部署成本过高，暂不采用 |

技术判断：可行，但尚无样本 PDF、API 凭据或运行测试，不能承诺识别准确率、回答质量及性能。核心风险在题目切分、跨页答案配对、开放题评价和错误记忆累积，而不是框架能否连接。

建议职责：FastAPI 负责 HTTP 与鉴权；LangChain 负责模型/检索适配；LangGraph 负责有界工作流、状态恢复和对话编排；PostgreSQL 是业务事实来源；Milvus 是可重建的检索索引。PDF、页图和题目图片保存到文件/对象存储，通过 Storage 接口隔离实现。

模块划分：导入 ingestion、题库 question_bank、练习 practice、错题 mistakes、检索 retrieval、对话 conversations、学习记忆 learner_memory、提供商 providers。业务层不直接依赖 Milvus SDK 或模型 SDK。

## 3. PDF 导入与发布

1. 管理员上传 PDF，记录文件哈希、来源、版本与存储地址，返回异步 job_id。
2. 优先提取文本层，需要时调用 OCR；保留页码、原始文本、布局坐标及图片引用。
3. 按题目语义切分，支持跨页题干、独立答案章节、共享材料、多题引用同一材料。
4. 结构化生成题干、选项、参考答案、解析、题型、考试分类与知识点；答案配对结合题号、章节、页范围，不能仅按题号匹配。
5. 校验选项唯一性、答案是否合法、必填字段、配对置信度及重复题。无法解析、答案缺失、公式图片不完整或配对歧义进入待审核队列。
6. 审核确认后发布题目版本，事务内写入索引任务；后台调用 Embedding 并 upsert Milvus。
7. 记录索引成功/失败及重试信息。只有已审核发布的题目可以抽取；尚未索引的题目可练习，但不能承诺 RAG 可检索。

状态：uploaded → extracting → structuring → awaiting_review → indexing → completed；支持 failed、部分成功及按失败单元重试。任务进度分别统计总页数、识别页数、有效题数、待审核题数和索引题数，不能把 API 调用成功当作导入完成。

幂等键采用文件哈希、解析器版本及题目版本；重复上传返回已有任务或明确创建新版本。OCR 输出、模型输出均视为不可信数据，不能作为系统指令执行。

## 4. 题型与判题

公共题目字段：id、version、question_type、exam_category、stem、material_id、assets、knowledge_tags、difficulty（可空）、source、review_status、schema_version。题型专有内容存入有版本校验的 JSONB payload。

| 形式 | 专有内容 | 判题与错题规则 |
| --- | --- | --- |
| 选择题 choice | 稳定 option_id、单选/多选模式、正确选项集合 | 用确定性规则比较集合；多选与部分得分规则待确认，默认草案为集合全对才正确 |
| 一问一答 qa | 参考答案、允许答案、要点与评分规则（可选） | 客观短答案可规范化精确判定；开放答案采用参考要点评价，输出正确/错误/待确认，不能只比较字符串 |
| 论述题 essay（未来） | 材料、字数约束、评分维度、分值与示例 | 独立评价策略，提供维度反馈；不承诺等同正式考试评分 |

LLM 评价必须附依据、缺失要点和不确定状态；用户可确认或纠正结果。只有确定判错或用户标错才进入有效错题统计；待确认评价不自动固化为学习习惯。

每种题型实现协议：validate_payload、render_public、grade、build_retrieval_text。扩展时新增 schema/策略和契约用例，不更改统一抽题、作答记录、会话接口。

## 5. 随机练习与错题

随机抽题在 PostgreSQL 对已发布题目按考试分类、形式、知识点筛选，再无放回抽样；默认单次练习内不重复，历史重复策略可配置。小题库可使用随机排序，规模扩大后替换抽样实现并验证偏差，不把向量近邻检索当随机抽题。

抽题生成 practice_session，固定 question_version 与题序。返回题干、材料和选项；参考答案、解析、正确选项均由响应模型排除。题量不足返回实际数量及原因。

提交答案记录原始作答、耗时、评价版本和结果；使用 Idempotency-Key 防止重复提交导致统计翻倍。事务内保存 attempt、错题更新与后续记忆任务。重做产生新 attempt，保留完整历史。

错题按 user_id + question_id 聚合，保存首次/最近错误时间、错误次数、复习次数、掌握状态以及关联 attempt。一次答对不删除错误历史；“已掌握”为可撤销状态，自动判定阈值待确认。评价被纠正时，保留原始评价与修订审计，并事务性重算错误次数和有效错题状态，再排队更新长期记忆。

## 6. RAG 辅导与长期记忆

建议图流程：鉴权及意图识别 → 加载会话与题目 → 读取用户错题事实及记忆 → 检索候选资料 → 校验权限/版本并构造证据 → 生成讲解 → 保存消息 → 提议更新记忆。

错题事实首先从 PostgreSQL 读取；Milvus 检索相似题、解析与相关知识。首期可依据用户错题的题目 ID 限定候选集，再与公共题库检索合并。私有记忆如需向量化，使用独立集合或明确 visibility、user_id 过滤；服务端从身份上下文注入权限条件，检索结果仍回表检查。共享题库与用户数据不可混淆。

检索单元以题干、参考解析、知识点为主，保留 question_id、version、chunk_id、source_page、embedding_model、embedding_version。长材料分块但保持题目关联；答题前的提示模式不能返回参考答案，完整讲解默认在提交后开放。

作答前防泄题由服务端依据当前用户在当前练习项的提交状态控制；提示模式从检索上下文排除答案、解析及含答案的相似题片段，不仅依赖提示词要求模型保密。

回答结构：题意说明、关键依据、解题步骤、常见误区、针对本次错误的改进建议、来源。引用必须对应实际检索材料；无证据或材料冲突时明确说明，不伪造原文依据。用户提交的思路缺失时，不推断具体错误原因。

短期记忆：会话消息与 LangGraph checkpoint，thread_id 绑定用户和会话。长期记忆：跨会话的结构化学习记录，不等同于聊天摘要，也不自动从 checkpoint 获得。

长期记录字段：user_id、知识点/错误标签、观察或推断类型、evidence_attempt_ids、样本数、置信度、创建/更新时间、状态、过期或衰减策略。统计事实由程序计算；“易漏看否定词”等推断保留证据并允许纠正。低样本观察只作候选，不直接宣称习惯；阈值需通过实际数据评估。

记忆更新异步执行，以事件 ID 幂等去重；作答评价纠正后重新计算相关统计并撤销失效记忆。用户能查看、修改和删除记忆；禁止把删除的记忆通过旧任务自动重新写回。

## 7. 数据与一致性

建议表：users、source_documents、import_jobs、materials、questions、question_versions、practice_sessions、practice_items、attempts、mistakes、conversations、messages、learner_memories、memory_evidence、outbox_events。LangGraph 持久化表与业务表分开管理迁移。

所有用户资源携带 user_id；attempt 固定题目与判题版本；messages 标记角色、生成状态与引用；错题聚合有唯一约束；消息重试有 request_id。题目更新不覆盖历史版本。

PostgreSQL 事务中写业务事实和 outbox，由独立 worker 重试写 Milvus，避免请求内双写造成不可恢复的不一致。Milvus 主键由题目版本/分块/向量版本确定，重复事件可安全重放；定期校验缺失、过期索引并修复。

Embedding 模型更换需新建版本化索引并全量重建、评估、切换和保留回滚窗口；即使维度相同，不同模型的向量也不能混用。删除以数据库 tombstone 立即阻断读取，再异步清理索引与文件。

## 8. 接口草案（/api/v1）

| 方法与路径 | 用途 |
| --- | --- |
| POST /imports | 上传 PDF，返回 202 与 job_id，管理员权限 |
| GET /imports/{id} | 查询导入进度和失败原因 |
| GET /imports/{id}/review-items | 查询待审核题目 |
| PATCH /review-items/{id} | 修正结构化题目或配对 |
| POST /review-items/{id}/publish | 审核发布并排队索引 |
| POST /practice-sessions | 指定筛选条件和数量随机抽题 |
| GET /practice-sessions/{id} | 获取练习状态和不含答案的题目 |
| POST /practice-sessions/{id}/attempts | 提交某题答案，返回评价与 attempt_id |
| GET /mistakes | 分页查询错题及筛选 |
| PATCH /mistakes/{id} | 更新掌握状态 |
| POST /attempts/{id}/feedback | 用户确认或纠正评价，保留原始评价和审计记录 |
| POST /conversations | 创建会话，返回 conversation_id |
| GET /conversations | 分页列举当前用户会话 |
| GET /conversations/{id}/messages | 分页读取消息 |
| POST /conversations/{id}/messages | 发送消息，可关联 question_id 或 attempt_id |
| DELETE /conversations/{id} | 删除会话及消息/checkpoint，返回 204 |
| GET /memories | 查看当前用户长期记忆 |
| PATCH /memories/{id} | 纠正记忆并记录来源 |
| DELETE /memories/{id} | 删除记忆并阻断旧任务重建 |

统一错误结构：code、message、request_id、details。身份由服务端鉴权取得，不信任请求中的 user_id；分页使用游标；资源不存在或无权访问采用一致策略。同一会话并发生成需串行化或返回冲突，不能覆盖 checkpoint。

对话建议支持 SSE：message_start、token、citation、message_end、error；开始流式响应后的失败通过 error 事件表达。断线不保证模型重放完全一致，客户端通过 request_id 查询已保存结果，重试避免重复消息。是否首期实现 SSE 待评审。

删除会话默认保留独立练习事实和由作答产生的长期记忆；仅来源于已删消息的记忆应撤销或去除关联。该语义须向用户明确，并提供独立记忆删除能力。删除与在途任务需通过 tombstone/版本检查阻止数据复活。

## 9. 可靠性、部署与观测

首期建议一个 API 服务、一个持久任务 worker、PostgreSQL、Milvus 和文件/对象存储。可先用 PostgreSQL 任务表及租约机制，暂不强制引入 Redis/Celery；任务须有超时、退避重试、失败队列和人工重试。FastAPI BackgroundTasks 不作为可恢复导入任务的唯一保障。

OCR/Embedding/LLM 适配器统一超时、并发限额、429 退避、用量统计和敏感信息脱敏；非幂等调用重试计入成本。设置文件大小/页数、单次抽题数量、检索数量和对话 token 上限，具体值按样本与预算确定。

记录 trace/request/job ID、各阶段时延、模型版本、检索命中、引用来源、token/页数成本及失败率；日志避免输出完整用户隐私和密钥。数据库迁移、备份恢复和索引重建应有操作说明。

## 10. 验收与阶段

以下是拟定验收方法，不是已经测得的指标。

1. 样本验证：收集两种题型、文本/扫描 PDF、跨页题目和独立答案页；人工标注至少 100 题，分别报告题目切分、答案配对准确率和审核比例。所有已发布题目必须有可追溯来源；错误配对不得无审核入库。
2. 练习闭环：验证单次无重复、筛选有效、题量不足、答案不泄露、重复提交幂等、版本固定、错题统计与 attempt 一致。
3. 判题：选择题按已确定规则全量通过规则用例；问答评价与人工参考对照，单独报告误判和待确认比例，再确定上线门槛。
4. RAG：建立带预期证据的查询集，测 Recall@K、引用准确率和讲解质量；无证据、冲突材料、提示注入必须有降级行为。不能仅用“回答流畅”验收。
5. 记忆：跨新会话读取有效观察；纠正评价、删除记忆后结果一致；单次错题不被直接表述为稳定习惯。
6. 隔离与恢复：两个用户互访资源全部受阻；模拟 OCR 限流、Milvus 不可用、worker 中断、重复事件和删除期间并发任务，确认可恢复且不重复计数。
7. 性能与成本：在声明的数据量、并发量、硬件和外部模型条件下记录 P50/P95、每百页导入成本和每次对话成本；规模与预算未确认前不写虚假的 SLA。

阶段顺序：需求确认与样本验证 → PDF 导入审核和题库 → 抽题作答错题 → 带引用的 RAG 对话 → 长期记忆 → 论述题扩展。每阶段通过对应验收后再推进。

## 11. 待确认事项

- 选择题是否包含多选，以及部分得分规则。
- 一问一答主要是标准短答案，还是需要按要点评价的开放答案。
- 首批 PDF 样本、答案版式、是否包含公式/图形/共享材料。
- 用户规模、题库规模、部署机器、调用预算与外部 API 供应商。
- 鉴权方式、题库是否共享、长期记忆默认启用与删除语义。
- GitHub 基线目标：`1278770517/KaoGongRAG`；后续功能改动使用独立提交或分支。

## 12. 官方资料与验证边界

资料核查日期：2026-11-19。以下支持能力判断，不代表已完成本项目集成验证。

- [Milvus 过滤检索](https://milvus.io/docs/filtered-search.md)：可组合元数据过滤与向量搜索；应用仍需负责身份隔离。
- [Milvus Embedding Function](https://milvus.io/docs/embedding-function-overview.md)：查询向量与字段向量维度需匹配；本项目建议经提供商适配层显式管理向量版本。
- [LangGraph 记忆官方源文档](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/add-memory.mdx) 与 [Store 文档](https://github.com/langchain-ai/docs/blob/main/src/oss/langgraph/stores.mdx)：线程内状态与跨线程存储是不同职责。
- [FastAPI 后台任务说明](https://fastapi.tiangolo.com/tutorial/background-tasks/)：进程内后台任务有适用边界；持久任务队列与恢复机制属于本项目架构建议。

实施前应锁定 Python、LangChain、LangGraph、Milvus SDK 与数据库驱动版本，并完成兼容性验证。本草案未指定未经验证的版本组合。
