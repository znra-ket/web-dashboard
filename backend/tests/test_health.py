import unittest

from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app


class HealthEndpointTests(unittest.IsolatedAsyncioTestCase):
    async def test_health_endpoint_returns_ok(self) -> None:
        app = create_app(
            Settings(
                environment="test",
                database_url="sqlite+aiosqlite:///:memory:",
            )
        )

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/health")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "app_name": "web-xray-dashboard",
                "environment": "test",
            },
        )
