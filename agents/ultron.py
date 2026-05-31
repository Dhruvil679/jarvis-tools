class UltronAgent:
    def __init__(self):
        self.name = "Ultron"

    def run(self, prompt: str) -> str:
        return f"{self.name}: Processing {prompt}"
