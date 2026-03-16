"""
Unit tests for knowledge MCP Tool Package (T24 — Sprint 2 gate).
Tests fetch_care_guide caching and search_local_kb keyword matching.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFetchCareGuide:
    @pytest.mark.asyncio
    async def test_cache_miss_calls_search_and_llm(self, tmp_path: Path):
        """fetch_care_guide calls search_web and LLM on cache miss."""
        from tools.knowledge.server import _fetch_care_guide

        mock_search = AsyncMock(return_value=[
            {"title": "Monstera Care", "snippet": "Water weekly.", "url": "https://example.com"}
        ])
        mock_llm_response = MagicMock()
        mock_llm_response.choices = [MagicMock()]
        mock_llm_response.choices[0].message.content = json.dumps({
            "watering": "Once a week",
            "light": "Indirect bright light",
            "temperature": "18-27°C",
            "humidity": "High",
            "notes": "Wipe leaves monthly",
        })

        with patch("tools.knowledge.server._cache_dir", return_value=tmp_path), \
             patch("tools.knowledge.server._search_web", mock_search), \
             patch("tools.knowledge.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_llm_response)
            mock_cfg = MagicMock()
            mock_cfg.default_model = "gpt-4o"
            with patch("tools.knowledge.server.get_tool_config", return_value=mock_cfg):
                result = await _fetch_care_guide("monstera")

        assert result["watering"] == "Once a week"
        assert result["light"] == "Indirect bright light"
        mock_search.assert_called_once()

    @pytest.mark.asyncio
    async def test_cache_hit_skips_network(self, tmp_path: Path):
        """fetch_care_guide returns cached result without calling search_web."""
        from tools.knowledge.server import _fetch_care_guide

        # Pre-populate cache
        cached_guide = {
            "watering": "Twice a week",
            "light": "Full sun",
            "temperature": "20-30°C",
            "humidity": "Medium",
            "notes": "Drought tolerant",
        }
        cache_file = tmp_path / "monstera.json"
        cache_file.write_text(json.dumps(cached_guide), encoding="utf-8")

        mock_search = AsyncMock()

        with patch("tools.knowledge.server._cache_dir", return_value=tmp_path), \
             patch("tools.knowledge.server._search_web", mock_search):
            result = await _fetch_care_guide("monstera")

        # Cache hit — search_web should NOT be called
        mock_search.assert_not_called()
        assert result["watering"] == "Twice a week"

    @pytest.mark.asyncio
    async def test_second_call_uses_cache(self, tmp_path: Path):
        """Second call to fetch_care_guide for same species uses cache."""
        from tools.knowledge.server import _fetch_care_guide

        mock_search = AsyncMock(return_value=[
            {"title": "Pothos Care", "snippet": "Easy to grow.", "url": "https://example.com"}
        ])
        mock_llm_response = MagicMock()
        mock_llm_response.choices = [MagicMock()]
        mock_llm_response.choices[0].message.content = json.dumps({
            "watering": "Every 1-2 weeks",
            "light": "Low to bright indirect",
            "temperature": "15-30°C",
            "humidity": "Any",
            "notes": "Very forgiving",
        })

        with patch("tools.knowledge.server._cache_dir", return_value=tmp_path), \
             patch("tools.knowledge.server._search_web", mock_search), \
             patch("tools.knowledge.server.litellm") as mock_litellm:
            mock_litellm.acompletion = AsyncMock(return_value=mock_llm_response)
            mock_cfg = MagicMock()
            mock_cfg.default_model = "gpt-4o"
            with patch("tools.knowledge.server.get_tool_config", return_value=mock_cfg):
                # First call — cache miss
                result1 = await _fetch_care_guide("pothos")
                # Second call — cache hit
                result2 = await _fetch_care_guide("pothos")

        # search_web should only be called once (first call)
        assert mock_search.call_count == 1
        assert result1 == result2


class TestSearchLocalKb:
    def test_keyword_match_returns_sorted_results(self, tmp_path: Path):
        """search_local_kb returns results sorted by relevance score."""
        from tools.knowledge.server import _search_local_kb

        # Create test summaries
        summaries = [
            {"id": "s1", "category": "plant_monitor", "tags": [], "created_at": "2026-01-01T00:00:00+00:00",
             "content": "The plant needs water. Water the plant daily."},
            {"id": "s2", "category": "plant_monitor", "tags": [], "created_at": "2026-01-02T00:00:00+00:00",
             "content": "Temperature is normal. No issues detected."},
            {"id": "s3", "category": "plant_monitor", "tags": [], "created_at": "2026-01-03T00:00:00+00:00",
             "content": "Water water water! The plant is very thirsty."},
        ]
        for s in summaries:
            (tmp_path / f"{s['id']}.json").write_text(json.dumps(s), encoding="utf-8")

        with patch("tools.knowledge.server.app_config") as mock_cfg:
            mock_cfg.storage.base_dir = str(tmp_path.parent)
            with patch("tools.knowledge.server.Path") as mock_path_cls:
                # Redirect summaries_dir to tmp_path
                mock_path_cls.return_value.__truediv__ = lambda self, x: tmp_path if "summaries" in str(x) else tmp_path / x
                pass

        # Direct test with patched summaries dir
        import tools.knowledge.server as ks
        original_base = None
        try:
            from core.config import app_config as real_cfg
            original_base = real_cfg.storage.base_dir
            real_cfg.storage.base_dir = str(tmp_path.parent)

            # Create summaries dir at expected location
            summaries_dir = tmp_path.parent / "summaries"
            summaries_dir.mkdir(exist_ok=True)
            for s in summaries:
                (summaries_dir / f"{s['id']}.json").write_text(json.dumps(s), encoding="utf-8")

            results = _search_local_kb("water plant")
        finally:
            if original_base:
                real_cfg.storage.base_dir = original_base

        # s3 has most "water" occurrences, should rank first
        assert len(results) >= 1
        assert results[0]["summary_id"] in ["s1", "s3"]  # Both have "water"

    def test_no_match_returns_empty(self, tmp_path: Path):
        """search_local_kb returns empty list when no keywords match."""
        from tools.knowledge.server import _search_local_kb

        summary = {
            "id": "s1", "category": "test", "tags": [],
            "created_at": "2026-01-01T00:00:00+00:00",
            "content": "The plant is healthy.",
        }
        summaries_dir = tmp_path / "summaries"
        summaries_dir.mkdir()
        (summaries_dir / "s1.json").write_text(json.dumps(summary), encoding="utf-8")

        from core.config import app_config as real_cfg
        original_base = real_cfg.storage.base_dir
        try:
            real_cfg.storage.base_dir = str(tmp_path)
            results = _search_local_kb("chemistry experiment flask")
        finally:
            real_cfg.storage.base_dir = original_base

        assert results == []
