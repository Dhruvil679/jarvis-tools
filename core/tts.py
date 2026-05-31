import subprocess
import threading
import time
import sys
from typing import Optional

try:
    import pyttsx3
except Exception:
    pyttsx3 = None

class TTSEngine:
    """TTS engine supporting Piper (if available) and fallback engines."""

    def __init__(self, use_piper: bool = False, piper_cmd: Optional[str] = None):
        self.use_piper = use_piper
        self.piper_cmd = piper_cmd or "piper"
        self._init_fallback()

    def _init_fallback(self):
        if pyttsx3:
            try:
                self.engine = pyttsx3.init()
            except Exception:
                self.engine = None
        else:
            self.engine = None

    def speak(self, text: str):
        """Speak text using Piper if configured; otherwise fallback to pyttsx3 or console."""
        if not text:
            return
        if self.use_piper:
            try:
                subprocess.run([self.piper_cmd, text], check=False)
                return
            except Exception:
                pass

        if self.engine:
            try:
                # run in thread to avoid blocking
                t = threading.Thread(target=self.engine.say, args=(text,))
                t.start()
                self.engine.runAndWait()
                return
            except Exception:
                pass

        # Last fallback: simple console print with small delay to feel like speaking
        for ch in text:
            sys.stdout.write(ch)
            sys.stdout.flush()
            time.sleep(0.002)
        sys.stdout.write("\n")
