from app.settings_service import _normalize_priority


def test_normalize_priority_preserves_order_and_disabled_source() -> None:
    priority = _normalize_priority(
        [
            {"name": "youtube", "enabled": False},
            {"name": "slskd", "enabled": True},
        ]
    )
    assert [item["name"] for item in priority][:2] == ["youtube", "slskd"]
    assert priority[0]["enabled"] is False
