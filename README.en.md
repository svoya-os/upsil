# UpsiL

**A small language for AI scripts.** Kotlin-like syntax, local language models, search over
your own documents and PyTorch networks, with readable Python under the hood.

[Русский](README.md) · [Specification](docs/spec.en.md) · [Tutorial (Russian)](docs/tutorial.md) ·
[Examples](examples) · [Changelog](CHANGELOG.md)

```upsil
import llm
import rag

llm m = llm.Model()                              // local model: sos models serve
vector_store notes = rag.VectorStore()
notes.add_dir("examples/notes")                  // index a folder of notes

val question = "How do I check a backup?"
print([m] => "Answer from the notes:\n{notes.context(question)}\n\nQuestion: {question}")
```

> **Status: v0.2 is an early version.** The language is small and honest: everything the
> documentation describes works and is covered by tests, including the code examples in the
> documentation itself. It is not a mature tool yet: there is no exception handling, no
> anonymous functions and no importing of other `.upl` files, and the syntax may still change.
> The full list is in ["Not in v0.2"](docs/spec.en.md#14-not-in-v02). The documentation is
> written in Russian first; the specification and this README are also in English.

## What it is

- **A language**: `fun`, `val`/`var`, `if`/`else if`, `while`, `for (i in 0..n)`, classes,
  interpolated strings `"Hello, {name}"`, multi-line strings for prompts, clear errors in
  Russian or English with line and column.
- **AI resources in the language**: `llm m = llm.Model()` is a model, `[m] => "..."` asks it,
  `-> json` turns the answer into data, `vector_store db = rag.VectorStore()` searches
  documents, `model Net { ... }` is a PyTorch network.
- **A compiler to Python**: the whole program is checked before it runs (unknown names,
  reassigned `val`s, `break` outside a loop, wrong argument counts...), turned into a Python
  syntax tree and run; `upsil build` shows the resulting code. Any Python library can be used:
  `import py "numpy" as np`.
- **No dependencies**: only Python 3.10+. PyTorch is optional, for `model` blocks.

## Install

```sh
uv tool install git+https://github.com/svoya-os/upsil
# or
pipx install git+https://github.com/svoya-os/upsil
```

Once the package is on PyPI, `uv tool install upsil` (or `pipx install upsil`) will do. With
PyTorch: `uv tool install 'upsil[nn]'`. Check: `upsil version`.

## Five minutes

Variables, strings, functions:

```upsil
val name = "UpsiL"          // a val never changes
var count = 0               // a var can

fun greet(who, punct = "!") {
    return "Hello, {who}{punct}"
}

count += 1
print(greet(name), count)
print(greet("world", punct = "?"))
```
```output
Hello, UpsiL! 1
Hello, world?
```

Loops, lists, dicts:

```upsil
val prices = {"bread": 50, "milk": 90}
var total = 0
for (item, price) in prices.items() {
    total += price
}
val squares = []
for (i in 1..=5) {
    squares.append(i * i)
}
print("total {total}, squares {squares}, even {squares[1::2]}")
```
```output
total 140, squares [1, 4, 9, 16, 25], even [4, 16]
```

Classes:

```upsil
class Account {
    val owner: str
    var balance = 0

    fun deposit(amount) {
        if amount <= 0 {
            error("the amount must be positive")
        }
        balance += amount
    }
}

val acc = Account("Ann")
acc.deposit(100)
print(acc)
```
```output
Account(owner="Ann", balance=100)
```

Errors show up before the program runs:

```upsil-error
val limit = 3
limit = 4
```
```output
example.upl:2:1: error: cannot reassign val 'limit' (declared at line 1); declare it with var
  2 | limit = 4
    | ^^^^^
```

Commands:

```sh
upsil run hello.upl          # run (or simply: upsil hello.upl)
upsil check hello.upl        # check without running
upsil build hello.upl        # show the resulting Python
upsil repl                   # interactive mode
```

## AI in the language

```upsil
import llm

llm m = llm.Model()                                   // the default model
val text = "UpsiL compiles to Python and works with local models."

val summary = [m] => "Summarize in five words: {text}"
val strict = [m, system: "Answer only yes or no"] => "Is Python a programming language?"
val facts = [m] => "Return JSON \{\"language\": ..., \"goal\": ...\} for the text: {text}" -> json

print(summary, strict, facts["language"])
for (piece in m.stream("Write a haiku about compilers")) {
    print(piece, end = "")                            // the answer as it is generated
}
```

- `[m] => text` returns the model's answer as a string; `system:` sets its role; `-> json`
  returns a dict or a list. Values inserted into a prompt with `{...}` are passed as text and
  never executed.
- `rag.VectorStore()` searches by meaning if the server can compute embeddings; otherwise it
  says so and searches by words (BM25). The index is saved as JSON.
- `model` becomes a `torch.nn.Module`; layers are fields, `forward` is a method.

More in the [specification](docs/spec.en.md#9-ai-models-prompts-search).

## UpsiL on SOS

UpsiL is developed as a module of [SOS](https://github.com/svoya-os), a Linux distribution for
working with AI, and talks to its local model server by default:

- `sos models serve` starts llama.cpp in router mode with an OpenAI-compatible API at
  `http://127.0.0.1:8080/v1`, UpsiL's default address; models live in `/srv/ai`;
- `sos models suggest` recommends a model for your GPU;
- if the server is not running, UpsiL says exactly that:
  `The local model is not responding (127.0.0.1:8080). On SOS: sos models serve`;
- the assistant Jackson uses the same server, so models are downloaded once.

Outside SOS any OpenAI-compatible server works (llama.cpp, Ollama, vLLM, LM Studio or a cloud
API): set `UPSIL_LLM_URL` (and `UPSIL_LLM_KEY` if a key is needed) or put them in
`~/.config/upsil/config.toml`.

## Editors

- VS Code: the extension in [vscode-upsil](vscode-upsil);
- GNOME Text Editor and gedit: [editor/upsil.lang](editor/upsil.lang);
- Kate and KWrite: [editor/upsil.xml](editor/upsil.xml).

All three grammars are generated from one keyword list by
[tools/gen_syntax.py](tools/gen_syntax.py). Installation:

```sh
cd vscode-upsil && npx @vscode/vsce package && code --install-extension upsil-lang-1.1.0.vsix
mkdir -p ~/.local/share/gtksourceview-5/language-specs && cp editor/upsil.lang ~/.local/share/gtksourceview-5/language-specs/
mkdir -p ~/.local/share/org.kde.syntax-highlighting/syntax && cp editor/upsil.xml ~/.local/share/org.kde.syntax-highlighting/syntax/
```

## What is new in 0.2

Version 0.2 is a rewrite. Much of 0.1 was a facade: the "model" answered with canned phrases,
search always returned the first document, a network layer returned a string, and the
documentation and standard library were mostly generated repetition. All of that is gone; the
LLVM prototype is kept in git history and may return as a separate backend. Details, including
what changed in the syntax, are in [CHANGELOG.md](CHANGELOG.md).

## Development

```sh
python3 -m unittest discover -s tests -v   # all tests, no network and no PyTorch needed
python3 tools/gen_syntax.py                 # regenerate the editor grammars
python3 -m upsil run examples/hello.upl     # run from a source checkout
```

The tests use only the standard library; a small OpenAI-compatible server started by the tests
stands in for the model.

## License

[Apache-2.0](LICENSE). Author: Maksim Segen; UpsiL contributors are listed in the git history.
