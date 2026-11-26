# 五页 Milvus 测试

已按用户确认仅处理 manifest 中第 1—5 页，不继续 OCR。

运行入口：`python rag_ingest.py --source output/2023公考公基常识必刷600题-解析册_第2-100页`。
添加 `--write` 创建新集合并写入；已有同名集合时拒绝覆盖。使用
`--verify-only` 重新验证已有集合；`--collection` 指定新的实验集合。
默认集合 `kaogong_pilot_5pages_v1`，本机 `http://localhost:19530` 无鉴权。
百炼复用本地 Settings 的 OCR_API_KEY、OCR_BASE_URL；密钥不进入输出。

## 实测结果

- 11 道父题，32 个 question/evidence 子块；文件保存在源目录的 rag_pilot 下。
- text-embedding-v4，1024 维，HNSW/COSINE；中文 analyzer + BM25 Function，SPARSE_INVERTED_INDEX。
- 服务端 3.0-20261110-63100f8f5b；SDK 2.6.18。已实测建表、写入、计数、加载、两类索引查询。
- 强一致读取计数 32，dense 自检命中。BM25 三条查询首位分别命中第 1、9、10 题。
- parents.json 保存原始题目转录、页码、图片布局引用；chunks.json 保存规范化视图；report.json 保存检索结果。
- 向量缓存按模型及内容哈希保存，可避免重试重复调用；报告 token 数仅代表本次调用，验证运行的 0 不表示首次生成免费。
- 25 项 pytest 通过，新增代码 Ruff 通过。

## 全量前的边界

所有数据 visibility=test_only，OCR 文本未经人工审核，不发布生产别名。
第 2 题含图片，第 11 题处于本次截断末尾，status=needs_review；其余为 unreviewed。
测试查询允许读取待审核数据，不能作为生产授权/审核过滤实现。
原始图片不进入 embedding，图片描述也未作为审核通过的证据。

当前为五页短文本试验：按解析/拓展边界切分，使用保守 UTF-8 字节护栏，
超过护栏明确报错，未接入实际模型 tokenizer，未实现任意长论证的递归语义切分。
全量前必须补齐 tokenizer 和长文本测试，不可将字节护栏称作精确 token 计数。
未实现 PostgreSQL、生产发布、RRF/reranker 或标注集质量评估。
中文分词实测将“淝水”拆为“淝”“水”，应对专名补充分词及召回测试。

参考：[百炼 Embedding](https://www.alibabacloud.com/help/en/model-studio/embedding)、
[Milvus BM25](https://milvus.io/docs/bm25-function.md)。
