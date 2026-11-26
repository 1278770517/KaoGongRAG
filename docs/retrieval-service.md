# 检索服务运行说明

前端接口声明见 [前端接口契约](frontend-api-contract.md)，OpenAPI 静态快照见 [openapi.snapshot.json](openapi.snapshot.json)。

Python 环境：项目 .venv。Windows 请使用以下模块入口，入口选择 psycopg 兼容的 SelectorEventLoop。

```powershell
.venv/Scripts/python.exe -m rag_service.ingestion --source 'output/2023公考公基常识必刷600题-解析册_第2-100页' --max-pages 5
.venv/Scripts/python.exe -m rag_service.worker
$env:LOCAL_REVIEW='true'
.venv/Scripts/python.exe -m rag_service.api
```

服务默认监听 127.0.0.1:8000，接口文档 http://127.0.0.1:8000/docs。
不要在未经鉴权加固前暴露公网。LOCAL_REVIEW 默认 false；五页样本未经审核，测试时显式打开并传 review=true。

POST /search 请求示例：`{"query":"官渡之战","review":true,"limit":5}`。
返回父题、RRF 分数、image_urls 和 degraded 路由列表。图片 URL 已包含审核参数，可直接访问。
GET /questions/{question_id} 获取题目；GET /assets/{asset_id} 返回裁剪后的 PNG；GET /health 检查 SQL/Milvus。
默认响应只允许题干相关字段，不返回原始解析。此接口不是严格的作答前提示系统，不能代替 PRD 的本题限定提示。

## 配置及存储

.env 已有 POSTGRES_PASSWORD；默认 PostgreSQL localhost:5432/postgres，用户 postgres。
EMBEDDING_API_KEY、EMBEDDING_BASE_URL 缺省时复用 OCR_API_KEY、OCR_BASE_URL。
模型默认 text-embedding-v4，1024维；Milvus localhost:19530，新集合 kaogong_service_v1。
原集合 kaogong_pilot_5pages_v1 未删除。模型/维度变更须使用新的集合名称并重新索引。
REQUEST_TIMEOUT 默认30秒，CONCURRENCY 默认8，POSTGRES_HOST/PORT/DB/USER、MILVUS_URI/COLLECTION 可配置。

PostgreSQL rag_questions 保存父题，rag_assets 保存图片关系，rag_jobs 保存索引任务。
图片存储 output/rag_assets，以内容哈希命名。图片只在导入时裁剪；HTTP读取不重新裁剪或编码Base64。
没有新增 embedding 缓存或检索缓存。旧实验脚本保留兼容，正式入口使用 rag_service。

任务短事务领取，外部网络调用不持有数据库锁；5分钟租约和claim_token隔离过期任务，单任务240秒截止。
索引写入后验证ID与BM25命中才标记完成。失败任务保留failed与错误类型，可通过 Repository.retry(job_id) 显式重试再运行worker。
worker 当前为运行到队列为空后退出的CLI，不是常驻调度器。批量导入仍需按任务规模分批。

## 验证与边界

2026-11-23：实际五页入库、混合检索、图片返回、未审核隔离和8路并发健康检查通过。
机器可读结果 output/service-validation.json。真实SQL隔离测试可设置 RAG_TEST_POSTGRES=1 后运行 tests/test_service_repository.py；其临时schema独立于业务数据。

尚无审核发布管理接口，默认published-only查询对当前样本返回空结果；review模式用于本机开发验收，不能直接当作生产审核流程。
分块仍复用已验证的选择题解析器，长输入明确拒绝；未验证百炼精确tokenizer，不能宣称已支持任意长度或全部题型。
未实现 reranker、缓存、互联网鉴权、多租户服务和完整发布迁移流程。异步与并发上限减少阻塞，不能据此承诺无死锁或任意并发吞吐。
