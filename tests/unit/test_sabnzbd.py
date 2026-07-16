from __future__ import annotations

from pytest_httpx import HTTPXMock

from app.sources.sabnzbd import SabnzbdAdapter


class TestSabnzbdStatus:
    async def test_status_returns_capability_state(self, httpx_mock: HTTPXMock) -> None:
        httpx_mock.add_response(
            url="http://sab.local/api?apikey=key&output=json&mode=queue&search=SAB123",
            json={"queue": {"slots": [{"nzo_id": "SAB123", "status": "Downloading"}]}},
        )

        adapter = SabnzbdAdapter("http://sab.local", "key")
        state = await adapter.status("SAB123")

        assert state.available is True
        assert state.reason == "Downloading"
