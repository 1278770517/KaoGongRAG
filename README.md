# PDF 逐页 OCR 转 Markdown

使用 Qwen 视觉模型执行 OCR，识别每页文字、表格、公式及图片区域；保持模型返回的阅读顺序，将图片裁剪成 PNG 并以 Base64 嵌入 Markdown。支持文本 PDF 和扫描 PDF。

默认 `OCR_MODEL=qwen3-vl-plus`。真实合成文档联调中，原来的 `qwen-vl-ocr-2025-11-20` 能识别文字，但出现无效图片坐标或漏图；`qwen3-vl-plus` 通过了同一双栏插图页的顺序和裁图核验。因此本地 `.env` 已改用后者。模型可配置，但请用含插图的样本验证后再替换。

## 使用

项目根目录 PowerShell：

```powershell
./uv.ps1 sync --locked
# 首次配置时使用；已有 .env 时不要覆盖
Copy-Item .env.example .env
# 编辑 .env，填入 OCR_API_KEY 和对应地域/工作空间的 OCR_BASE_URL
./.venv/Scripts/python.exe main.py "试卷.pdf"
# 只解析第 2 到 5 页，保留原始页码
./.venv/Scripts/python.exe main.py "试卷.pdf" --start-page 2 --end-page 5
```

现有脚本配置已迁移至忽略的 `.env`。环境变量优先于 `.env`；`--env-file` 可指定配置文件。密钥不得提交。`OCR_BASE_URL` 使用 OpenAI 兼容接口地址，当前为 `https://ws-nzz9m16u7c5um2ek.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`。调用通过 `OpenAI(...).chat.completions.create(...)` 完成；不要填写原生 `/api/v1` 地址。

输出为 `output/试卷/1/1.md`、`output/试卷/2/2.md` 等。每个页目录还保存 `page.png` 和 `layout.json` 供核对，文件名目录下保存 `manifest.json` 汇总状态。布局图片坐标归一化为 0–1000。

Markdown 图片形如 `![图片](data:image/png;base64,...)`，不依赖外部图片文件。请使用支持 data URI 的 Markdown 阅读器，部分平台（包括 GitHub Markdown 预览）会过滤它。

逐页处理及保存。已存在同名输出目录时拒绝覆盖；重新运行用 `--output output/另一次运行`。仅选择失败页重试时仍需指定新输出根目录。

退出码：0 全部成功，1 有页面失败，2 输入/配置/输出错误。失败页记录在 manifest.json，继续处理后续页。网络、限流、服务器或格式错误最多重试 `OCR_RETRIES` 次；认证错误直接失败。响应截断时标记失败，可调高 `OCR_MAX_TOKENS`（受模型限制）。中断时 manifest 保留 processing 状态和已完成页。

## 阅读顺序和边界

`OCR_MAX_TOKENS` 默认 4096；提高前请确认模型与账号支持对应的输出上限。

模型按通栏标题、多栏栏内顺序、题干选项、图片及页脚返回内容块；程序保留顺序，不以坐标简单排序，也不把图片统一放到末尾。图片从原页渲染图按模型区域裁剪，扫描页及矢量图同样可处理。旋转页使用显示方向。

这能防止程序拼接导致乱序，但 OCR 仍可能漏字、错判分栏或图片边界，无法承诺所有版面自动正确。复杂题库请对照 page.png 和 layout.json 抽查。目标是阅读顺序，不是原版式复刻。合并单元格等复杂表格在 Markdown 中表达有限。PDF 页面会发送至 `.env` 配置的 OCR 服务。

接口依据：[阿里云 Qwen OCR 官方文档](https://www.alibabacloud.com/help/en/model-studio/qwen-vl-ocr-api-reference)。通过 OpenAI SDK 发送 image_url 与布局提示词，读取 choices[0].message.content。SDK 内置重试关闭，统一由 OCR_RETRIES 控制网络和布局错误的重试次数。

## 验证

```powershell
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m ruff check main.py pdf_ocr tests
```

## 异步调用

CLI 现在使用 AsyncOpenAI 和 convert_pdf_async，.env 的 OCR_CONCURRENCY 默认 3（范围 1–16）。按有限批次并发识别，页图内存随并发数而非总页数增长。渲染、哈希、裁图和磁盘写入在后台串行执行，API 请求及重试等待不阻塞事件循环。完成日志可能乱序，但目录与 manifest 始终按原页码对应。

```python
from pathlib import Path
from openai import AsyncOpenAI
from pdf_ocr.config import Settings
from pdf_ocr.client import AsyncOCRClient
from pdf_ocr.converter import convert_pdf_async

async def convert():
    settings = Settings()
    async with AsyncOpenAI(api_key=settings.ocr_api_key.get_secret_value(),
                           base_url=settings.ocr_base_url, max_retries=0) as sdk:
        return await convert_pdf_async(
            Path("试卷.pdf"), Path("output"), AsyncOCRClient(settings, sdk=sdk),
            concurrency=settings.ocr_concurrency, dpi=settings.ocr_dpi)
```

在已有异步服务中直接 `await convert()`；普通脚本用 `asyncio.run(convert())`。原 convert_pdf/OCRClient 保留为同步兼容接口。异步不是持久任务队列；请求需要立即返回任务 ID 时仍需额外任务系统。取消时停止调度剩余页，已保存结果保留，manifest 不会误标为完成。
