"""
Unit tests for notify MCP Tool Package (T24 — Sprint 2 gate).
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class TestFeishuSend:
    @pytest.mark.asyncio
    async def test_feishu_send_success(self):
        """feishu_send returns success=True when HTTP 200."""
        from tools.notify.server import _feishu_send

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cfg = MagicMock()
        mock_cfg.feishu_default_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

        with patch("tools.notify.server.get_tool_config", return_value=mock_cfg), \
             patch("tools.notify.server.httpx.AsyncClient", return_value=mock_client):
            result = await _feishu_send("Hello from ClawWithTail!")

        assert result["success"] is True
        assert result["status_code"] == 200

    @pytest.mark.asyncio
    async def test_feishu_send_failure_500(self):
        """feishu_send returns success=False when HTTP 500."""
        from tools.notify.server import _feishu_send

        mock_response = MagicMock()
        mock_response.status_code = 500

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cfg = MagicMock()
        mock_cfg.feishu_default_webhook = "https://open.feishu.cn/open-apis/bot/v2/hook/test"

        with patch("tools.notify.server.get_tool_config", return_value=mock_cfg), \
             patch("tools.notify.server.httpx.AsyncClient", return_value=mock_client):
            result = await _feishu_send("Test message")

        assert result["success"] is False
        assert result["status_code"] == 500

    @pytest.mark.asyncio
    async def test_feishu_send_no_webhook_raises(self):
        """feishu_send raises ExternalAPIError when no webhook URL configured."""
        from tools.notify.server import _feishu_send
        from tools.shared.errors import ExternalAPIError

        mock_cfg = MagicMock()
        mock_cfg.feishu_default_webhook = None

        with patch("tools.notify.server.get_tool_config", return_value=mock_cfg):
            with pytest.raises(ExternalAPIError, match="No Feishu webhook URL"):
                await _feishu_send("Test message")

    @pytest.mark.asyncio
    async def test_feishu_send_uses_explicit_webhook(self):
        """feishu_send uses the explicitly provided webhook_url."""
        from tools.notify.server import _feishu_send

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cfg = MagicMock()
        mock_cfg.feishu_default_webhook = None  # No default

        explicit_url = "https://custom.webhook.url/test"
        with patch("tools.notify.server.get_tool_config", return_value=mock_cfg), \
             patch("tools.notify.server.httpx.AsyncClient", return_value=mock_client):
            result = await _feishu_send("Test", webhook_url=explicit_url)

        assert result["success"] is True
        # Verify the explicit URL was used
        mock_client.post.assert_called_once_with(explicit_url, json={
            "msg_type": "text",
            "content": {"text": "Test"},
        })

    @pytest.mark.asyncio
    async def test_feishu_send_report_formats_message(self):
        """feishu_send_report sends a formatted message with title, summary, and path."""
        from tools.notify.server import _feishu_send_report

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        mock_cfg = MagicMock()
        mock_cfg.feishu_default_webhook = "https://test.webhook.url"

        with patch("tools.notify.server.get_tool_config", return_value=mock_cfg), \
             patch("tools.notify.server.httpx.AsyncClient", return_value=mock_client):
            result = await _feishu_send_report(
                title="Plant Health Report",
                summary="The plant looks healthy.",
                report_path="/home/user/.clawtail/data/reports/report.md",
            )

        assert result["success"] is True
        # Verify the message contains all three parts
        call_kwargs = mock_client.post.call_args[1]["json"]
        message_text = call_kwargs["content"]["text"]
        assert "Plant Health Report" in message_text
        assert "The plant looks healthy." in message_text
        assert "report.md" in message_text
