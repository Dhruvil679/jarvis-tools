"""SkillEngine: dynamic skill discovery and production-ready loader."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from .logger import get_logger


logger = get_logger(__name__)


class Skill:
    """Represents a skill directory containing metadata and text files."""

    STANDARD_FILES = ("SKILL.md", "CLAUDE.md", "prompt.md", "README.md", "system_prompt.md")

    def __init__(self, path: str):
        self.path = path
        self.name = os.path.basename(path)
        self.metadata: Dict[str, Any] = {}
        self.files: Dict[str, str] = {}
        self._mtimes: Dict[str, float] = {}
        self._loaded_at = 0.0
        self.load(force=True)

    def _read_file(self, p: str) -> str:
        try:
            with open(p, "r", encoding="utf-8") as f:
                return f.read()
        except Exception:
            return ""

    def load(self, force: bool = False) -> None:
        now = time.time()
        meta_path = os.path.join(self.path, "metadata.json")
        try:
            if force or (os.path.exists(meta_path) and os.path.getmtime(meta_path) != self._mtimes.get("metadata", 0)):
                self.metadata = json.loads(self._read_file(meta_path)) if os.path.exists(meta_path) else {}
                self._mtimes["metadata"] = os.path.getmtime(meta_path) if os.path.exists(meta_path) else 0
        except Exception:
            logger.debug("Failed to load metadata for %s", self.name)

        for fname in self.STANDARD_FILES:
            p = os.path.join(self.path, fname)
            try:
                if os.path.exists(p):
                    mtime = os.path.getmtime(p)
                    if force or (self._mtimes.get(fname) != mtime):
                        self.files[fname] = self._read_file(p)
                        self._mtimes[fname] = mtime
                elif fname in self.files:
                    del self.files[fname]
                    self._mtimes.pop(fname, None)
            except Exception:
                logger.debug("Failed to load file %s for skill %s", fname, self.name)

        self._loaded_at = now

    @property
    def keywords(self) -> List[str]:
        kws = self.metadata.get("keywords", []) or []
        return [str(k).lower() for k in kws if k]

    @property
    def priority(self) -> int:
        try:
            return int(self.metadata.get("priority", 5))
        except Exception:
            return 5

    def get_preferred_content(self) -> Optional[str]:
        for fname in ("SKILL.md", "CLAUDE.md", "prompt.md", "README.md"):
            txt = self.files.get(fname, "")
            if txt and txt.strip():
                return txt
        return None

    def to_metadata(self) -> Dict[str, Any]:
        return {"name": self.name, **(self.metadata or {})}


class SkillEngine:
    """Discover, cache, and query skills."""

    def __init__(self, base_dirs: Optional[List[str]] = None):
        if base_dirs is None:
            repo_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
            base_dirs = [
                os.path.join(repo_root, "Skills"),
                os.path.join(repo_root, "skills"),
                os.path.join(repo_root, "engineering-team"),
                os.path.join(repo_root, "marketing-skill"),
                os.path.join(repo_root, "product-team"),
            ]
        self.base_dirs = base_dirs
        self.skills: Dict[str, Skill] = {}
        self._skipped = 0
        self.reload()

    def reload(self) -> None:
        loaded = 0
        skipped = 0
        found_names: List[str] = []
        new_skills: Dict[str, Skill] = {}

        for base in self.base_dirs:
            if not os.path.exists(base):
                continue
            try:
                for root, _, files in os.walk(base):
                    if not any(fname in files for fname in Skill.STANDARD_FILES) and "metadata.json" not in files:
                        continue
                    path = os.path.abspath(root)
                    name = os.path.basename(path)
                    try:
                        if name in self.skills and self.skills[name].path == path:
                            skill = self.skills[name]
                            skill.load(force=False)
                        else:
                            skill = Skill(path)
                        new_skills[skill.name] = skill
                        loaded += 1
                        found_names.append(skill.name)
                    except Exception:
                        skipped += 1
                        logger.debug("Skipped invalid skill at %s", path)
            except Exception:
                logger.debug("Failed to scan base dir %s", base)

        self.skills = new_skills
        self._skipped = skipped

        try:
            logger.info("Loaded %d skills (skipped=%d): %s", loaded, skipped, ", ".join(found_names[:50]))
        except Exception:
            logger.info("Loaded %d skills (skipped=%d)", loaded, skipped)

    def list_skills(self) -> List[str]:
        return sorted(list(self.skills.keys()))

    def match_skills(self, text: str, max_results: int = 8) -> List[Skill]:
        t = (text or "").lower()
        scored: List[tuple] = []
        for skill in self.skills.values():
            try:
                score = 0
                for keyword in skill.keywords:
                    if keyword and keyword in t:
                        score += 10
                if skill.name.lower() in t:
                    score += 5
                if score > 0:
                    scored.append((score + skill.priority, skill))
            except Exception:
                logger.debug("Error scoring skill %s", skill.name)

        scored.sort(key=lambda item: item[0], reverse=True)
        results = [skill for _, skill in scored][:max_results]

        try:
            names = [skill.name for skill in results]
            logger.info("Matched skills for query '%s': %s", (text or "")[:80], ", ".join(names))
        except Exception:
            pass

        return results

    def get_skill_context(self, skill_names: List[str], max_chars: int = 1000) -> str:
        parts: List[str] = []
        for name in skill_names:
            skill = self.skills.get(name)
            if not skill:
                logger.debug("Skill not found: %s", name)
                continue
            try:
                raw = skill.get_preferred_content()
                if not raw:
                    continue
                cleaned = re.sub(r"```.*?```", "", raw, flags=re.S)
                cleaned = re.sub(r"<[^>]+>", "", cleaned)
                match = re.search(r"(?mi)^(#{1,6}\s*examples\b|examples?:)", cleaned)
                if match:
                    cleaned = cleaned[: match.start()]
                cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
                if len(cleaned) > 5000:
                    cleaned = cleaned[:5000]
                parts.append(f"# Skill: {skill.name}\n{cleaned}")
            except Exception:
                logger.debug("Failed to prepare skill context for %s", name)

        joined = "\n\n".join(parts)
        injected = joined
        if len(injected) > max_chars:
            injected = injected[: max_chars - 3] + "..."

        try:
            logger.info("Injected skill context size: %d chars", len(injected))
        except Exception:
            pass

        return injected

    def get_skill_by_name(self, name: str) -> Optional[Skill]:
        return self.skills.get(name)

    def get_skill_metadata(self) -> Dict[str, Dict[str, Any]]:
        out: Dict[str, Dict[str, Any]] = {}
        for name, skill in self.skills.items():
            try:
                out[name] = skill.to_metadata()
            except Exception:
                out[name] = {}
        return out


__all__ = ["SkillEngine", "Skill"]

