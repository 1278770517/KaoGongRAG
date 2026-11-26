"""PostgreSQL 父题、资源关联和索引任务存储；短事务与租约隔离任务。"""

import hashlib
import json
import uuid

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

DDL = """
CREATE TABLE IF NOT EXISTS rag_questions (
 question_id text PRIMARY KEY, question_version bigint NOT NULL,
 status text NOT NULL, indexed boolean NOT NULL DEFAULT false, payload jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS rag_assets (
 asset_id text NOT NULL, question_id text NOT NULL REFERENCES rag_questions,
 page integer NOT NULL, bbox jsonb NOT NULL, PRIMARY KEY(asset_id,question_id,page));
CREATE TABLE IF NOT EXISTS rag_jobs (
 job_id text PRIMARY KEY, question_ids jsonb NOT NULL, chunks jsonb NOT NULL,
 status text NOT NULL DEFAULT 'pending', lease_until timestamptz, error text,
 attempts integer NOT NULL DEFAULT 0, claim_token text);
ALTER TABLE rag_jobs ADD COLUMN IF NOT EXISTS claim_token text;
ALTER TABLE rag_questions ADD COLUMN IF NOT EXISTS index_job text;
ALTER TABLE rag_questions ALTER COLUMN question_version TYPE bigint;
"""


class Repository:
    """封装 SQL 操作；不在事务内调用 OCR、embedding 或 Milvus。"""

    def __init__(self, pool):
        """接收共享异步连接池，方法内部按需借用连接。"""
        self.pool = pool

    async def initialize(self):
        """创建本服务的表及兼容字段；不修改其他业务表。"""
        async with self.pool.connection() as conn:
            await conn.execute(DDL)

    async def health(self):
        """执行轻量 SQL，检测连接池和数据库连接。"""
        async with self.pool.connection() as conn:
            await conn.execute("SELECT 1")
        return True

    async def stage(self, parents, chunks, assets):
        """用整批内容哈希生成任务 ID；相同任务复用，父题与资源在同一事务暂存。"""
        job_id = hashlib.sha256(
            json.dumps(chunks, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        async with self.pool.connection() as conn, conn.transaction():
            # 同批内容使用同一事务锁，避免并发请求同时创建同一任务。
            await conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (job_id,)
            )
            cursor = await conn.execute(
                "SELECT status FROM rag_jobs WHERE job_id=%s", (job_id,)
            )
            if await cursor.fetchone():
                return job_id
            for parent in parents:
                await conn.execute(
                    "INSERT INTO rag_questions(question_id,question_version,status,indexed,payload) VALUES (%s,%s,%s,false,%s) ON CONFLICT(question_id) DO UPDATE SET question_version=EXCLUDED.question_version,status=EXCLUDED.status,indexed=false,payload=EXCLUDED.payload",
                    (
                        parent["question_id"],
                        parent["question_version"],
                        parent["status"],
                        Jsonb(parent),
                    ),
                )
            await conn.execute(
                "DELETE FROM rag_assets WHERE question_id=ANY(%s)",
                ([p["question_id"] for p in parents],),
            )
            for asset in assets:
                await conn.execute(
                    "INSERT INTO rag_assets VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (
                        asset["asset_id"],
                        asset["question_id"],
                        asset["page"],
                        Jsonb(asset["bbox"]),
                    ),
                )
            await conn.execute(
                "UPDATE rag_questions SET index_job=%s WHERE question_id=ANY(%s)",
                (job_id, [p["question_id"] for p in parents]),
            )
            await conn.execute(
                "INSERT INTO rag_jobs(job_id,question_ids,chunks) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (job_id, Jsonb([p["question_id"] for p in parents]), Jsonb(chunks)),
            )
        return job_id

    async def claim(self, job_id=None):
        """通过 SKIP LOCKED 领取任务，支持指定 job_id；过期租约可重新领取。"""
        async with self.pool.connection() as conn, conn.transaction():
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "UPDATE rag_jobs SET claim_token=%s, status='running', attempts=attempts+1, lease_until=now()+interval '5 minutes' WHERE job_id=(SELECT job_id FROM rag_jobs WHERE (%s::text IS NULL OR job_id=%s) AND (status='pending' OR (status='running' AND lease_until<now())) ORDER BY job_id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING job_id,chunks,claim_token",
                (str(uuid.uuid4()), job_id, job_id),
            )
            return await cursor.fetchone()

    async def job_status(self, job_id):
        """读取任务真实状态，供重复请求或失败排查使用。"""
        async with self.pool.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT job_id,status,error FROM rag_jobs WHERE job_id=%s", (job_id,)
            )
            return await cursor.fetchone()

    async def finish(self, job_id, error=None, claim_token=None):
        """只有当前领取令牌能结束任务；只有仍归属此任务的父题可标记 indexed。"""
        async with self.pool.connection() as conn, conn.transaction():
            cursor = await conn.execute(
                "UPDATE rag_jobs SET status=%s,error=%s,lease_until=NULL WHERE job_id=%s AND claim_token=%s AND status='running' RETURNING question_ids",
                (
                    "failed" if error else "completed",
                    str(error)[:2000] if error else None,
                    job_id,
                    claim_token,
                ),
            )
            row = await cursor.fetchone()
            if row and not error:
                await conn.execute(
                    "UPDATE rag_questions SET indexed=true WHERE question_id = ANY(%s) AND index_job=%s",
                    (row[0], job_id),
                )

    async def retry(self, job_id):
        """显式将失败任务恢复为 pending，避免请求自动无限重试。"""
        async with self.pool.connection() as conn:
            await conn.execute(
                "UPDATE rag_jobs SET status='pending',error=NULL WHERE job_id=%s AND status='failed'",
                (job_id,),
            )

    async def hydrate(self, ids, review=False):
        """一次批量读取已索引父题；默认仅 published，审核模式放宽状态过滤。"""
        async with self.pool.connection() as conn:
            cursor = await conn.execute(
                "SELECT payload FROM rag_questions WHERE question_id=ANY(%s) AND indexed AND (%s OR status='published')",
                (list(ids), review),
            )
            return {row[0]["question_id"]: row[0] for row in await cursor.fetchall()}

    async def asset(self, asset_id, review=False):
        """按资源关联的父题检查可见性，防止绕过题目过滤直接取图。"""
        async with self.pool.connection() as conn:
            cursor = conn.cursor(row_factory=dict_row)
            await cursor.execute(
                "SELECT a.asset_id,a.page,a.bbox FROM rag_assets a JOIN rag_questions q USING(question_id) WHERE asset_id=%s AND q.indexed AND (%s OR q.status='published') LIMIT 1",
                (asset_id, review),
            )
            return await cursor.fetchone()
