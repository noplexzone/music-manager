from __future__ import annotations

import tomllib
from pathlib import Path


def test_pytest_asyncio_loop_scope_is_explicit() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    pytest_options = data["tool"]["pytest"]["ini_options"]

    assert pytest_options["asyncio_default_fixture_loop_scope"] == "function"
    assert pytest_options["asyncio_default_test_loop_scope"] == "function"
