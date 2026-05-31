import asyncio
import sys
import time
from rich.console import Console
from rich.panel import Panel
from core.logger import get_logger

console = Console()
logger = get_logger(__name__)

async def boot_sequence():
    console.clear()
    console.rule("[bold cyan]J.A.R.V.I.S.[/bold cyan] Booting")
    stages = [
        "Initializing core systems",
        "Loading voice modules",
        "Connecting to Ollama",
        "Spawning agents",
        "Completing diagnostics",
    ]
    for s in stages:
        console.print(f"[cyan]>[/cyan] {s}")
        await asyncio.sleep(0.5)
    console.rule("[green]Online[/green]")

def typing_print(text: str, delay: float = 0.01):
    for ch in text:
        sys.stdout.write(ch)
        sys.stdout.flush()
        time.sleep(delay)
    sys.stdout.write("\n")

def status_log(message: str):
    console.print(Panel(message, style="bold white on black"))
