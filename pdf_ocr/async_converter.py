"""Bounded async OCR; local rendering and writes run on a dedicated worker."""

import asyncio
import hashlib
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import pymupdf

from .client import OCRError
from .layout import render_markdown

# 多个异步转换也共用这把锁，避免在不同线程同时执行 PyMuPDF 操作。
_LOCAL_LOCK = threading.Lock()


def _run_local(fn, *args):
    with _LOCAL_LOCK:
        return fn(*args)


async def convert_pdf_async(
    source,
    output,
    client,
    *,
    start_page=1,
    end_page=None,
    dpi=144,
    concurrency=3,
    progress=None,
):
    from .converter import write_json

    if not 1 <= concurrency <= 16 or not 72 <= dpi <= 300:
        raise ValueError("concurrency must be 1..16 and dpi 72..300")
    source, output = Path(source), Path(output)
    root = output / source.stem
    # 本地渲染、裁图和文件写入放到后台线程，网络请求由事件循环调度。
    pool = ThreadPoolExecutor(max_workers=1)
    loop = asyncio.get_running_loop()

    async def local(fn, *args):
        return await loop.run_in_executor(pool, partial(_run_local, fn, *args))

    def prepare():
        with pymupdf.open(source) as document:
            if not document.is_pdf or document.needs_pass:
                raise ValueError("输入必须是未加密 PDF")
            total = document.page_count
            last = total if end_page is None else end_page
            if not 1 <= start_page <= last <= total:
                raise ValueError("页码范围无效")
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        root.mkdir(parents=True, exist_ok=False)
        return {
            "source": source.name,
            "sha256": digest,
            "total_pages": total,
            "start_page": start_page,
            "end_page": last,
            "status": "processing",
            "pages": [],
        }

    def render(number):
        folder = root / str(number)
        folder.mkdir()
        with pymupdf.open(source) as doc:
            # 用户页码从 1 开始，PyMuPDF 的索引从 0 开始。
            page = doc[number - 1]
            # 按指定 DPI 渲染，同时限制超大页面的像素总量和最长边。
            scale = min(
                dpi / 72,
                (8_000_000 / (page.rect.width * page.rect.height)) ** 0.5,
                8000 / max(page.rect.width, page.rect.height),
            )
            png = page.get_pixmap(
                matrix=pymupdf.Matrix(scale, scale),
                colorspace=pymupdf.csRGB,
                alpha=False,
            ).tobytes("png")
        (folder / "page.png").write_bytes(png)
        return png

    def save(number, layout, png):
        folder = root / str(number)
        markdown = render_markdown(layout, png)
        write_json(folder / "layout.json", layout.model_dump())
        (folder / f"{number}.md").write_text(markdown + "\n", encoding="utf-8")

    try:
        manifest = await local(prepare)
        await local(write_json, root / "manifest.json", manifest)
        lock = asyncio.Lock()

        # 每页独立识别和写入，已知的页面错误记录到清单，其他页继续处理。
        async def page_job(number):
            try:
                png = await local(render, number)
                layout = await client.recognize(png)
                await local(save, number, layout, png)
                record = {
                    "page": number,
                    "status": "completed",
                    "markdown": f"{number}/{number}.md",
                }
            except (OCRError, ValueError, RuntimeError) as exc:
                record = {
                    "page": number,
                    "status": "failed",
                    "error": str(exc)
                    if isinstance(exc, OCRError)
                    else "页面渲染或布局处理失败",
                }
            # 并发请求可能乱序返回，持锁更新清单并按原始页码排序。
            async with lock:
                manifest["pages"].append(record)
                manifest["pages"].sort(key=lambda p: p["page"])
                await local(write_json, root / "manifest.json", manifest)
            if progress:
                progress(number, manifest["end_page"], record["status"])

        # 当前批次结束后再启动下一批，限制在途请求和内存中的页图数量。
        for first in range(start_page, manifest["end_page"] + 1, concurrency):
            async with asyncio.TaskGroup() as group:
                for number in range(
                    first, min(first + concurrency, manifest["end_page"] + 1)
                ):
                    group.create_task(page_job(number))
        manifest["status"] = (
            "partial_failure"
            if any(p["status"] == "failed" for p in manifest["pages"])
            else "completed"
        )
        await local(write_json, root / "manifest.json", manifest)
        return manifest
    finally:
        # 等待正在执行的本地操作收尾，在线程外关闭线程池。
        await asyncio.to_thread(pool.shutdown, wait=True, cancel_futures=True)
