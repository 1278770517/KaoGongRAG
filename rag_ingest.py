"""五页实验入库工具及共享选择题解析器；正式父题与图片导入见 rag_service。"""

import argparse
import asyncio
import hashlib
import json
import math
import re
from contextlib import AsyncExitStack
from pathlib import Path

from openai import AsyncOpenAI
from pymilvus import AsyncMilvusClient, DataType, Function, FunctionType

from pdf_ocr.config import Settings


def digest(text):
    """生成稳定 SHA256，用于来源、内容或记录标识。"""
    return hashlib.sha256(text.encode()).hexdigest()


def validate_vector(vector, dim):
    """拒绝维度错误、NaN/Inf 和全零向量，避免无效索引。"""
    if (
        len(vector) != dim
        or not all(math.isfinite(x) for x in vector)
        or not any(vector)
    ):
        raise ValueError("Invalid embedding")


def parse_pages(pages, document):
    """按题号和答案边界跨页组装父题，再生成 question/evidence 视图；不跨题滑窗。"""
    parents, current = [], None
    for page, blocks in pages:
        for block in blocks:
            if block["type"] == "image":
                if current:
                    current["images"].append({"page": page, **block})
                continue
            text = block.get("markdown", "")
            if re.fullmatch(
                r"\s*第\s*\d+\s*页\s*共\s*\d+\s*页\s*", text
            ) or text.startswith("更多资料添加"):
                continue
            for part in re.split(
                r"(?m)(?=^\s*\d+[.．、]\s*[（(](?:单选|多选)[）)])", text
            ):
                if not part.strip():
                    continue
                match = re.match(r"\s*(\d+)[.．、]\s*[（(](单选|多选)[）)]", part)
                if match:
                    if current:
                        parents.append(current)
                    current = {
                        "question_id": digest(f"{document}:{page}:{match[1]}"),
                        "number": int(match[1]),
                        "raw_text": "",
                        "source_pages": [],
                        "images": [],
                    }
                if current:
                    current["raw_text"] += part + "\n"
                    if page not in current["source_pages"]:
                        current["source_pages"].append(page)
    if current:
        parents.append(current)
    chunks = []
    for i, parent in enumerate(parents):
        text = re.sub(r"[（(]微信公众号[：:][^）)]*[）)]", "", parent["raw_text"])
        sections = re.split(r"【答案】", text, maxsplit=1)
        question = sections[0].strip()
        answer = re.match(r"\s*([A-D]+)", sections[1]) if len(sections) == 2 else None
        parent["status"] = (
            "needs_review"
            if i == len(parents) - 1 or parent["images"] or not answer
            else "unreviewed"
        )
        parent["answer"] = answer[1] if answer else None
        parent["question_text"] = question
        options = dict(
            re.findall(
                r"([A-D])[.．、]\s*(.*?)(?=\s+[A-D][.．、]|$)", question, re.DOTALL
            )
        )
        parent["options"] = options
        views = [("question", "题目候选陈述/正确性待判定：\n" + question)]
        if answer:
            actual = "；".join(
                options.get(letter, "[选项缺失]") for letter in answer[1]
            )
            evidence = re.split(r"【解析】", sections[1], maxsplit=1)
            if len(evidence) == 2:
                for piece in re.split(r"(?=【拓展】)", evidence[1]):
                    if piece.strip():
                        views.append(
                            (
                                "evidence",
                                f"题干上下文：{question}\n参考答案：{answer[1]} {actual}\n解析依据：{piece.strip()}",
                            )
                        )
        for ordinal, (view, content) in enumerate(views):
            # Conservative pilot guard, not a substitute for the model tokenizer.
            if len(content.encode()) > 7500:
                raise ValueError(
                    "Chunk exceeds pilot byte guard; requires tokenizer-aware splitting"
                )
            chunks.append(
                {
                    "chunk_id": digest(f"{parent['question_id']}:{ordinal}:{content}"),
                    "question_id": parent["question_id"],
                    "question_version": 1,
                    "view_type": view,
                    "chunk_ordinal": ordinal,
                    "source_document_id": document,
                    "source_pages": parent["source_pages"],
                    "content_hash": digest(content),
                    "index_generation": "pilot_v1",
                    "status": parent["status"],
                    "visibility": "test_only",
                    "tenant_id": "shared",
                    "question_type": "choice",
                    "exam_category": "公基常识",
                    "has_image": bool(parent["images"]),
                    "image_description_status": "missing"
                    if parent["images"]
                    else "not_applicable",
                    "retrieval_text": content,
                }
            )
    return parents, chunks


def validate_sparse(hits, expected_parent):
    """验收 BM25 候选中是否包含指定父题。"""
    if not any(hit["entity"]["question_id"] == expected_parent for hit in hits):
        raise ValueError("BM25 failed to retrieve expected parent")


def _prepare(source):
    """同步读取五页布局并输出父题和分块文件；由异步入口放入线程执行。"""
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    selected = [
        p for p in manifest["pages"] if p["status"] == "completed" and p["page"] <= 5
    ]
    if [p["page"] for p in selected] != [1, 2, 3, 4, 5]:
        raise ValueError("Pilot requires completed pages 1 through 5")
    pages = [
        (
            p["page"],
            json.loads(
                (source / str(p["page"]) / "layout.json").read_text(encoding="utf-8")
            )["blocks"],
        )
        for p in selected
    ]
    parents, chunks = parse_pages(pages, manifest["sha256"])
    out = source / "rag_pilot"
    out.mkdir(exist_ok=True)
    for name, data in [("parents", parents), ("chunks", chunks)]:
        (out / f"{name}.json").write_text(
            json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return parents, chunks, out


def _read_json(path):
    """同步读取 JSON；异步流程通过 to_thread 调用。"""
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path, value):
    """同步序列化并写入 JSON；异步流程通过 to_thread 调用。"""
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


async def ingest(
    source: Path,
    *,
    collection="kaogong_pilot_5pages_v1",
    write=False,
    verify_only=False,
):
    """可 await 的实验导入入口；调用方应限制并发任务数，不在接口内调用 main。"""
    if write and verify_only:
        raise ValueError("write and verify_only are mutually exclusive")
    parents, chunks, out = await asyncio.to_thread(_prepare, Path(source))
    summary = {
        "parents": len(parents),
        "chunks": len(chunks),
        "review": [p["number"] for p in parents if p["status"] == "needs_review"],
    }
    if not write and not verify_only:
        return summary
    async with AsyncExitStack() as stack:
        client = AsyncMilvusClient(uri="http://localhost:19530", timeout=30)
        stack.push_async_callback(client.close)
        if await client.has_collection(collection) and not verify_only:
            raise ValueError(
                "Collection exists; choose a new name to preserve previous run"
            )
        settings = await asyncio.to_thread(Settings)
        api = await stack.enter_async_context(
            AsyncOpenAI(
                api_key=settings.ocr_api_key.get_secret_value(),
                base_url=settings.ocr_base_url,
                timeout=120,
                max_retries=2,
            )
        )
        return await _index(client, api, parents, chunks, out, collection, verify_only)


async def _index(client, api, parents, chunks, out, collection, verify_only):
    """异步生成或读取实验向量，创建索引并验证计数、BM25 与 dense 命中。"""
    model, dim = "text-embedding-v4", 1024
    tokens = 0
    for row in chunks:
        cache = out / f"{model}_{row['content_hash']}.json"
        if await asyncio.to_thread(cache.exists):
            vector = await asyncio.to_thread(_read_json, cache)
        else:
            result = await api.embeddings.create(
                model=model,
                input=[row["retrieval_text"]],
                dimensions=dim,
                encoding_format="float",
            )
            if len(result.data) != 1 or result.data[0].index != 0:
                raise ValueError("Embedding response mapping mismatch")
            vector = result.data[0].embedding
            tokens += result.usage.total_tokens
            validate_vector(vector, dim)
            await asyncio.to_thread(_write_json, cache, vector)
        validate_vector(vector, dim)
        row["dense_vector"] = vector
    schema = client.create_schema(auto_id=False, enable_dynamic_field=False)
    for key in chunks[0]:
        if key == "dense_vector":
            schema.add_field(key, DataType.FLOAT_VECTOR, dim=dim)
        elif key == "source_pages":
            schema.add_field(key, DataType.JSON)
        elif isinstance(chunks[0][key], bool):
            schema.add_field(key, DataType.BOOL)
        elif isinstance(chunks[0][key], int):
            schema.add_field(key, DataType.INT64)
        else:
            kwargs = {"max_length": 16000 if key == "retrieval_text" else 256}
            if key == "retrieval_text":
                kwargs.update(enable_analyzer=True, analyzer_params={"type": "chinese"})
            schema.add_field(
                key, DataType.VARCHAR, is_primary=key == "chunk_id", **kwargs
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
    indexes = client.prepare_index_params()
    indexes.add_index(
        field_name="sparse_vector",
        index_type="SPARSE_INVERTED_INDEX",
        metric_type="BM25",
    )
    indexes.add_index(
        field_name="dense_vector",
        index_type="HNSW",
        metric_type="COSINE",
        params={"M": 16, "efConstruction": 128},
    )
    analyzer = await client.run_analyzer(
        texts=["围魏救赵 孙膑 孙武 桂陵 马陵 淝水"], analyzer_params={"type": "chinese"}
    )
    if not verify_only:
        await client.create_collection(
            collection,
            schema=schema,
            index_params=indexes,
            consistency_level="Strong",
        )
        await client.insert(collection, chunks)
        await client.flush(collection)
    await client.load_collection(collection)
    count = (await client.query(collection, filter="", output_fields=["count(*)"]))[0][
        "count(*)"
    ]
    if count != len(chunks):
        raise ValueError(f"Count mismatch: {count}")
    results = {}
    for query in ["牧野之战", "鹿台 秦始皇", "首因效应"]:
        results[query] = await client.search(
            collection,
            data=[query],
            anns_field="sparse_vector",
            limit=3,
            output_fields=["question_id", "view_type", "retrieval_text"],
            search_params={"metric_type": "BM25"},
        )
    expected = dict(
        zip(["牧野之战", "鹿台 秦始皇", "首因效应"], [1, 9, 10], strict=True)
    )
    for query, number in expected.items():
        parent = next(p for p in parents if p["number"] == number)
        validate_sparse(results[query][0], parent["question_id"])
    dense = await client.search(
        collection,
        data=[chunks[0]["dense_vector"]],
        anns_field="dense_vector",
        limit=1,
        output_fields=["chunk_id"],
        search_params={"metric_type": "COSINE", "params": {"ef": 32}},
    )
    if dense[0][0]["entity"]["chunk_id"] != chunks[0]["chunk_id"]:
        raise ValueError("Dense self retrieval failed")
    report = {
        "collection": collection,
        "server": await client.get_server_version(),
        "model": model,
        "dimension": dim,
        "count": count,
        "parents": len(parents),
        "api_tokens_this_run": tokens,
        "analyzer": [item.tokens for item in analyzer],
        "sparse_results": results,
        "dense_self_match": True,
        "production_ready": False,
    }
    await asyncio.to_thread(_write_json, out / "report.json", report)
    return report


def main():
    """命令行同步边界：创建事件循环运行 ingest；HTTP 接口应直接 await ingest。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--collection", default="kaogong_pilot_5pages_v1")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--write", action="store_true")
    modes.add_argument("--verify-only", action="store_true")
    args = parser.parse_args()
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        result = runner.run(
            ingest(
                args.source,
                collection=args.collection,
                write=args.write,
                verify_only=args.verify_only,
            )
        )
    print(
        json.dumps(
            {k: v for k, v in result.items() if k not in ("sparse_results", "analyzer")}
        )
    )


if __name__ == "__main__":
    main()
