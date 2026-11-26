import httpx
import pytest

from rag_service.api import app


@pytest.mark.asyncio
async def test_frontend_json_preflight():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        response = await client.options(
            "/search",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.asyncio
async def test_unknown_origin_not_allowed():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        response = await client.options(
            "/search",
            headers={
                "Origin": "https://unknown.example",
                "Access-Control-Request-Method": "POST",
            },
        )
    assert "access-control-allow-origin" not in response.headers


@pytest.mark.asyncio
async def test_validation_error_has_cors_header():
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://api"
    ) as client:
        response = await client.post(
            "/search", json={}, headers={"Origin": "http://127.0.0.1:3000"}
        )
    assert response.status_code == 422
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
