"""检索流程协调：并发召回、单路降级、批量回表和父题排名融合。"""

import asyncio


def public_parent(parent, review=False):
    """普通模式仅返回题干白名单字段；审核模式返回完整父题及可访问的图片 URL。"""
    value = (
        dict(parent)
        if review
        else {
            k: parent[k]
            for k in (
                "question_id",
                "question_version",
                "number",
                "question_text",
                "options",
                "image_asset_ids",
                "source_pages",
            )
            if k in parent
        }
    )
    if not review:
        for key in (
            "answer",
            "analysis",
            "explanation",
            "answer_text",
            "analysis_text",
        ):
            value.pop(key, None)
    value["image_urls"] = [
        f"/assets/{asset}" + ("?review=true" if review else "")
        for asset in parent.get("image_asset_ids", [])
    ]
    return value


async def retrieve(query, repo, providers, limit=10, review=False, timeout=30):
    """并发调用 providers 的两路 Milvus 召回，再批量读取 SQL 父题并融合排名。"""

    async def route(name):
        """动态选择 dense/sparse 方法，隔离单路超时；取消异常继续向调用者传播。"""
        try:
            async with asyncio.timeout(timeout):
                # name 为 dense/sparse：实际调用在 providers.py，asyncio 仅负责调度。
                return await getattr(providers, name)(query, limit * 5, review)
        except Exception:  # noqa: BLE001 - dependency boundary; cancellation propagates
            return None

    # 两路网络等待可重叠；一条失败仍保留另一条正常结果。
    dense, sparse = await asyncio.gather(route("dense"), route("sparse"))
    degraded = [
        name for name, hits in [("dense", dense), ("sparse", sparse)] if hits is None
    ]
    if len(degraded) == 2:
        raise RuntimeError("All retrieval routes unavailable")
    ids = {h["question_id"] for hits in (dense, sparse) for h in (hits or [])}
    # Milvus 只返回候选标识；SQL 批量补齐父题，并执行状态过滤。
    parents = await repo.hydrate(ids, review=review)
    scores = {}
    for hits in (dense, sparse):
        seen = set()
        for rank, hit in enumerate(hits or [], 1):
            key = hit["question_id"]
            parent = parents.get(key)
            if (
                parent
                and parent["question_version"] == hit["question_version"]
                and key not in seen
            ):
                # 按 chunk 排名计算父题 RRF，每路每题只计一次；60 为平滑常数。
                # 比较排名而非直接相加 COSINE 与 BM25 的不同分值。
                scores[key] = scores.get(key, 0) + 1 / (60 + rank)
                seen.add(key)
    return {
        "results": [
            dict(public_parent(parents[key], review), score=scores[key])
            for key in sorted(scores, key=scores.get, reverse=True)[:limit]
        ],
        "degraded": degraded,
    }
