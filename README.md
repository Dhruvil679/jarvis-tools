# JARVIS Operating System (jarvis-tools)

JARVIS now runs as a multi-agent operating system with specialist agents, per-agent memory, an orchestrator, a FastAPI backend, and a React dashboard scaffold.

## What Changed
- `Friday`, `Oracle`, `Vision`, `Ultron`, `Hulk`, `Spectre`, `Herald`, `Veronica`, and `Gecko` now live as data-driven agents under `agents/`.
- `core/agent_router.py`, `core/agent_manager.py`, `core/agent_memory.py`, and `core/orchestrator.py` provide the new runtime.
- `api/` exposes `/agents`, `/agents/status`, `/chat`, `/memory`, and `/skills`.
- `dashboard/` contains the React + TypeScript + Tailwind UI scaffold.
- `core/skill_engine.py` now scans the larger skill catalog recursively, including the `Skills/` tree.

## Install
```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## Run
```bash
python main.py
```

## API
```bash
python -m api.server
```

## Dashboard
```bash
cd dashboard
npm install
npm run dev
```

## Configuration
- `config/config.py` now includes agent roots, memory roots, API host/port, and the route config path.
- `config/agent_routes.json` controls default routing behavior.
- `OLLAMA_URL`, `OLLAMA_MODEL`, and `OLLAMA_TIMEOUT` still control the local model client.

## Notes
- The API and dashboard are scaffolded for local development and can be extended with real tool execution and richer UI state.
- Windows voice input still depends on the local audio stack and PyAudio availability.

x