"""外部服务适配：异步调用百炼与 Milvus，管理向量校验和双路召回。"""

import asyncio
import math

from openai import AsyncOpenAI
from pymilvus import AsyncMilvusClient, DataType, Function, FunctionType


class Providers:
    """复用异步客户端，以并发上限约束 embedding 和检索网络请求。"""

    def __init__(self, settings):
        """客户端在当前事件循环创建，整个服务生命周期共享。"""
        self.settings = settings
        self.gate = asyncio.Semaphore(settings.concurrency)
        self.api = AsyncOpenAI(
            api_key=settings.embedding_api_key.get_secret_value(),
            base_url=settings.embedding_base_url,
            timeout=settings.request_timeout,
            max_retries=1,
        )
        self.milvus = AsyncMilvusClient(
            uri=settings.milvus_uri, timeout=settings.request_timeout
        )
        self.collection = settings.milvus_collection

    async def close(self):
        """关闭外部 HTTP 和 Milvus 连接。"""
        await self.api.close()
        await self.milvus.close()

    async def embed(self, texts):
        """调用百炼并按响应 index 对齐输入，再验证维度、有限值及非零向量。"""
        async with self.gate, asyncio.timeout(self.settings.request_timeout):
            result = await self.api.embeddings.create(
                model=self.settings.embedding_model,
                input=texts,
                dimensions=self.settings.embedding_dim,
                encoding_format="float",
            )
        rows = sorted(result.data, key=lambda r: r.index)
        if [r.index for r in rows] != list(range(len(texts))):
            raise ValueError("Embedding mapping mismatch")
        vectors = [r.embedding for r in rows]
        if any(
            len(v) != self.settings.embedding_dim
            or not any(v)
            or not all(math.isfinite(x) for x in v)
            for v in vectors
        ):
            raise ValueError("Invalid embedding")
        return vectors

    async def initialize(self):
        """集合不存在时创建 BM25/dense schema；已有集合继续使用，不为每份 PDF 建集合。"""
        if await self.milvus.has_collection(self.collection):
            return
        schema = self.milvus.create_schema(auto_id=False, enable_dynamic_field=False)
        for field, size in [
            ("chunk_id", 256),
            ("question_id", 256),
            ("status", 64),
            ("retrieval_text", 16000),
        ]:
            opts = (
                {"enable_analyzer": True, "analyzer_params": {"type": "chinese"}}
                if field == "retrieval_text"
                else {}
            )
            schema.add_field(
                field,
                DataType.VARCHAR,
                max_length=size,
                is_primary=field == "chunk_id",
                **opts,
            )
        schema.add_field("question_version", DataType.INT64)
        schema.add_field("image_asset_ids", DataType.JSON)
        schema.add_field(
            "dense_vector", DataType.FLOAT_VECTOR, dim=self.settings.embedding_dim
        )
        schema.add_field("sparse_vector", DataType.SPARSE_FLOAT_VECTOR)
        schema.add_function(
            Function(
                name="bm25",
                input_field_names=["retrieval_text"],
                output_field_names=["sparse_vector"],
                function_type=FunctionType.BM25,
            )
        )
        indexes = self.milvus.prepare_index_params()
        indexes.add_index(
            field_name="dense_vector", index_type="AUTOINDEX", metric_type="COSINE"
        )
        indexes.add_index(
            field_name="sparse_vector",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
        )
        await self.milvus.create_collection(
            self.collection,
            schema=schema,
            index_params=indexes,
            consistency_level="Strong",
        )

    async def search(self, data, field, limit, review):
        """向 Milvus 执行指定向量字段查询，普通模式只召回 published 记录。"""
        async with self.gate, asyncio.timeout(self.settings.request_timeout):
            result = await self.milvus.search(
                self.collection,
                data=[data],
                anns_field=field,
                filter="" if review else 'status == "published"',
                limit=limit,
                output_fields=["question_id", "question_version"],
                search_params={
                    "metric_type": "BM25" if field == "sparse_vector" else "COSINE"
                },
                consistency_level="Strong",
            )
        return [hit["entity"] for hit in result[0]]

    async def dense(self, query, limit, review):
        """先生成查询向量，再调用 Milvus COSINE 检索。"""
        return await self.search(
            (await self.embed([query]))[0], "dense_vector", limit, review
        )

    async def sparse(self, query, limit, review):
        """直接把查询文本交给 Milvus 的内建 BM25。"""
        return await self.search(query, "sparse_vector", limit, review)

    async def index(self, chunks):
        """按批生成向量并 upsert；写入后验证主键集合与抽样稀疏召回。"""
        # 同 chunk_id 更新，新增 ID 追加；这不是语义相似去重，也不自动删除旧块。
        fields = (
            "chunk_id",
            "question_id",
            "status",
            "retrieval_text",
            "question_version",
            "image_asset_ids",
        )
        for start in range(0, len(chunks), 10):
            batch = chunks[start : start + 10]
            vectors = await self.embed([c["retrieval_text"] for c in batch])
            rows = [
                dict({key: c[key] for key in fields}, dense_vector=v)
                for c, v in zip(batch, vectors, strict=True)
            ]
            await self.milvus.upsert(self.collection, rows)
        await self.milvus.flush(self.collection)
        import json

        ids = [c["chunk_id"] for c in chunks]
        found = await self.milvus.query(
            self.collection,
            filter="chunk_id in " + json.dumps(ids),
            output_fields=["chunk_id"],
            consistency_level="Strong",
        )
        if {r["chunk_id"] for r in found} != set(ids):
            raise RuntimeError("Index verification failed")
        if chunks:
            hits = await self.sparse(chunks[0]["retrieval_text"], 100, True)
            if not any(h["question_id"] == chunks[0]["question_id"] for h in hits):
                raise RuntimeError("Index search verification failed")
