"""Opt-in real PostgreSQL transaction tests in a disposable isolated schema."""

import asyncio
import os
import uuid

import pytest
from psycopg import sql
from psycopg_pool import AsyncConnectionPool

from rag_service.config import Settings
from rag_service.repository import Repository


@pytest.mark.skipif(
    os.getenv("RAG_TEST_POSTGRES") != "1", reason="requires local PostgreSQL"
)
def test_jobs_fence_versions_and_retry():
    async def run():
        settings = Settings()
        schema = "rag_test_" + uuid.uuid4().hex
        async with AsyncConnectionPool(
            settings.conninfo, open=False, min_size=1, max_size=1
        ) as pool:
            async with pool.connection() as conn:
                await conn.execute(
                    sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema))
                )
                await conn.execute(
                    sql.SQL("SET search_path TO {}").format(sql.Identifier(schema))
                )
            try:
                repo = Repository(pool)
                await repo.initialize()
                p = {
                    "question_id": "one",
                    "question_version": 1,
                    "status": "unreviewed",
                }
                job = await repo.stage([p], [{"chunk_id": "old"}], [])
                assert await repo.stage([p], [{"chunk_id": "old"}], []) == job
                claimed = await repo.claim()
                assert claimed["job_id"] == job
                await repo.finish(job, claim_token="wrong")
                assert not await repo.hydrate(["one"], review=True)
                newer = dict(p, question_version=2)
                job2 = await repo.stage([newer], [{"chunk_id": "new"}], [])
                await repo.finish(job, claim_token=claimed["claim_token"])
                assert not await repo.hydrate(["one"], review=True)
                claimed2 = await repo.claim()
                assert claimed2["job_id"] == job2
                await repo.finish(
                    job2, error="transient", claim_token=claimed2["claim_token"]
                )
                await repo.retry(job2)
                retried = await repo.claim()
                assert retried["claim_token"] != claimed2["claim_token"]
                await repo.finish(job2, claim_token=retried["claim_token"])
                assert (await repo.hydrate(["one"], review=True))["one"][
                    "question_version"
                ] == 2
                assert not await repo.hydrate(["one"])
            finally:
                async with pool.connection() as conn:
                    await conn.execute(
                        sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema))
                    )

    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(run())
