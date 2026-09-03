class VectorStore:
    def __init__(self, dim=768):
        self.dim = dim
        self.documents = []
        
    def add(self, text: str):
        self.documents.append(text)
        print(f"[VectorStore] Added document: '{text[:20]}...'")
        
    def search(self, query: str, top_k: int = 1) -> str:
        print(f"[VectorStore] Searching for '{query}'...")
        # Mock vector search for MVP: just return the first doc if any
        if not self.documents:
            return "No context found."
        # In a real engine, this would do embedding + cosine similarity
        return self.documents[0]
