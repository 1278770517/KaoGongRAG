"""领取持久化索引任务，验证 Milvus 写入后标记完成；队列为空即退出。"""

import asyncio

from psycopg_pool import AsyncConnectionPool

from .config import Settings
from .providers import Providers
from .repository import Repository


async def run_worker(settings, repo, providers):
    """处理待办任务；网络调用不占用 SQL 事务，完成后用 claim_token 确认归属。"""
    await providers.initialize()
    processed = 0
    while job := await repo.claim():
        try:
            async with asyncio.timeout(240):
                await providers.index(job["chunks"])
            await repo.finish(job["job_id"], claim_token=job["claim_token"])
            processed += 1
        except Exception as exc:
            await repo.finish(
                job["job_id"], error=type(exc).__name__, claim_token=job["claim_token"]
            )
            raise
    return processed


async def run():
    """创建独立 worker 的连接池与客户端，并确保退出时关闭。"""
    settings = Settings()
    async with AsyncConnectionPool(
        settings.conninfo, open=False, min_size=1, max_size=settings.concurrency
    ) as pool:
        repo = Repository(pool)
        await repo.initialize()
        providers = Providers(settings)
        try:
            print({"processed": await run_worker(settings, repo, providers)})
        finally:
            await providers.close()


def main():
    """独立进程入口，使用兼容 Windows PostgreSQL 的事件循环。"""
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(run())


if __name__ == "__main__":
    main()
