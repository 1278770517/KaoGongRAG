import argparse
import sys
from pathlib import Path

import httpx
from pydantic import ValidationError

from pdf_ocr.client import OCRClient
from pdf_ocr.config import Settings
from pdf_ocr.converter import convert_pdf


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="逐页 OCR 解析 PDF，图片以 Base64 内嵌 Markdown"
    )
    parser.add_argument("pdf", type=Path, help="输入 PDF 文件")
    parser.add_argument(
        "--output", type=Path, default=Path("output"), help="输出根目录（默认 output）"
    )
    parser.add_argument(
        "--start-page", type=int, default=1, help="起始页，含本页，从 1 开始"
    )
    parser.add_argument("--end-page", type=int, help="结束页，含本页，默认最后一页")
    parser.add_argument("--env-file", type=Path, default=Path(__file__).parent / ".env")
    args = parser.parse_args(argv)
    try:
        settings = Settings(_env_file=args.env_file)
        with httpx.Client(follow_redirects=False) as http:
            result = convert_pdf(
                args.pdf,
                args.output,
                OCRClient(settings, http=http),
                start_page=args.start_page,
                end_page=args.end_page,
                dpi=settings.ocr_dpi,
                progress=lambda page, last, status: print(
                    f"[{page}/{last}] {status}", flush=True
                ),
            )
    except ValidationError:
        print("配置无效：请检查 .env 中 OCR_API_KEY、地址及数值范围。", file=sys.stderr)
        return 2
    except FileExistsError:
        print("输出目录已存在，请用 --output 指定新的目录。", file=sys.stderr)
        return 2
    except (OSError, ValueError, RuntimeError) as exc:
        print(
            f"转换无法完成（{type(exc).__name__}），请检查输入文件和输出权限。",
            file=sys.stderr,
        )
        return 2
    print(f"结果目录：{(args.output / args.pdf.stem).resolve()}")
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
