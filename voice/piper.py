import subprocess
from core.logger import get_logger

logger = get_logger(__name__)

class PiperTTS:
    """Minimal wrapper around a local Piper TTS executable or service.

    This acts as a placeholder. Configure `cmd` to point at your local piper binary.
    """

    def __init__(self, cmd: str = "piper", voice: str = "alloy"):
        self.cmd = cmd
        self.voice = voice

    def speak(self, text: str):
        try:
            subprocess.run([self.cmd, "--voice", self.voice, text], check=False)
        except Exception as e:
            logger.warning("Piper TTS invoke failed: %s", e)
