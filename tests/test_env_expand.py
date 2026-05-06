import os

from octo_satellite.env_expand import expand_env


def test_expand_simple(monkeypatch):
    monkeypatch.setenv("MY_SECRET", "hunter2")
    assert expand_env("${MY_SECRET}") == "hunter2"


def test_expand_embedded(monkeypatch):
    monkeypatch.setenv("HOST", "example.com")
    assert expand_env("https://${HOST}/api") == "https://example.com/api"


def test_expand_multiple(monkeypatch):
    monkeypatch.setenv("A", "hello")
    monkeypatch.setenv("B", "world")
    assert expand_env("${A} ${B}") == "hello world"


def test_expand_missing_not_strict():
    result = expand_env("${DOES_NOT_EXIST_XYZ}")
    assert result == "${DOES_NOT_EXIST_XYZ}"


def test_expand_missing_strict():
    import pytest
    with pytest.raises(ValueError, match="not set"):
        expand_env("${DOES_NOT_EXIST_XYZ}", strict=True)


def test_expand_no_vars():
    assert expand_env("plain string") == "plain string"
