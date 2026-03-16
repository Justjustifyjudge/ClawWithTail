"""
core.agent.llm_engine — LiteLLM wrapper with retry and vision support.

Responsibilities:
  - Wrap litellm.acompletion with exponential backoff retry (max 3, 429 only)
  - Provide complete_vision() for image+text calls
  - Expose model config from AppConfig.llm
"""
from __future__ import annotations

import asyncio
import base64
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Maximum retries on rate-limit (429) errors
_MAX_RETRIES = 3


class LLMEngine:
    """
    Thin wrapper around LiteLLM that adds:
      - Exponential backoff retry on HTTP 429 (rate limit)
      - Vision (image+text) convenience method
      - Model selection from AppConfig
    """

    def __init__(self) -> None:
        from core.config import app_config
        self._cfg = app_config.llm
        self._default_model = self._cfg.default_model
        self._vision_model = self._cfg.vision_model
        self._fallback_model = self._cfg.fallback_model
        # Support OpenAI-compatible base_url (e.g. DeepSeek, Moonshot, local Ollama)
        self._base_url: str | None = self._cfg.base_url or None

    async def complete(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        model: str | None = None,
    ):
        """
        Call LiteLLM completion with retry on 429.

        Args:
            messages: OpenAI-format messages list.
            tools: Optional list of tool schemas (OpenAI function calling format).
            model: Override model string. Defaults to config.default_model.

        Returns:
            Raw LiteLLM response object.

        Raises:
            Exception: After max retries exhausted, re-raises the last error.
        """
        import litellm

        target_model = model or self._default_model
        kwargs: dict = {"model": target_model, "messages": messages}
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        if self._base_url:
            kwargs["base_url"] = self._base_url

        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES + 1):
            try:
                response = await litellm.acompletion(**kwargs)
                return response
            except Exception as exc:
                exc_str = str(exc).lower()
                is_rate_limit = (
                    "429" in exc_str
                    or "rate limit" in exc_str
                    or "ratelimit" in exc_str
                    or "too many requests" in exc_str
                )
                if is_rate_limit and attempt < _MAX_RETRIES:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.warning(
                        "LLMEngine: rate limit hit (attempt %d/%d), retrying in %ds",
                        attempt + 1, _MAX_RETRIES, wait,
                    )
                    await asyncio.sleep(wait)
                    last_exc = exc
                    continue
                # Non-rate-limit error or max retries exhausted
                raise

        # Should not reach here, but satisfy type checker
        raise last_exc  # type: ignore[misc]

    async def complete_vision(self, frame_path: str, prompt: str) -> str:
        """
        Send an image + text prompt to the vision model.

        The image is base64-encoded for the API call but NEVER stored in context
        or returned as base64 — only the text response is returned.

        Args:
            frame_path: Absolute path to a JPEG/PNG image file.
            prompt: Text prompt to accompany the image.

        Returns:
            LLM text response string.
        """
        import litellm

        image_bytes = Path(frame_path).read_bytes()
        b64 = base64.b64encode(image_bytes).decode("utf-8")

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
                    },
                    {"type": "text", "text": prompt},
                ],
            }
        ]

        response = await self.complete(messages, model=self._vision_model)
        return response.choices[0].message.content or ""


# Global singleton — lazy-initialized
_engine: LLMEngine | None = None


def get_llm_engine() -> LLMEngine:
    """Return the global LLMEngine singleton."""
    global _engine
    if _engine is None:
        _engine = LLMEngine()
    return _engine
