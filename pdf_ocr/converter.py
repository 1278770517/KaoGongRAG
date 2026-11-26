from .async_converter import convert_pdf_async

__all__ = ["convert_pdf", "convert_pdf_async"]
import hashlib
import json
from pathlib import Path
from typing import Protocol

import pymupdf
from openai import AsyncOpenAI

from pdf_ocr.client import OCRError
from pdf_ocr.layout import Layout, render_markdown


class Recognizer(Protocol):
    def recognize(self, png: bytes) -> Layout: ...


def write_json(path: Path, value: dict):
    # 先写入临时文件再替换，读取方不会遇到只写了一半的 JSON。
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


# 同步兼容入口，按页依次渲染、识别并保存。
def convert_pdf(
    source: Path,
    output: Path,
    client: Recognizer,
    *,
    start_page: int = 1,
    end_page: int | None = None,
    dpi: int = 144,
    progress=None,
) -> dict:
    source, output = Path(source), Path(output)
    if not 72 <= dpi <= 300:
        raise ValueError("DPI 必须在 72..300 之间")
    with pymupdf.open(source) as document:
        if not document.is_pdf or document.needs_pass:
            raise ValueError("输入必须是未加密的 PDF")
        last = document.page_count if end_page is None else end_page
        if not 1 <= start_page <= last <= document.page_count:
            raise ValueError(f"页码范围无效；此文件共 {document.page_count} 页")
        root = output / source.stem
        root.mkdir(parents=True, exist_ok=False)
        with source.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        manifest = {
            "source": source.name,
            "sha256": digest,
            "total_pages": document.page_count,
            "start_page": start_page,
            "end_page": last,
            "status": "processing",
            "pages": [],
        }
        write_json(root / "manifest.json", manifest)
        for number in range(start_page, last + 1):
            folder = root / str(number)
            folder.mkdir()
            try:
                page = document[number - 1]
                scale = min(
                    dpi / 72,
                    (8_000_000 / (page.rect.width * page.rect.height)) ** 0.5,
                    8000 / max(page.rect.width, page.rect.height),
                )
                pixmap = page.get_pixmap(
                    matrix=pymupdf.Matrix(scale, scale),
                    colorspace=pymupdf.csRGB,
                    alpha=False,
                )
                png = pixmap.tobytes("png")
                (folder / "page.png").write_bytes(png)
                layout = client.recognize(png)
                markdown = render_markdown(layout, png)
                write_json(folder / "layout.json", layout.model_dump())
                (folder / f"{number}.md").write_text(markdown + "\n", encoding="utf-8")
                record = {
                    "page": number,
                    "status": "completed",
                    "markdown": f"{number}/{number}.md",
                }
            except (OCRError, ValueError, RuntimeError) as exc:
                message = (
                    str(exc) if isinstance(exc, OCRError) else "页面渲染或布局处理失败"
                )
                record = {"page": number, "status": "failed", "error": message}
            manifest["pages"].append(record)
            write_json(root / "manifest.json", manifest)
            if progress:
                progress(number, last, record["status"])
        manifest["status"] = (
            "partial_failure"
            if any(p["status"] == "failed" for p in manifest["pages"])
            else "completed"
        )
        write_json(root / "manifest.json", manifest)
        return manifest


async def _example():
    from pdf_ocr.client import AsyncOCRClient
    from pdf_ocr.config import Settings

    settings = Settings()

    async with AsyncOpenAI(
        api_key=settings.ocr_api_key.get_secret_value(),
        base_url=settings.ocr_base_url,
        max_retries=0,
        timeout=settings.ocr_timeout,
    ) as sdk:
        # 创建 OCR 模型客户端
        client = AsyncOCRClient(settings, sdk=sdk)

        # 逐页识别并保存 Markdown
        result = await convert_pdf_async(
            source=r"D:\KaoGongRAG\2023公考公基常识必刷600题-解析册_第2-100页.pdf",
            output=r"D:\KaoGongRAG\output",
            client=client,
            start_page=1,
            end_page=5,  # None 表示处理到最后一页
            dpi=settings.ocr_dpi,
            concurrency=settings.ocr_concurrency,
        )

    print(result["status"])


if __name__ == "__main__":
    import asyncio

    asyncio.run(_example())
