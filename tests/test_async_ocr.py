import asyncio
import json

import pymupdf
import pytest

from pdf_ocr.client import OCRError
from pdf_ocr.converter import convert_pdf_async
from pdf_ocr.layout import parse_layout


@pytest.mark.asyncio
async def test_concurrency_failure_and_page_order(tmp_path):
    source = tmp_path / "test.pdf"
    with pymupdf.open() as doc:
        for _ in range(5):
            doc.new_page(width=100, height=100)
        doc.save(source)

    class Client:
        active = 0
        peak = 0
        calls = 0

        async def recognize(self, png):
            self.calls += 1
            number = self.calls
            self.active += 1
            self.peak = max(self.peak, self.active)
            await asyncio.sleep(0.03 if number == 1 else 0.01)
            self.active -= 1
            if number == 2:
                raise OCRError("failed")
            return parse_layout('{"blocks":[]}')

    client = Client()
    result = await convert_pdf_async(source, tmp_path / "out", client, concurrency=2)
    assert client.peak == 2
    assert [p["page"] for p in result["pages"]] == [1, 2, 3, 4, 5]
    assert result["status"] == "partial_failure"
    assert sum(p["status"] == "completed" for p in result["pages"]) == 4
    assert json.loads((tmp_path / "out/test/manifest.json").read_text()) == result


@pytest.mark.asyncio
async def test_invalid_concurrency(tmp_path):
    with pytest.raises(ValueError):
        await convert_pdf_async(tmp_path / "absent.pdf", tmp_path, None, concurrency=0)


@pytest.mark.asyncio
async def test_async_sdk_retry():
    import httpx2

    from pdf_ocr.client import AsyncOCRClient
    from pdf_ocr.config import Settings

    requests = []

    async def respond(request):
        requests.append(request)
        if len(requests) == 1:
            return httpx2.Response(503)
        return httpx2.Response(
            200,
            json={
                "id": "test",
                "object": "chat.completion",
                "created": 0,
                "model": "test",
                "choices": [
                    {
                        "index": 0,
                        "finish_reason": "stop",
                        "message": {"role": "assistant", "content": '{"blocks":[]}'},
                    }
                ],
            },
        )

    async def sleep(_):
        await asyncio.sleep(0)

    async with httpx2.AsyncClient(transport=httpx2.MockTransport(respond)) as http:
        client = AsyncOCRClient(
            Settings(_env_file=None, ocr_api_key="test", ocr_retries=1),
            http=http,
            sleep=sleep,
        )
        assert (await client.recognize(b"png")).blocks == []
    assert len(requests) == 2
