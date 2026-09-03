# 🧠 CortexDOC

**Cortex** is a next-generation programming language engineered from the ground up for the Artificial Intelligence ecosystem. 

Unlike traditional languages (like Python) where AI features are bolted on via heavy C++ libraries, Cortex treats AI concepts—tensors, neural models, vector databases, and LLM prompting—as **first-class citizens** at the compiler level.

---

## 🚀 Installation & Usage

Cortex comes with a built-in compiler (transpiler) and CLI.

### 1. Installation
Navigate to the Cortex project folder and install it locally:
```bash
cd CortexLang
pip install -e .
```

### 2. The CLI
You can execute `.ctx` files using the `cortex` command:
```bash
# Compile and run the code immediately
cortex run my_app.ctx

# Compile to Python without running (generates my_app.py)
cortex build my_app.ctx
```

---

## 📖 Language Reference

### 1. Variables & Types
Cortex uses Kotlin-style variable declarations, making scope and mutability explicitly clear for both humans and AI.

- `val`: Immutable value (cannot be reassigned)
- `var`: Mutable variable

```kotlin
val name: string = "Cortex"
var epoch: int = 0
```

Native AI Types:
- `tensor`: N-dimensional array for mathematical operations.
- `prob`: A probabilistic float (e.g., model confidence).
- `llm`: A Large Language Model instance.
- `vector_store`: A vector database.

### 2. Functions
Functions are defined using the `fun` keyword. Type hinting is strictly enforced.

```kotlin
fun forward(x: tensor, W: tensor) -> tensor {
    return x @ W
}
```
*(Note: Cortex natively understands the `@` operator as matrix multiplication).*

### 3. RAG and LLMs (Standard Library)
Cortex comes with a native `stdlib` that eliminates the need for massive frameworks like LangChain.

#### Initializing Models
```kotlin
import cortex.rag
import cortex.llm

llm my_model = LLM(provider="openai", model="gpt-4")
vector_store db = VectorStore(dim=768)
```

#### Native Prompting (`=>`)
Instead of formatting strings and making HTTP requests, Cortex introduces the **Prompt Operator (`=>`)**. The compiler inherently understands that you are sending a string to an LLM. String formatting is done implicitly.

```kotlin
val query = "What is metric program equivalence?"
val context = db.search(query)

// Send prompt directly to the model
val answer = [my_model] => "Answer the query: {query} based on context: {context}"
```

---

## 🔮 Advanced Concepts (From EWSCS 2026)

Cortex is currently in early development. The compiler architecture is designed to support the following paradigms in the near future:

### 1. Probabilistic Control Flow
Traditional `if/else` statements only handle `True` or `False`. Cortex `prob` types will allow probabilistic branching natively:
```kotlin
prob confidence = model.predict(x)

if confidence > 0.95 {
    // High confidence path
} else_prob {
    // Escalate to human or fallback model
}
```

### 2. Distributed Consensus
Training across clusters normally requires complex MPI or NCCL boilerplate. Cortex will support `distributed` blocks natively:
```kotlin
distributed (cluster_nodes) {
    tensor local_grad = compute_grad()
    consensus W = W - lr * average(local_grad)
}
```

---

## 🛠 Standard Library Modules

- `cortex.llm`: Access to the `LLM` class.
- `cortex.rag`: Access to the `VectorStore` class.
- `cortex.nn`: (Coming soon) Access to native neural network layers `Linear`, `Conv`, `Transformer`.

*Designed for AI, by AI.*
