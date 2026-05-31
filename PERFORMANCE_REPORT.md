# Performance Report

## Measured Timings
- `SkillEngine` initialization: `1.464s` for `2,838` discovered skills.
- `AgentManager` initialization: `0.023s` for all 9 agents and their SQLite stores.
- Routing throughput: `100` route decisions in `0.003s`.
- Orchestrator throughput: `20` single-agent runs in `0.406s`.
- API health throughput: `20` `/health` requests in `0.096s`.

## Frontend Build
- Vite build time: `727ms`.
- Output JS bundle: `149.32 kB` raw, `48.11 kB` gzip.
- Output CSS bundle: `9.44 kB` raw, `2.95 kB` gzip.

## Observations
- Skill discovery dominates startup cost because the repo contains a large skill catalog.
- Agent routing and API health checks are effectively instantaneous relative to skill loading.
- The fallback orchestrator path remains lightweight when no live LLM call is required.

