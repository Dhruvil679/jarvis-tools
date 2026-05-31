from __future__ import annotations

import asyncio
import sys

from config.config import config
from core.agent_manager import AgentManager
from core.agent_router import AgentRouter
from core.command_router import CommandRouter
from core.logger import get_logger
from core.ollama_client import OllamaClient
from core.orchestrator import JarvisOrchestrator
from core.skill_engine import SkillEngine
from core.tts import TTSEngine
from core.voice_input import VoiceInput
from tools import calculator_tool, google_tool, spotify_tool, system_tool, youtube_tool
from ui.terminal_ui import boot_sequence, status_log, typing_print


logger = get_logger("main")


async def init_systems() -> None:
    await boot_sequence()


async def main_loop() -> None:
    voice = VoiceInput()
    tts = TTSEngine(use_piper=config.USE_PIPER, piper_cmd=config.PIPER_CMD)
    ollama = OllamaClient(base_url=config.OLLAMA_URL, model=config.MODEL, timeout=config.OLLAMA_TIMEOUT)
    skill_engine = SkillEngine()
    agent_manager = AgentManager(
        agents_root=config.AGENTS_ROOT,
        memory_root=config.MEMORY_ROOT,
        skill_engine=skill_engine,
        llm_client=ollama,
    )
    agent_router = AgentRouter(routes_path=config.ROUTE_CONFIG)
    orchestrator = JarvisOrchestrator(
        agent_manager=agent_manager,
        agent_router=agent_router,
        skill_engine=skill_engine,
    )

    router = CommandRouter()
    router.register("youtube", lambda text: youtube_tool.open_youtube(text))
    router.register("google", lambda text: google_tool.search_google(text))
    router.register("spotify", lambda text: spotify_tool.open_spotify(text))
    router.register("system", lambda text: system_tool.system_status(text))
    router.register("calculator", lambda text: calculator_tool.calculate(text))

    status_log("JARVIS OS online. Type a request or press Enter for voice input.")

    while True:
        try:
            typing_print("Awaiting input (press Enter to speak, or type 'exit'):")
            line = await asyncio.get_running_loop().run_in_executor(None, sys.stdin.readline)
            if not line:
                await asyncio.sleep(0.1)
                continue

            line = line.strip()
            if line.lower() == "exit":
                tts.speak("Shutting down. Goodbye.")
                break

            if line:
                text = line
            else:
                text = await voice.listen()
                if not text:
                    status_log("No speech detected.")
                    continue

            command_result = await router.route(text)
            if command_result:
                orchestrator.shared_memory.add_message("system", command_result, {"source": "command_router"})
                typing_print(f"\nJARVIS: {command_result}\n")
                tts.speak(command_result)
                continue

            result = await orchestrator.process(text, mode="auto")
            status_log(f"Route: {result.route.primary_agent} | Mode: {result.mode} | Confidence: {result.route.confidence:.2f}")
            if result.route.collaborators:
                status_log(f"Collaborators: {', '.join(result.route.collaborators)}")

            typing_print(f"\nJARVIS: {result.final_response}\n")
            tts.speak(result.final_response)

        except KeyboardInterrupt:
            tts.speak("Interrupted. Shutting down.")
            break
        except Exception as exc:
            logger.exception("Main loop error: %s", exc)
            await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(init_systems())
        asyncio.run(main_loop())
    except Exception as exc:
        logger.exception("Fatal error: %s", exc)
