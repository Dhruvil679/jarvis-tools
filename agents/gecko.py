class GeckoAgent:
    def __init__(self):
        self.name = "Gecko"

    def run(self, prompt: str) -> str:
        return f"{self.name}: Ready to assist with {prompt}"
