"""FastAPI 入口：共享异步连接，提供两阶段导入、混合检索和图片读取接口。"""

import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from psycopg_pool import AsyncConnectionPool
from pydantic import BaseModel, Field, field_validator

from rag_service.assets import asset_path
from rag_service.config import CorsSettings, Settings
from rag_service.providers import Providers
from rag_service.repository import Repository
from rag_service.retrieval import public_parent, retrieve


@asynccontextmanager
async def lifespan(app):
    """启动时创建共享连接和客户端，关闭时释放；避免每个请求重复建连接。"""
    settings = Settings()
    async with AsyncConnectionPool(
        settings.conninfo,
        open=False,
        min_size=1,
        max_size=settings.concurrency,
        timeout=settings.request_timeout,
    ) as pool:
        providers = Providers(settings)
        try:
            repo = Repository(pool)
            await repo.initialize()
            await providers.initialize()
            app.state.settings = settings
            app.state.repo = repo
            app.state.providers = providers
            yield
        finally:
            await providers.close()


app = FastAPI(lifespan=lifespan)
# 精确匹配前端 Origin（含协议和端口）；配置在启动时读取，修改后需重启。
app.add_middleware(
    CORSMiddleware,
    allow_origins=CorsSettings().origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
upload_gate = asyncio.Semaphore(1)


class ImportMarkdown(BaseModel):
    """第二步入库参数；失败任务必须显式请求重试。"""

    path: str = Field(min_length=1)
    retry_failed: bool = False


@app.post("/imports/pdf")
async def import_pdf(
    request: Request, end_page: int = Query(default=10, ge=1, le=1000)
):
    """接受原始 PDF 或 multipart file，调用 OCR 并返回文件路径及逐页状态。"""
    from rag_service.imports import upload_pdf

    try:
        if request.headers.get("content-type", "").startswith("multipart/form-data"):
            async with request.form(max_files=1, max_fields=2) as form:
                file = form.get("file")
                if file is None or not hasattr(file, "read"):
                    raise HTTPException(422, "Expected multipart file field")

                class StreamUpload:
                    """将 multipart 文件适配成与原始请求体一致的分块流。"""

                    async def stream(self):
                        """分块读取上传文件，避免一次性读入整个 PDF。"""
                        while part := await file.read(1024 * 1024):
                            yield part

                return await upload_pdf(StreamUpload(), "output", end_page, upload_gate)
        return await upload_pdf(request, "output", end_page, upload_gate)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    except TimeoutError:
        raise HTTPException(504, "OCR deadline exceeded")


@app.post("/imports/markdown")
async def import_markdown(body: ImportMarkdown):
    """暂存指定解析结果，只领取对应任务；索引验证完成后才标记成功。"""
    from rag_service.imports import prepare_markdown

    try:
        prepared = await asyncio.to_thread(
            prepare_markdown, body.path, "output", app.state.settings.asset_root
        )
    except (ValueError, OSError, KeyError) as exc:
        raise HTTPException(422, str(exc))
    repo = app.state.repo
    job_id = await repo.stage(*prepared)
    if body.retry_failed:
        await repo.retry(job_id)
    job = await repo.claim(job_id)
    if job:
        try:
            async with asyncio.timeout(240):
                await app.state.providers.index(job["chunks"])
            await repo.finish(job_id, claim_token=job["claim_token"])
        except BaseException as exc:
            await asyncio.shield(
                repo.finish(
                    job_id, error=type(exc).__name__, claim_token=job["claim_token"]
                )
            )
            if isinstance(exc, asyncio.CancelledError):
                raise
            if isinstance(exc, Exception):
                raise HTTPException(
                    503,
                    {"job_id": job_id, "status": "failed", "error": type(exc).__name__},
                ) from exc
            raise
    return {
        **await repo.job_status(job_id),
        "parents": len(prepared[0]),
        "chunks": len(prepared[1]),
        "assets": len(prepared[2]),
    }


class Search(BaseModel):
    """检索参数；review 仅用于已开启本地审核的实例。"""

    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=50)
    review: bool = False

    @field_validator("query")
    @classmethod
    def nonempty(cls, value):
        """拒绝纯空白查询。"""
        if not value.strip():
            raise ValueError("Query cannot be blank")
        return value.strip()


def review_allowed(review):
    """服务端未允许本地审核时，拒绝读取未发布内容的请求。"""
    if review and not app.state.settings.local_review:
        raise HTTPException(403, "Local review disabled")


@app.get("/health")
async def health():
    """检查 SQL 与 Milvus 可用性，依赖异常统一返回 503。"""
    try:
        async with asyncio.timeout(app.state.settings.request_timeout):
            await app.state.repo.health()
            exists = await app.state.providers.milvus.has_collection(
                app.state.providers.collection
            )
            if not exists:
                raise RuntimeError()
        return {"status": "ok"}
    except Exception:  # noqa: BLE001 - dependency boundary; cancellation propagates
        raise HTTPException(503, "Dependency unavailable")


@app.post("/search")
async def search(body: Search):
    """执行混合召回并设置整个请求截止时间；两路均失败时返回 503。"""
    review_allowed(body.review)
    try:
        async with asyncio.timeout(app.state.settings.request_timeout):
            return await retrieve(
                body.query,
                app.state.repo,
                app.state.providers,
                body.limit,
                body.review,
                app.state.settings.request_timeout,
            )
    except (RuntimeError, TimeoutError):
        raise HTTPException(503, "Retrieval unavailable")


@app.get("/questions/{question_id}")
async def question(question_id: str, review: bool = False):
    """按已知题目 ID 直接读取 SQL 父题，不进行向量检索。"""
    review_allowed(review)
    async with asyncio.timeout(app.state.settings.request_timeout):
        rows = await app.state.repo.hydrate([question_id], review=review)
    if question_id not in rows:
        raise HTTPException(404, "Question not found")
    return public_parent(rows[question_id], review)


@app.get("/assets/{asset_id}")
async def asset(asset_id: str, review: bool = False):
    """校验题目可见性后发送 PNG；不在请求中裁剪或生成 Base64。"""
    review_allowed(review)
    try:
        path = asset_path(app.state.settings.asset_root, asset_id)
    except ValueError:
        raise HTTPException(404, "Asset not found")
    async with asyncio.timeout(app.state.settings.request_timeout):
        if not await app.state.repo.asset(
            asset_id, review=review
        ) or not await asyncio.to_thread(path.is_file):
            raise HTTPException(404, "Asset not found")
    return FileResponse(path, media_type="image/png")


def main():
    """使用 Windows psycopg 兼容的 SelectorEventLoop 启动本机 HTTP 服务。"""
    import uvicorn

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(
            uvicorn.Server(
                uvicorn.Config(app, host="127.0.0.1", port=8000, loop="asyncio")
            ).serve()
        )


if __name__ == "__main__":
    main()
