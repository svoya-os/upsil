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

> **Status: v0.3 is an early version.** The language is small and honest: everything the
> documentation describes works and is covered by tests, including the code examples in the
> documentation itself. Version 0.3 grew out of using the language: we wrote neural-network
> training, review labeling with a model, prompt comparison and log parsing in it, and added
> what was missing ([what was inconvenient and what changed](docs/dogfood.md), in Russian).
> What is still missing is listed in ["Not in v0.3"](docs/spec.en.md#14-not-in-v03). The
> documentation is written in Russian first; the specification and this README are also in
> English.

## What it is

- **A language**: `fun`, `val`/`var`, `if`/`else if`, `while`, `for (i in 0..n)`, classes,
  interpolated strings `"Hello, {name}"`, multi-line and raw (`r"\d+"`) strings, lambdas
  `x => x * 2`, comprehensions `[x * x for x in xs if x > 0]`, `if (c) a else b`, tuples and
  unpacking `val (lo, hi) = ...`, errors with `try`/`catch`/`finally`/`throw`, `with`,
  `assert`, imports of your own files `import "helpers.upl"`, tests with `upsil test`, and
  clear errors in Russian or English with line and column.
- **AI resources in the language**: `llm m = llm.Model()` is a model, `[m] => "..."` asks it,
  `-> json(shape)` turns the answer into checked data (a wrong shape makes it ask again),
  `m.ask_all([...])` asks many questions in parallel, `vector_store db = rag.VectorStore()`
  searches documents, `model Net { ... }` is a PyTorch network, `nn.fit(...)` trains it with
  validation and a progress line.
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
val squares = [i * i for i in 1..=5]
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
upsil test                   # run the tests: fun test_...() in test_*.upl files
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
val facts = [m] => "Name the language and the goal: {text}" -> json({"language": str, "goal": str})

print(summary, strict, facts["language"])
for (piece in m.stream("Write a haiku about compilers")) {
    print(piece, end = "")                            // the answer as it is generated
}
```

- `[m] => text` returns the model's answer as a string; `system:` sets its role; `-> json`
  returns a dict or a list, and `-> json(shape)` also checks it: when the model answers in the
  wrong shape, it is told what is wrong and asked again; if that fails, `llm.FormatError` is
  raised, which `catch` can handle. Values inserted into a prompt with `{...}` are passed as
  text and never executed.
- `m.ask_all(questions, schema = shape, errors = "null")` asks many questions in parallel and
  does not stop because of one bad answer.
- `rag.VectorStore()` searches by meaning if the server can compute embeddings; otherwise it
  says so and searches by words (BM25). The index is saved as JSON.
- `model` becomes a `torch.nn.Module`; layers are fields, `forward` is a method.
  `nn.fit(net, x, y, epochs = 60, val = (x_test, y_test))` trains it, `nn.accuracy` measures
  it, and `with nn.no_grad() { ... }` computes without gradients.

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
cd vscode-upsil && npx @vscode/vsce package && code --install-extension upsil-lang-1.2.0.vsix
mkdir -p ~/.local/share/gtksourceview-5/language-specs && cp editor/upsil.lang ~/.local/share/gtksourceview-5/language-specs/
mkdir -p ~/.local/share/org.kde.syntax-highlighting/syntax && cp editor/upsil.xml ~/.local/share/org.kde.syntax-highlighting/syntax/
```

## What is new in 0.3

Version 0.3 was tested by use: four real programs were written in UpsiL (a PyTorch classifier,
review labeling with a model, prompt comparison, questions about notes) and what got in the way
was written down ([docs/dogfood.md](docs/dogfood.md), in Russian). One malformed model reply
used to end a whole labeling run: now there are `try`/`catch`, answer shapes and a second try.
`torch.no_grad()` could not be used: now there is `with`. Data columns were built with loops:
now there are comprehensions. Sorting and prompt templates needed separate functions: now
there are lambdas. The training loop was written by hand: now there is `nn.fit`. Plus tuples and
unpacking, the `if` expression, raw strings for regular expressions, the `csv` and `re` modules,
imports of your own files and `upsil test`. Details are in [CHANGELOG.md](CHANGELOG.md).

Version 0.2 was a rewrite after an audit of 0.1, much of which was a facade; the LLVM prototype
of 0.1 is kept in git history.

## Development

```sh
python3 -m unittest discover -s tests -v   # all tests, no network and no PyTorch needed
python3 tools/gen_syntax.py                 # regenerate the editor grammars
python3 -m upsil run examples/hello.upl     # run from a source checkout
```

The tests use only the standard library; a small OpenAI-compatible server started by the tests
stands in for the model, and `tests/microtorch.py`, a small numpy autograd, stands in for
PyTorch, so the example networks really train in the tests. To run a program with it:
`python3 tests/run_microtorch.py examples/spirals.upl`.

## License

[Apache-2.0](LICENSE). Author: Maksim Segen; UpsiL contributors are listed in the git history.
