class LLM:
    def __init__(self, provider="mock", model="mock-v1"):
        self.provider = provider
        self.model = model
        print(f"[LLM] Initialized model {model} via {provider}")
        
    def prompt(self, text: str) -> str:
        print(f"[LLM] Sending prompt: {text}")
        return f"AI Generated Response based on: {text}"
