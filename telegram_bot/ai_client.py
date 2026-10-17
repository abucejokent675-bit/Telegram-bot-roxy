from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import Settings
from .personality import PERSONALITY

logger = logging.getLogger(__name__)


class AIError(Exception):
    pass


class AIClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(timeout=settings.ai_timeout_seconds)

    @property
    def available(self) -> bool:
        return self.settings.ai_configured

    async def close(self) -> None:
        await self._client.aclose()

    async def chat(self, messages: list[dict[str, str]], max_tokens: int | None = None) -> str:
        if not self.available:
            raise AIError("AI is not configured (missing AI_API_KEY).")

        payload: dict[str, Any] = {
            "model": self.settings.ai_model,
            "messages": [{"role": "system", "content": PERSONALITY}] + messages,
            "max_tokens": max_tokens or self.settings.ai_max_tokens,
            "temperature": 0.4,
        }

        headers = {
            "Authorization": f"Bearer {self.settings.ai_api_key}",
            "Content-Type": "application/json",
        }

        try:
            response = await self._client.post(
                f"{self.settings.ai_base_url}/chat/completions",
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()
            content = data["choices"][0]["message"]["content"]
            return str(content).strip()
        except httpx.HTTPStatusError as error:
            logger.error("AI HTTP error: %s", error.response.status_code)
            raise AIError(f"AI provider returned status {error.response.status_code}") from error
        except Exception as error:
            logger.error("AI request failed: %s", type(error).__name__)
            raise AIError("Failed to contact the AI provider") from error
