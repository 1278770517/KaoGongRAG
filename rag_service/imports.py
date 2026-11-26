"""两阶段导入适配：Markdown 提供正文，布局和页图提供图片来源。"""

import asyncio
import json
import re
import uuid
from pathlib import Path

from rag_ingest import digest, parse_pages

from .assets import crop_asset


def contained(root, path):
    """解析真实路径并限定在指定根目录内，拒绝越界路径及根目录本身。"""
    root, path = Path(root).resolve(), Path(path).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError("Path must be inside the output directory")
    return path


def markdown_blocks(text, layout):
    """读取 MD 正文，并按图片出现顺序接回布局信息；数量不一致则拒绝。"""
    images = [b for b in layout if b["type"] == "image"]
    pattern = r"!\[(?:\\.|[^\]])*\]\(data:image/png;base64,[A-Za-z0-9+/=\s]+\)"
    matches = list(re.finditer(pattern, text))
    if len(matches) != len(images):
        raise ValueError("Markdown images do not match layout provenance")
    blocks, position = [], 0
    for match, image in zip(matches, images, strict=True):
        blocks.extend(
            {"type": "text", "markdown": part}
            for part in re.split(r"\n\s*\n", text[position : match.start()])
            if part.strip()
        )
        blocks.append(image)
        position = match.end()
    blocks.extend(
        {"type": "text", "markdown": part}
        for part in re.split(r"\n\s*\n", text[position:])
        if part.strip()
    )
    return blocks


def prepare_markdown(path, output_root, asset_root):
    """读取 manifest 全部选定页，构建父题、分块及图片；同步工作由接口移到线程。"""
    path = contained(output_root, path)
    if path.is_file():
        if path.suffix.lower() != ".md":
            raise ValueError("Expected Markdown or OCR directory")
        source = path.parent.parent
    else:
        source = path
    source = contained(output_root, source)
    manifest = json.loads(
        contained(source, source / "manifest.json").read_text(encoding="utf-8")
    )
    records = manifest["pages"]
    if (
        manifest["status"] != "completed"
        or [p["page"] for p in records]
        != list(range(manifest["start_page"], manifest["end_page"] + 1))
        or any(p["status"] != "completed" for p in records)
    ):
        raise ValueError("Incomplete OCR page range")
    layouts, md_paths = [], []
    for record in records:
        page = record["page"]
        md = contained(source, source / record["markdown"])
        md_paths.append(md)
        text = md.read_text(encoding="utf-8")
        layout = json.loads(
            contained(source, source / str(page) / "layout.json").read_text(
                encoding="utf-8"
            )
        )
        blocks = markdown_blocks(text, layout["blocks"])
        layouts.append((page, blocks))
    if path.is_file() and path not in md_paths:
        raise ValueError("Markdown not listed in manifest")
    parents, chunks = parse_pages(layouts, manifest["sha256"])
    if not parents:
        raise ValueError("Unsupported Markdown: no recognized questions")
    # 首题之前的标题/前言不属于题目正文，单独保留，避免静默丢弃。
    first_text = "\n".join(b.get("markdown", "") for _, bs in layouts for b in bs)
    prefix = re.split(
        r"(?m)^\s*\d+[.．、]\s*[（(](?:单选|多选)[）)]", first_text, maxsplit=1
    )[0]
    prefix = re.sub(r"第\s*\d+\s*页\s*共\s*\d+\s*页|更多资料添加[^\n]*", "", prefix)
    # Keep introductory document text explicitly; it is not a question chunk.
    for parent in parents:
        parent["document_preamble"] = prefix.strip()
    assets = []
    for parent in parents:
        parent["question_version"] = int(
            digest(json.dumps(parent, sort_keys=True, ensure_ascii=False))[:15], 16
        )
        parent["image_asset_ids"] = []
        for image in parent["images"]:
            png = contained(source, source / str(image["page"]) / "page.png")
            asset_id = crop_asset(png, image["bbox"], asset_root)
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
        parent = by_id[chunk["question_id"]]
        chunk.update(
            question_version=parent["question_version"],
            image_asset_ids=parent["image_asset_ids"],
            index_generation="service_v1",
        )
        chunk["chunk_id"] = digest(f"{chunk['chunk_id']}:{parent['question_version']}")
    return parents, chunks, assets


async def upload_pdf(request, output_root, end_page, gate):
    """限流上传并调用现有异步 OCR；返回解析路径和 manifest，不直接索引。"""
    from pdf_ocr.async_converter import convert_pdf_async
    from pdf_ocr.client import AsyncOCRClient
    from pdf_ocr.config import Settings

    async with asyncio.timeout(1800), gate:
        folder = Path(output_root).resolve() / uuid.uuid4().hex
        await asyncio.to_thread(folder.mkdir, parents=True)
        source = folder / "upload.pdf"
        stream = await asyncio.to_thread(source.open, "xb")
        size, header = 0, b""
        try:
            async for part in request.stream():
                size += len(part)
                header = (header + part)[:5]
                if size > 100 * 1024 * 1024:
                    raise ValueError("PDF exceeds 100 MiB")
                await asyncio.to_thread(stream.write, part)
        finally:
            await asyncio.to_thread(stream.close)
        if header != b"%PDF-":
            raise ValueError("Expected PDF bytes")
        settings = await asyncio.to_thread(Settings)
        client = AsyncOCRClient(settings)
        try:
            manifest = await convert_pdf_async(
                source,
                folder,
                client,
                end_page=end_page,
                concurrency=getattr(settings, "ocr_concurrency", 3),
                dpi=getattr(settings, "ocr_dpi", 144),
            )
        finally:
            await client.sdk.close()
        root = folder / source.stem
        return {
            "directory": str(root),
            "markdown_paths": [
                str(root / p["markdown"])
                for p in manifest["pages"]
                if p["status"] == "completed"
            ],
            "manifest": manifest,
        }
