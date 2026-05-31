"""Async-capable Ollama HTTP client with retry, timeout, and streaming helpers.

Exposes `generate` (async) and `generate_stream` (async generator). Uses the
blocking `requests` library under the hood but runs HTTP calls in background
threads so callers do not block the event loop.
"""

import asyncio
import logging
import time
import threading
import json
from typing import Optional, AsyncGenerator

from .logger import get_logger

logger = get_logger(__name__)


class OllamaClient:
    """Ollama client with retries and optional streaming support."""

    def __init__(self, base_url: str = "http://localhost:11434", model: str = "qwen2.5:7b", timeout: int = 180):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = int(timeout)

    async def generate(self, prompt: str, max_tokens: int = 512, retries: int = 2, backoff: float = 0.8) -> Optional[str]:
        """Generate text from the model. Retries on transient failures.

        Adds logging for prompt length and elapsed time to help diagnose timeouts.
        """
        loop = asyncio.get_running_loop()
        for attempt in range(retries + 1):
            start = time.time()
            try:
                res = await loop.run_in_executor(None, self._generate_sync, prompt, max_tokens, self.timeout)
                elapsed = time.time() - start
                logger.info("Ollama generate: prompt_len=%d elapsed=%.2fs timeout=%s attempt=%d", len(prompt or ""), elapsed, self.timeout, attempt + 1)
                return res
            except Exception as e:
                elapsed = time.time() - start
                logger.warning("Ollama generate attempt %s failed (prompt_len=%d elapsed=%.2fs timeout=%s): %s", attempt + 1, len(prompt or ""), elapsed, self.timeout, e)
                if attempt < retries:
                    await asyncio.sleep(backoff * (2 ** attempt))
                else:
                    logger.error("Ollama generate failed after %s attempts (last elapsed=%.2fs timeout=%s)", retries + 1, elapsed, self.timeout)
                    return None

    def _generate_sync(self, prompt: str, max_tokens: int, timeout: int):

        try:
            import requests
            import json

            url = f"{self.base_url}/api/generate"

            payload = {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_predict": max_tokens
                }
            }

            resp = requests.post(
                url,
                json=payload,
                timeout=timeout
            )

            resp.raise_for_status()

            final_response = ""

            for line in resp.text.splitlines():

                if not line.strip():
                    continue

                try:
                    chunk = json.loads(line)
                    final_response += chunk.get("response", "")

                except Exception as chunk_error:
                    logger.warning(f"Malformed Ollama chunk: {chunk_error}")
                    continue

            return final_response.strip()

        except Exception as e:
            logger.error(f"Ollama request failed: {e}")
            raise
        
    async def generate_stream(self, prompt: str, max_tokens: int = 512) -> AsyncGenerator[str, None]:
        """Async generator yielding streaming response chunks from Ollama.

        This starts a background thread that performs a streaming POST call and
        forwards lines to an asyncio.Queue which this generator yields from.
        """
        try:
            import requests
        except Exception as exc:
            logger.error("generate_stream requires requests: %s", exc)
            return

        q: "asyncio.Queue[Optional[str]]" = asyncio.Queue()

        loop = asyncio.get_event_loop()

        def worker():
            url = f"{self.base_url}/api/generate"
            payload = {"model": self.model, "prompt": prompt, "max_tokens": max_tokens}
            try:
                with requests.post(url, json=payload, stream=True, timeout=self.timeout) as r:
                    r.raise_for_status()
                    for chunk in r.iter_lines(decode_unicode=True):
                        if chunk:
                            asyncio.run_coroutine_threadsafe(q.put(chunk), loop)
                asyncio.run_coroutine_threadsafe(q.put(None), loop)
            except Exception as e:
                logger.exception("Streaming call failed: %s", e)
                asyncio.run_coroutine_threadsafe(q.put(None), loop)

        t = threading.Thread(target=worker, daemon=True)
        t.start()

        while True:
            chunk = await q.get()
            if chunk is None:
                break
            yield chunk


__all__ = ["OllamaClient"]
