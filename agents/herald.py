class HeraldAgent:
    def __init__(self):
        self.name = "Herald"

    def run(self, prompt: str) -> str:
        return f"{self.name}: Announcing - {prompt}"
