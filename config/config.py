from __future__ import annotations

from pathlib import Path
import os

class Config:
    """Central configuration for JARVIS."""

    def __init__(self):
        self.BASE_DIR = Path(__file__).resolve().parent.parent
        self.AGENTS_ROOT = os.getenv("JARVIS_AGENTS_ROOT", str(self.BASE_DIR / "agents"))
        self.MEMORY_ROOT = os.getenv("JARVIS_MEMORY_ROOT", str(self.BASE_DIR / "memory"))
        self.AGENT_SKILL_REGISTRY = os.getenv(
            "JARVIS_AGENT_SKILL_REGISTRY",
            str(Path(self.MEMORY_ROOT) / "agent_skill_registry.db"),
        )
        self.ROUTE_CONFIG = os.getenv("JARVIS_ROUTE_CONFIG", str(self.BASE_DIR / "config" / "agent_routes.json"))
        self.API_HOST = os.getenv("JARVIS_API_HOST", "127.0.0.1")
        self.API_PORT = int(os.getenv("JARVIS_API_PORT", "8000"))
        self.DASHBOARD_DIR = os.getenv("JARVIS_DASHBOARD_DIR", str(self.BASE_DIR / "dashboard"))
        self.OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
        self.MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        # Ollama timeout (seconds) for large prompts / autonomous planning
        self.OLLAMA_TIMEOUT = int(os.getenv("OLLAMA_TIMEOUT", "180"))
        self.AGENT_TIMEOUT_SECONDS = int(os.getenv("JARVIS_AGENT_TIMEOUT", "60"))
        self.VOICE = os.getenv("JARVIS_VOICE", "alloy")
        self.USE_PIPER = os.getenv("JARVIS_USE_PIPER", "false").lower() in ("1", "true", "yes")
        self.PIPER_CMD = os.getenv("PIPER_CMD", "piper")
        self.WAKE_WORD = os.getenv("JARVIS_WAKE", "jarvis")
        self.DEBUG = os.getenv("JARVIS_DEBUG", "false").lower() in ("1", "true", "yes")

config = Config()
