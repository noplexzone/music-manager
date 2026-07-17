from __future__ import annotations

import tomllib
from pathlib import Path


def test_setuptools_includes_web_assets_in_built_distributions() -> None:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))

    setuptools_config = data["tool"]["setuptools"]
    package_data = setuptools_config["package-data"]

    assert setuptools_config["include-package-data"] is True
    assert "app" in package_data
    assert "templates/*.html" in package_data["app"]
    assert "static/css/*.css" in package_data["app"]
