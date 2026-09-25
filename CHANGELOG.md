# Changelog

Notable changes to UpsiL. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/). Until 1.0, a minor version may change
the language in incompatible ways; such changes are listed under **Changed**.

## [0.3.0] - 2026-09-25

UpsiL 0.3 comes from using the language. Four real programs were written in 0.2 (a PyTorch
classifier, review labeling with a model, prompt comparison, questions about notes), and what got
in the way was written down in [docs/dogfood.md](docs/dogfood.md). Every item there is addressed
below. Everything 0.2 accepted still compiles, except programs that used the new keywords
`catch` and `throw` as names.

### Added

- Errors: `try { } catch (e: Type) { } finally { }`, several `catch` clauses, `catch { }` without
  a name, `throw value` (a message or an error object) and a bare `throw` inside `catch` that
  re-throws. `Error` and the common Python error types are built in for `catch`; `llm.Error` and
  `llm.FormatError` come with `llm`.
- `with expression as name { }` for context managers, several at once, optionally in
  parentheses: `with nn.no_grad() { ... }`.
- Lambdas: `x => x * 2`, `(a, b) => a + b`, `() => 42`, `(s: str) => s.upper()`.
- List and dict comprehensions with several `for` and `if` clauses, and generator arguments:
  `sum(x * x for x in xs)`, `(x for x in xs)`.
- The `if (condition) a else b` expression.
- Tuples `(a, b)` / `(a,)`, `return a, b`, `val (a, b) = pair`, `var (x, y) = ...`,
  `a, b = b, a`.
- `assert condition, message`, which also runs under `python -O`; the message defaults to the
  condition's source text.
- Raw strings `r"..."` and `r"""..."""` (no escapes, no interpolation) for regular expressions and
  paths.
- `import "helpers.upl" as h` and `import helpers` (a `.upl` file next to the program): each file
  runs once; a missing file is a compile error, a cycle a run-time error.
- Answer shapes: `[m] => text -> json(shape)` and `m.ask(..., schema = shape)` check the reply
  against `str int float bool list dict`, `[T]`, `["a", "b"]` or `{"key": T, "optional?": T}`,
  send the shape as a JSON Schema to servers that constrain output, and when the reply does not
  fit, tell the model what was wrong and ask again (`json_retries`, 1 by default); then
  `llm.FormatError` with the reply in `e.reply`. Plain `-> json` retries the same way.
- `m.ask_all(prompts, ..., workers = 4, errors = "raise" | "null")`: many questions in parallel,
  answers in order.
- `nn.fit` (a training loop with validation, a progress line and a history; Ctrl-C stops early),
  `nn.batches`, `nn.evaluating`, `nn.accuracy`, `nn.auto_device`, `nn.count_params`.
- Modules `csv` (`read`, `parse`, `write`, `stringify`) and `re` (`test`, `find`, `find_all`,
  `groups`, `replace`, `split`, `escape`).
- `upsil test`: runs `fun test_...()` in `test_*.upl` / `*_test.upl` files and reports each test
  with the failing line.
- Examples: spirals (training with `nn.fit`), reviews (shapes, `ask_all`, CSV), prompt_eval
  (lambdas), logs (regular expressions, comprehensions, `try`/`catch`, unpacking; offline).
- `tests/microtorch.py`, a small numpy autograd that stands in for PyTorch, so the neural
  examples and `nn` helpers really train in the tests; `tests/run_microtorch.py` runs a program
  with it.

### Changed

- `try`, `catch`, `finally`, `throw`, `with` and `assert` are keywords (`try`, `finally`, `with`
  and `assert` were already reserved as Python keywords).
- A model reply that is not the JSON asked for raises `llm.FormatError` (a kind of `llm.Error`)
  after one retry, instead of failing at once.
- `if cond print(x)` (a body without braces) now says that the body goes in `{ }` and that a value
  by condition is `if (c) a else b`.
- The VS Code extension is version 1.2.0 (new keywords, raw strings).

## [0.2.0] - 2026-09-25

UpsiL 0.2 is a rewrite. An audit of 0.1 showed that the language worked only in part and that
several advertised features were placeholders. 0.2 keeps the ideas that were worth keeping (the
Kotlin-like syntax, the prompt operator, models and vector stores as declared resources, `model`
blocks as shorthand for PyTorch modules, compiling to readable Python, documentation in Russian
first) and rebuilds them on a small core in which every documented feature is tested.

### Added

- A new compiler: a lexer and a precedence-climbing parser with line and column positions,
  semantic checks, and code generation through Python's `ast` module. Errors in the program are
  reported before it runs, all at once: unknown names (with suggestions), a `val` assigned again,
  `break` outside a loop, `return` outside a function, duplicate parameters, wrong argument
  counts, shadowing, names used before their declaration.
- Language features: statements end at line breaks; `val`/`var` with optional types; functions
  with default and named arguments, closures and nested functions; `if`/`else if`, `while`, two
  forms of `for` with destructuring, `a..b` and `a..=b` ranges; lists, dicts, slices;
  interpolated strings `"{expr}"` and `"{expr:.2f}"`; dedented triple-quoted strings; classes
  with fields, constructors and methods; `import py "module"` for Python libraries.
- AI features: `llm m = llm.Model()`; the prompt operator `[m] => "..."` with `system:` and
  `-> json`; streaming (`m.stream`), conversations (`m.chat`), embeddings (`m.embed`);
  `vector_store db = rag.VectorStore()` with semantic search over embeddings or, when the server
  has none, word search (BM25), plus `add_dir`, `save` and `load`; `model` blocks that become
  `torch.nn.Module` subclasses.
- A real OpenAI-compatible client (standard library only). It uses the SOS model server at
  `http://127.0.0.1:8080/v1` by default, or `UPSIL_LLM_URL`, or `~/.config/upsil/config.toml`;
  an API key is optional. When the server is down it says so, in Russian or English:
  «Локальная модель не отвечает (127.0.0.1:8080). В СОС: sos models serve».
- Runtime modules `fs`, `http`, `json`, `sys`, `math`, `time`, `random`; `ui` keeps the tkinter
  chat window of 0.1 and now runs the handler in a background thread.
- The `upsil` command: `run`, `build`, `check`, `repl`, `version`, `help`; exit codes 0, 1, 2
  and 64; run-time errors shown with UpsiL source lines instead of Python internals.
- Examples: hello, fib, collections, chat, rag_notes, summarize, neural_net, neurochat.
- Documentation: the language specification in Russian and English with an EBNF grammar, a
  tutorial in Russian, READMEs in Russian and English. Code examples in the documentation are
  tested.
- Syntax highlighting for VS Code, GNOME Text Editor and Kate, generated from the same keyword
  list the lexer uses.
- Packaging with `pyproject.toml` (the `upsil` command, the optional `nn` extra for PyTorch),
  the Apache-2.0 license, a NOTICE file, and continuous integration on Python 3.10 to 3.13.

### Changed

These break programs written for 0.1:

- A line break ends a statement: `val x = 5` followed by a line `-3` is two statements (0.1 read
  `val x = 5 - 3`).
- Operators have precedence: `(1 + 2) * 3` is 9 (0.1 printed 7).
- `not` replaces `!`; `&&` and `||` are errors with a hint to use `and` and `or`.
- Modules are imported by their UpsiL names (`import llm`, `import rag`, `import nn`) and used
  through them: `llm.Model(...)`, `rag.VectorStore()`. `import cortex.rag`, `LLM(...)` and
  `VectorStore(dim = 768)` are gone.
- `{...}` in a string is interpolation checked by the compiler; a literal brace is written `\{`.
- In `model` blocks, members are called by name (`l1(x)`), and a `forward` method is required.
- `print` shows `true`, `false` and `null`.
- `upsil run` no longer writes a `.py` file next to the program, and it never chooses between
  two engines; `upsil build` prints the Python or writes it where `-o` says.
- The VS Code extension moves to the `svoya-os` publisher, version 1.1.0.

### Removed

- The LLVM JIT (`upsil/llvm_compiler.py`) and the features only it knew (`malloc`, `free`,
  `gpu_kernel`, native file and socket calls). It generated invalid or wrong code for much of
  the language. It is kept in the git history and may return as a second backend behind the new
  front end.
- `ctxpm`, a package manager that only printed messages.
- `UpsiL_Documentation.md` and `generate_docs.py`: 1.2 MB of text, 99.6 % of it the same
  chapters repeated by a script. The new documentation describes what exists.
- `stdlib/*.upl` and `generate_stdlib.py`: 14,000 lines of functions that returned 0. The
  standard library is now the runtime modules described in the specification.
- `run_massive_tests.py`, which generated programs but checked nothing. There is now a real
  test suite.
- The placeholder AI runtime: `llm.Model` answered with random canned phrases, `rag` returned
  the first document for every query, `nn.Linear` returned a string.
- `upsil/lsp.py`: its diagnostics always pointed at line 1 and its completions were fixed
  snippets. A language server may return on top of the new checker.
- `CortexLang/` (an earlier copy of the project under its old name), `setup.py` (replaced by
  `pyproject.toml`), `setup_icon.py` and `make_transparent.py` (they depended on one computer's
  Windows paths), stray test programs and generated `.py` files, committed `.vsix` packages.

### Fixed

Problems of 0.1 that the rewrite fixes:

- A string literal could not contain the letter `n` (a typo in the lexer's regular expression).
- Line breaks did not end statements, and operators had no precedence.
- Methods of `model` blocks were generated outside the class.
- String literals were pasted into Python source, so `"{...}"` ran arbitrary Python and a quote
  inside a string could inject code. Interpolation is now compiled from UpsiL expressions and
  values are inserted as data.
- The prompt operator `[m] => "..."` did not parse.

## [0.1.0]

The first prototype: an LLVM JIT for a subset of the language, a transpiler to Python for
programs that used `ui`, `llm` or `rag`, and the VS Code extension. It is available in the git
history of this repository.

[0.2.0]: https://github.com/svoya-os/upsil/releases/tag/v0.2.0
