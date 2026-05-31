class VeronicaAgent:
    def __init__(self):
        self.name = "Veronica"

    def run(self, prompt: str) -> str:
        return f"{self.name}: Strategizing for {prompt}"
