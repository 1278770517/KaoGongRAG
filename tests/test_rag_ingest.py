import asyncio
import threading

import pytest

from rag_ingest import parse_pages, validate_vector


@pytest.mark.asyncio
async def test_ingest_cancellation_closes_clients(monkeypatch, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import rag_ingest

    client = SimpleNamespace(
        close=AsyncMock(), has_collection=AsyncMock(return_value=False)
    )
    api = AsyncMock()
    api.__aenter__.return_value = api
    monkeypatch.setattr(rag_ingest, "_prepare", lambda _: ([], [], tmp_path))
    monkeypatch.setattr(rag_ingest, "AsyncMilvusClient", lambda **_: client)
    monkeypatch.setattr(rag_ingest, "AsyncOpenAI", lambda **_: api)
    monkeypatch.setattr(
        rag_ingest,
        "Settings",
        lambda: SimpleNamespace(
            ocr_api_key=SimpleNamespace(get_secret_value=lambda: "test"),
            ocr_base_url="https://example.com",
        ),
    )
    started = asyncio.Event()

    async def index(*args):
        started.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(rag_ingest, "_index", index)
    task = asyncio.create_task(rag_ingest.ingest(tmp_path, write=True))
    await asyncio.wait_for(started.wait(), 2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    client.close.assert_awaited_once()
    api.__aexit__.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_prepare_does_not_block_loop(monkeypatch, tmp_path):
    import rag_ingest

    entered = threading.Event()
    release = threading.Event()

    def prepare(source):
        entered.set()
        assert release.wait(2)
        return [], [], tmp_path

    monkeypatch.setattr(rag_ingest, "_prepare", prepare, raising=False)
    task = asyncio.create_task(rag_ingest.ingest(tmp_path))
    try:
        for _ in range(100):
            if entered.is_set():
                break
            await asyncio.sleep(0.01)
        assert entered.is_set()
        assert not task.done()
    finally:
        release.set()
    assert (await task)["chunks"] == 0


def test_cross_page_and_quarantine():
    pages = [
        (
            1,
            [
                {
                    "type": "text",
                    "markdown": "1.（单选）不是哪项？\nA. 甲 B. 乙\n【答案】B。【解析】依据",
                }
            ],
        ),
        (
            2,
            [
                {
                    "type": "text",
                    "markdown": "续文。\n2.（单选）末题\nA. 丙 B. 丁\n【答案】A。【解析】说明。",
                }
            ],
        ),
    ]
    parents, chunks = parse_pages(pages, "doc")
    assert parents[0]["source_pages"] == [1, 2]
    assert "续文" in parents[0]["raw_text"]
    assert parents[-1]["status"] == "needs_review"
    question = next(c for c in chunks if c["view_type"] == "question")
    assert "不是" in question["retrieval_text"]
    assert "【答案】" not in question["retrieval_text"]


@pytest.mark.parametrize("v", [[0, 0], [float("nan"), 1], [1]])
def test_reject_invalid_vector(v):
    with pytest.raises(ValueError):
        validate_vector(v, 2)


def test_sparse_validation_rejects_empty_or_wrong_parent():
    import rag_ingest

    for hits in [[], [{"entity": {"question_id": "wrong"}}]]:
        with pytest.raises(ValueError):
            rag_ingest.validate_sparse(hits, "expected")
