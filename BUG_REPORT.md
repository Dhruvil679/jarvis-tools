# Bug Report

## Fixed Issues
- Legacy helper scripts executed at import time: `open_youtube.py`, `jarvis.py`, and `jarvis_core.py` now use callable entrypoints and `__main__` guards.
- Dashboard TypeScript build referenced the Vite node config through a project-reference chain, which pulled browser types into the wrong compile scope. The reference was removed so the app build only checks the client sources.
- Dashboard dependency audit reported moderate `vite` / `esbuild` vulnerabilities. The stack was upgraded to Vite `8.0.14` and `@vitejs/plugin-react` `6.0.2`, which cleared `npm audit`.

## Resolved Verification Gaps
- Repo-wide runtime import audit now passes without interactive side effects.
- Agent and SQLite validation now passes for all 9 agents.
- Dashboard build now passes end to end.

## Residual Notes
- `FastAPI` test client currently emits a deprecation warning about `httpx`. This is non-blocking and did not affect endpoint verification.

