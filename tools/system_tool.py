import platform
import psutil
from core.logger import get_logger

logger = get_logger(__name__)

def system_status(_: str = "") -> str:
    """Return a brief system diagnostic summary."""
    try:
        uname = platform.uname()
        cpu = psutil.cpu_percent(interval=0.5)
        mem = psutil.virtual_memory()
        status = (
            f"OS: {uname.system} {uname.release} | CPU: {cpu}% | "
            f"Mem: {mem.percent}% ({int(mem.used/1024**2)}MB/{int(mem.total/1024**2)}MB)"
        )
        return status
    except Exception as e:
        logger.exception("Failed to gather system status: %s", e)
        return "Unable to get system status"
