class HulkAgent:
    def __init__(self):
        self.name = "Hulk"

    def run(self, prompt: str) -> str:
        return f"{self.name}: Smash tasks for {prompt}"
