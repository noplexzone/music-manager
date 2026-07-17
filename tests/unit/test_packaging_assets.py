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


def test_custom_json_forms_are_not_double_submitted() -> None:
    templates = Path("app/templates")
    base = (templates / "base.html").read_text()
    setup = (templates / "setup.html").read_text()
    settings = (templates / "settings.html").read_text()

    assert 'form.dataset.customSubmit === "true"' in base
    assert 'id="setup-form"' in setup and 'data-custom-submit="true"' in setup
    assert 'id="settings-form"' in settings and 'data-custom-submit="true"' in settings
    assert 'headers: {"Content-Type": "application/json"' in settings
    assert '"tidal_config_path","tidal_session_path","tidal_quality"' in setup
