import torch
import torch.nn.functional as F

import cortex.stdlib.rag
import cortex.stdlib.llm
def main():
    print("=== Cortex RAG AI App ===")
    my_model = cortex.stdlib.llm.LLM(provider="cortex-native", model="Noesis-v1")
    db = cortex.stdlib.rag.VectorStore(dim=768)
    db.add("The EWSCS 2026 conference features courses on metric program equivalence and concurrent processes.")
    db.add("Cortex is a new programming language natively designed for neural networks and AI.")
    query = "What is Cortex?"
    context = db.search(query)
    answer = my_model.prompt(f"Answer the query: {query} based on this context: {context}")
    print("\n[AI Output]:")
    print(answer)

main()
