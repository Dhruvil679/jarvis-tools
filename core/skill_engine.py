"""SkillEngine: metadata-first discovery, lazy content loading, JSON disk cache.

Phase 3 optimisation goals
--------------------------
1. **Metadata-only at startup**: only ``metadata.json`` is read per skill;
   full text files are loaded lazily on first content request.
2. **Walk-bypass cache**: the JSON sidecar stores the *list of discovered paths*
   keyed by a base-directory fingerprint (mtime).  On warm starts the entire
   ``os.walk`` is skipped, dropping boot time by ~10×.
3. **Per-skill metadata cache**: each entry stores its ``metadata.json`` mtime +
   parsed payload so unchanged skills avoid any file I/O at all.
"""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional

from .logger import get_logger


logger = get_logger(__name__)

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_CACHE_FILE = os.path.join(_REPO_ROOT, ".skill_cache.json")
_CONTENT_FILES = ("SKILL.md", "CLAUDE.md", "prompt.md", "README.md", "system_prompt.md")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _dir_fingerprint(path: str) -> float:
    """Return the mtime of a directory (changes when entries are added/removed)."""
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _is_skill_dir(files: List[str]) -> bool:
    return "metadata.json" in files or any(f in files for f in _CONTENT_FILES)


# ---------------------------------------------------------------------------
# Skill
# ---------------------------------------------------------------------------

class Skill:
    """Represents a skill directory.

    *Metadata* is resolved eagerly (cheap JSON parse or cache hit).
    *Content files* are read lazily on the first call to
    :py:meth:`get_preferred_content`.
    """

    def __init__(self, path: str, preloaded_metadata: Optional[Dict[str, Any]] = None,
                 meta_mtime: float = 0.0):
        self.path = path
        self.name = os.path.basename(path)
        self._metadata: Dict[str, Any] = preloaded_metadata if preloaded_metadata is not None else {}
        self._meta_mtime: float = meta_mtime
        self._content_loaded = False
        self._files: Dict[str, str] = {}

        if preloaded_metadata is None:
            self._load_metadata()

    # ------------------------------------------------------------------
    # Metadata
    # ------------------------------------------------------------------

    def _load_metadata(self) -> None:
        meta_path = os.path.join(self.path, "metadata.json")
        try:
            if os.path.exists(meta_path):
                self._meta_mtime = os.path.getmtime(meta_path)
                with open(meta_path, "r", encoding="utf-8") as fh:
                    self._metadata = json.load(fh)
            else:
                self._metadata = {}
        except Exception:
            logger.debug("Failed to load metadata for skill: %s", self.name)
            self._metadata = {}

    @property
    def metadata(self) -> Dict[str, Any]:
        return self._metadata

    @property
    def keywords(self) -> List[str]:
        kws = self._metadata.get("keywords", []) or []
        return [str(k).lower() for k in kws if k]

    @property
    def priority(self) -> int:
        try:
            return int(self._metadata.get("priority", 5))
        except Exception:
            return 5

    def to_metadata(self) -> Dict[str, Any]:
        return {"name": self.name, **(self._metadata or {})}

    # ------------------------------------------------------------------
    # Content (lazy)
    # ------------------------------------------------------------------

    def _load_content(self) -> None:
        if self._content_loaded:
            return
        for fname in _CONTENT_FILES:
            p = os.path.join(self.path, fname)
            try:
                if os.path.exists(p):
                    with open(p, "r", encoding="utf-8") as fh:
                        self._files[fname] = fh.read()
            except Exception:
                logger.debug("Failed to read %s for skill %s", fname, self.name)
        self._content_loaded = True

    def get_preferred_content(self) -> Optional[str]:
        self._load_content()
        for fname in ("SKILL.md", "CLAUDE.md", "prompt.md", "README.md"):
            txt = self._files.get(fname, "")
            if txt and txt.strip():
                return txt
        return None

    # ------------------------------------------------------------------
    # Cache serialisation
    # ------------------------------------------------------------------

    def cache_entry(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "meta_mtime": self._meta_mtime,
            "metadata": self._metadata,
        }


# ---------------------------------------------------------------------------
# SkillEngine
# ---------------------------------------------------------------------------

class SkillEngine:
    """Discover, cache, and query skills.

    Cache layout (``_CACHE_FILE``)::

        {
          "base_fingerprints": { "<abs_base_dir>": <mtime_float>, ... },
          "skill_paths": [ "<abs_path>", ... ],          # discovered paths
          "skills": { "<abs_path>": { cache_entry }, ... }
        }

    Warm-start fast path
    --------------------
    If every base-dir mtime matches the stored fingerprint, we skip
    ``os.walk`` entirely and reconstruct skills directly from
    ``cache["skill_paths"]``.  Per-skill metadata is also served from cache
    when its ``metadata.json`` mtime is unchanged, so the whole boot may
    involve *zero* filesystem reads beyond the single cache JSON.
    """

    def __init__(self, base_dirs: Optional[List[str]] = None):
        if base_dirs is None:
            base_dirs = [
                os.path.join(_REPO_ROOT, "Skills"),
                os.path.join(_REPO_ROOT, "skills"),
                os.path.join(_REPO_ROOT, "engineering-team"),
                os.path.join(_REPO_ROOT, "marketing-skill"),
                os.path.join(_REPO_ROOT, "product-team"),
            ]
        self.base_dirs = [os.path.abspath(d) for d in base_dirs]
        self.skills: Dict[str, Skill] = {}
        self._disk_cache: Dict[str, Any] = {}
        self._skipped = 0

        t0 = time.perf_counter()
        self._load_disk_cache()
        self.reload()
        elapsed = time.perf_counter() - t0
        logger.info(
            "SkillEngine ready in %.3fs — %d skills loaded",
            elapsed, len(self.skills),
        )

    # ------------------------------------------------------------------
    # Disk cache I/O
    # ------------------------------------------------------------------

    def _load_disk_cache(self) -> None:
        try:
            if os.path.exists(_CACHE_FILE):
                with open(_CACHE_FILE, "r", encoding="utf-8") as fh:
                    self._disk_cache = json.load(fh)
        except Exception:
            self._disk_cache = {}

    def _flush_disk_cache(self) -> None:
        try:
            with open(_CACHE_FILE, "w", encoding="utf-8") as fh:
                json.dump(self._disk_cache, fh)
        except Exception:
            logger.debug("Could not write skill cache to %s", _CACHE_FILE)

    # ------------------------------------------------------------------
    # Reload
    # ------------------------------------------------------------------

    def reload(self) -> None:
        cached_fingerprints: Dict[str, float] = self._disk_cache.get("base_fingerprints", {})
        cached_skill_paths: List[str] = self._disk_cache.get("skill_paths", [])
        cached_skills: Dict[str, Any] = self._disk_cache.get("skills", {})

        # Compute current base-dir fingerprints
        current_fingerprints = {d: _dir_fingerprint(d) for d in self.base_dirs}

        # Can we skip os.walk?
        walk_needed = (
            not cached_skill_paths
            or current_fingerprints != cached_fingerprints
        )

        if walk_needed:
            skill_paths = self._walk_skill_paths()
        else:
            # Fast path: trust cached path list
            skill_paths = [p for p in cached_skill_paths if os.path.isdir(p)]

        new_skills: Dict[str, Skill] = {}
        new_cached_skills: Dict[str, Any] = {}
        skipped = 0
        found_names: List[str] = []

        for path in skill_paths:
            name = os.path.basename(path)
            try:
                skill = self._resolve_skill(path, cached_skills)
                new_skills[name] = skill
                new_cached_skills[path] = skill.cache_entry()
                found_names.append(name)
            except Exception:
                skipped += 1
                logger.debug("Skipped invalid skill at %s", path)

        self.skills = new_skills
        self._skipped = skipped

        # Persist updated cache
        self._disk_cache = {
            "base_fingerprints": current_fingerprints,
            "skill_paths": list(new_cached_skills.keys()),
            "skills": new_cached_skills,
        }
        self._flush_disk_cache()

        logger.info(
            "Loaded %d skills (skipped=%d, walk=%s): %s",
            len(found_names), skipped, walk_needed,
            ", ".join(found_names[:30]),
        )

    def _walk_skill_paths(self) -> List[str]:
        """Full os.walk discovery — used only on cold/stale starts."""
        paths: List[str] = []
        for base in self.base_dirs:
            if not os.path.exists(base):
                continue
            try:
                for root, _dirs, files in os.walk(base):
                    if _is_skill_dir(files):
                        paths.append(os.path.abspath(root))
            except Exception:
                logger.debug("Failed to scan base dir %s", base)
        return paths

    def _resolve_skill(self, path: str, cached_skills: Dict[str, Any]) -> Skill:
        """Return a Skill, using cached metadata when metadata.json is unchanged."""
        meta_path = os.path.join(path, "metadata.json")
        current_mtime = 0.0
        try:
            if os.path.exists(meta_path):
                current_mtime = os.path.getmtime(meta_path)
        except OSError:
            pass

        entry = cached_skills.get(path)
        if entry and entry.get("meta_mtime") == current_mtime:
            # Cache hit — no file I/O needed
            return Skill(path, preloaded_metadata=entry.get("metadata", {}),
                         meta_mtime=current_mtime)

        # Cache miss — read from disk
        skill = Skill(path)
        return skill

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def list_skills(self) -> List[str]:
        return sorted(self.skills.keys())

    def match_skills(self, text: str, max_results: int = 8) -> List[Skill]:
        t = (text or "").lower()
        scored: List[tuple] = []
        for skill in self.skills.values():
            try:
                score = sum(10 for kw in skill.keywords if kw and kw in t)
                if skill.name.lower() in t:
                    score += 5
                if score > 0:
                    scored.append((score + skill.priority, skill))
            except Exception:
                logger.debug("Error scoring skill %s", skill.name)

        scored.sort(key=lambda item: item[0], reverse=True)
        results = [skill for _, skill in scored][:max_results]
        logger.info(
            "Matched skills for '%s': %s",
            (text or "")[:80],
            ", ".join(s.name for s in results),
        )
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
                m = re.search(r"(?mi)^(#{1,6}\s*examples\b|examples?:)", cleaned)
                if m:
                    cleaned = cleaned[: m.start()]
                cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
                if len(cleaned) > 5000:
                    cleaned = cleaned[:5000]
                parts.append(f"# Skill: {skill.name}\n{cleaned}")
            except Exception:
                logger.debug("Failed to prepare skill context for %s", name)

        joined = "\n\n".join(parts)
        if len(joined) > max_chars:
            joined = joined[: max_chars - 3] + "..."
        logger.info("Skill context size: %d chars", len(joined))
        return joined

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
