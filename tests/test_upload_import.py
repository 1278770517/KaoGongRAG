import pytest

from rag_service.imports import contained, markdown_blocks


@pytest.mark.asyncio
async def test_upload_when_api_loaded_as_script(monkeypatch):
    """PyCharm 直接执行 api.py 时没有包上下文，接口仍应能加载导入模块。"""
    import runpy
    from pathlib import Path
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    import rag_service.imports as module

    fake = AsyncMock(return_value={"manifest": {"status": "completed"}})
    monkeypatch.setattr(module, "upload_pdf", fake)
    namespace = runpy.run_path(str(Path("rag_service/api.py")))
    result = await namespace["import_pdf"](SimpleNamespace(headers={}), end_page=10)
    assert result["manifest"]["status"] == "completed"
    fake.assert_awaited_once()


def test_containment(tmp_path):
    with pytest.raises(ValueError):
        contained(tmp_path, tmp_path.parent / "outside.md")


def test_markdown_is_authority():
    blocks = markdown_blocks(
        "1.（单选）edited\n\n![x](data:image/png;base64,AA==)",
        [
            {"type": "text", "markdown": "obsolete"},
            {"type": "image", "bbox": [0, 0, 10, 10]},
        ],
    )
    assert "edited" in blocks[0]["markdown"]
    assert blocks[1]["type"] == "image"


def test_missing_image_rejected():
    with pytest.raises(ValueError):
        markdown_blocks("text", [{"type": "image", "bbox": [0, 0, 10, 10]}])


def test_page_furniture_is_separate_block():
    blocks = markdown_blocks("解析正文\n\n第 2 页 共 210 页\n\n更多资料添加：abc", [])
    assert len(blocks) == 3


@pytest.mark.asyncio
async def test_upload_raw_and_multipart(monkeypatch):
    import httpx

    import rag_service.imports as module
    from rag_service.api import app

    async def fake_upload(request, root, end, gate):
        content = b"".join([part async for part in request.stream()])
        assert content == b"%PDF-test"
        assert end == 10
        return {"manifest": {"status": "completed"}}

    monkeypatch.setattr(module, "upload_pdf", fake_upload)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        assert (
            await client.post("/imports/pdf", content=b"%PDF-test")
        ).status_code == 200
        response = await client.post(
            "/imports/pdf", files={"file": ("a.pdf", b"%PDF-test", "application/pdf")}
        )
        assert response.status_code == 200


def test_prepare_rejects_partial_manifest(tmp_path):
    import json

    from rag_service.imports import prepare_markdown

    source = tmp_path / "doc"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps({"status": "partial_failure", "pages": []})
    )
    with pytest.raises(ValueError, match="Incomplete"):
        prepare_markdown(source, tmp_path, tmp_path / "assets")
