"""布局 JSON 导入命令行入口；与读取 Markdown 的 HTTP 导入接口分开。"""

import argparse
import asyncio
import json
from pathlib import Path

from psycopg_pool import AsyncConnectionPool

from rag_ingest import digest, parse_pages

from .assets import crop_asset
from .config import Settings
from .repository import Repository


def prepare(source: Path, asset_root: Path, max_pages: int = 5):
    """读取指定连续页的布局，生成父题版本及图片资源；缺页立即报错。"""
    manifest = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    pages = [
        p
        for p in manifest["pages"]
        if p["page"] <= max_pages and p["status"] == "completed"
    ]
    if [p["page"] for p in pages] != list(range(1, max_pages + 1)):
        raise ValueError("Requires exactly the existing completed pages 1 through 5")
    layouts = [
        (
            p["page"],
            json.loads(
                (source / str(p["page"]) / "layout.json").read_text(encoding="utf-8")
            )["blocks"],
        )
        for p in pages
    ]
    parents, chunks = parse_pages(layouts, manifest["sha256"])
    assets = []
    for parent in parents:
        parent["question_version"] = int(
            digest(json.dumps(parent, sort_keys=True, ensure_ascii=False))[:15], 16
        )
        parent["image_asset_ids"] = []
        for image in parent["images"]:
            asset_id = crop_asset(
                source / str(image["page"]) / "page.png", image["bbox"], asset_root
            )
            parent["image_asset_ids"].append(asset_id)
            assets.append(
                {
                    "asset_id": asset_id,
                    "question_id": parent["question_id"],
                    "page": image["page"],
                    "bbox": image["bbox"],
                }
            )
    by_id = {p["question_id"]: p for p in parents}
    for chunk in chunks:
        chunk["question_version"] = by_id[chunk["question_id"]]["question_version"]
        chunk["image_asset_ids"] = by_id[chunk["question_id"]]["image_asset_ids"]
        chunk["index_generation"] = "service_v1"
    # Fail closed for long input until provider tokenizer identity is verified.
    for chunk in chunks:
        if len(chunk["retrieval_text"].encode("utf-8")) > 7500:
            raise ValueError("Long input requires a verified model tokenizer")
    return parents, chunks, assets


async def stage(source, max_pages=5):
    """在线程中准备文件与图片，再用短 SQL 事务暂存索引任务。"""
    settings = Settings()
    prepared = await asyncio.to_thread(prepare, source, settings.asset_root, max_pages)
    async with AsyncConnectionPool(
        settings.conninfo, open=False, min_size=1, max_size=settings.concurrency
    ) as pool:
        repo = Repository(pool)
        await repo.initialize()
        print(await repo.stage(*prepared))


def main():
    """保留布局导入 CLI，选择 SelectorEventLoop 兼容 Windows 异步 PostgreSQL。"""
    parser = argparse.ArgumentParser(
        description="Stage existing five-page OCR; never invokes OCR"
    )
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--max-pages", type=int, default=5)
    args = parser.parse_args()
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(stage(args.source, args.max_pages))


if __name__ == "__main__":
    main()
