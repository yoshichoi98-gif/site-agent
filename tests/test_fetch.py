"""
Fetch layer tests. Hits real URLs (example.com). Requires network.
Run: pytest tests/test_fetch.py -v
"""
import asyncio
import os
import pytest
from src.fetch import fetch, _is_blocked, _cache_path


@pytest.mark.asyncio
async def test_fetch_example_com():
    result = await fetch("example.com")
    assert result.status_code == 200
    assert len(result.html) > 100
    assert not result.blocked
    assert result.fetched_with in ("httpx", "cache")


@pytest.mark.asyncio
async def test_fetch_creates_cache(tmp_path, monkeypatch):
    monkeypatch.setattr("src.fetch.CACHE_DIR", str(tmp_path))
    monkeypatch.setattr("src.config.CACHE_DIR", str(tmp_path))
    result = await fetch("example.com")
    cache_file = os.path.join(str(tmp_path), "example.com.html")
    assert os.path.exists(cache_file)


@pytest.mark.asyncio
async def test_fetch_uses_cache_on_second_call(tmp_path, monkeypatch):
    monkeypatch.setattr("src.fetch.CACHE_DIR", str(tmp_path))
    # Write fake cache
    cache_file = os.path.join(str(tmp_path), "example.com.html")
    with open(cache_file, "w") as f:
        f.write("<html>cached</html>")
    result = await fetch("example.com")
    assert result.fetched_with == "cache"
    assert "cached" in result.html


def test_is_blocked_by_status():
    assert _is_blocked(403, "<html>lots of content here" + "x" * 500 + "</html>")
    assert _is_blocked(429, "x" * 600)
    assert _is_blocked(503, "x" * 600)


def test_is_blocked_by_size():
    assert _is_blocked(200, "tiny")


def test_is_blocked_by_cloudflare_marker():
    html = "x" * 600 + "cloudflare ray id" + "y" * 200
    assert _is_blocked(200, html)


def test_not_blocked_normal_page():
    html = "<html><body>" + "content " * 100 + "</body></html>"
    assert not _is_blocked(200, html)
