import subprocess
from core.logger import get_logger

logger = get_logger(__name__)

def run_script(path: str) -> str:
    try:
        subprocess.Popen([path], shell=True)
        return f"Started {path}"
    except Exception as e:
        logger.exception("Failed to start automation script: %s", e)
        return "Failed to run automation"
