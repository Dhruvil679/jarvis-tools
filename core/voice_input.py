import asyncio
import speech_recognition as sr
from typing import Optional

class VoiceInput:
    """Voice input handler using SpeechRecognition."""

    def __init__(self, recognizer: Optional[sr.Recognizer] = None, mic_index: Optional[int] = None):
        self.recognizer = recognizer or sr.Recognizer()
        self.mic_index = mic_index

    async def listen(self, timeout: float = 5.0, phrase_time_limit: float = 8.0) -> Optional[str]:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._listen_blocking, timeout, phrase_time_limit)

    def _listen_blocking(self, timeout, phrase_time_limit):
        try:
            with sr.Microphone(device_index=self.mic_index) as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=0.6)
                audio = self.recognizer.listen(source, timeout=timeout, phrase_time_limit=phrase_time_limit)
            text = self.recognizer.recognize_google(audio)
            return text
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except sr.RequestError:
            return None
        except Exception:
            return None
