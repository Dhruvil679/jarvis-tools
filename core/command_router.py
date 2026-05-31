import asyncio
from typing import Callable, Dict, Optional
from core.logger import get_logger

logger = get_logger(__name__)

class CommandRouter:
    """Routes parsed commands to tool handlers."""

    def __init__(self):
        self.handlers: Dict[str, Callable[..., asyncio.Future]] = {}

    def register(self, name: str, handler: Callable[..., asyncio.Future]):
        self.handlers[name] = handler

    async def route(self, text: str) -> Optional[str]:
        text = (text or "").lower()
        if not text:
            return None

        # simple keyword matching
        if "youtube" in text or "open youtube" in text:
            return await self._safe_call("youtube", text)
        if "google" in text or text.startswith("search") or "search" in text:
            return await self._safe_call("google", text)
        if "spotify" in text:
            return await self._safe_call("spotify", text)
        if "calculator" in text or "calculate" in text:
            return await self._safe_call("calculator", text)
        if "notepad" in text or "open notepad" in text:
            return await self._safe_call("notepad", text)
        if "system status" in text or "status" == text.strip():
            return await self._safe_call("system", text)

        # default: return None so the assistant can reply
        return None

    async def _safe_call(self, name: str, text: str) -> Optional[str]:
        handler = self.handlers.get(name)
        if not handler:
            logger.warning("No handler registered for %s", name)
            return None
        try:
            result = handler(text)
            if asyncio.iscoroutine(result):
                result = await result
            return result
        except Exception as e:
            logger.exception("Handler %s failed: %s", name, e)
            return None
