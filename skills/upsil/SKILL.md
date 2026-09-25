---
name: upsil
description: Write, run and fix programs in UpsiL (упсиль), the SOS language for AI scripts (.upl files) — prompts to a local LLM, JSON answers of a given shape, search over notes, PyTorch networks, CSV data.
aliases: упсил, upsil
---
# UpsiL

UpsiL compiles to readable Python. Files end in `.upl`; Kotlin-like syntax, no semicolons.

- Run: `sos run main.upl ARGS` (environment header, progress in the SOS bar) or `upsil run main.upl ARGS`.
- Check without running: `upsil check main.upl`. Tests: `upsil test` runs every `fun test_...()` in `test_*.upl`.
- New project: `sos new NAME --template upsil`. Local model: `sos models serve` (UpsiL finds it at 127.0.0.1:8080).
- PyTorch for `nn`: `uv add torch` in the project folder; `sos run` then uses the project's `.venv`.
- Spec, tutorial, examples: /usr/share/doc/upsil.

## Language

```upsil
import py "statistics"      // a Python module; import "helpers.upl" as h — another UpsiL file
val name = "мир"            // val: constant, var: variable; types are optional: var n: int = 0
var n = 0
print("Привет, {name}! {n + 1}")   // {expr} interpolates; \{ \} are braces; r"\d+" is raw
fun add(a, b = 1) { return a + b }
val double = x => x * 2           // lambdas: (a, b) => a + b
if n > 0 { print("+") } else if n < 0 { print("-") } else { print("0") }
for (i in 0..3) { n += i }        // 0, 1, 2; 1..=3 includes 3
for (k, v) in {"a": 1}.items() { print(k, v) }
while n > 100 { break }
val sign = if (n > 0) "+" else "-"
val evens = [x for x in 0..10 if x % 2 == 0]
val (lo, hi) = (min(evens), max(evens))
try { print(10 / n) } catch (e: ZeroDivisionError) { print("ноль") } catch (e) { throw } finally { print("ok") }
assert len(evens) == 5, "evens = {evens}"
class Point {
    val x: float
    val y: float
    fun norm() { return (x * x + y * y) ** 0.5 }
}
print(Point(3, 4).norm(), div(7, 2), statistics.mean([1, 2]))   // div: integer division; / is float
```

`true`, `false`, `null`; `and`, `or`, `not`; `//` comments; `error("...")` or `throw "..."` to fail.
Modules: `llm rag nn csv json fs re http sys math time random ui`; `sys.args` holds the arguments.

## Models

```upsil
import llm
llm m = llm.Model(temperature = 0.2)   // or llm.Model("qwen3.5-4b")
val text = "UpsiL — язык для ИИ-скриптов."
val short = [m] => "Перескажи одним предложением: {text}"
val word = [m, system: "Отвечай одним словом"] => "Столица Франции?"
val shape = {"label": ["pos", "neg", "neu"], "score": float, "note?": str}
try {
    val a = [m] => "Оцени тональность: {text}" -> json(shape)
    print(a.label, a.score)      // JSON answers are records: a.label == a["label"]
} catch (e: llm.FormatError) {
    print("не тот JSON:", e.reply)
}
val answers = m.ask_all(["Тема: {t}" for t in ["кошки", "GPU"]], schema = shape, errors = "null")
```

A wrong JSON shape is asked again once, then raises `llm.FormatError`; other model failures are `llm.Error`.
`ask_all` sends 4 requests at a time and shows progress in the bar.

## Data, search, networks

- `csv.read(path, numbers = true)` gives a list of records; `csv.write(path, rows)`; `json.read`, `json.write`,
  `json.parse`; `fs.read`, `fs.write`, `fs.list(path, glob = "**/*.md")`; `re.find_all(r"\d+", s)`.
- `vector_store db = rag.VectorStore()`, `db.add_dir("notes")`, `db.search(q, k = 3)` (hits have `.text`,
  `.score`), `db.context(q)` (text for a prompt).

```upsil
import nn
model Net {
    val l1 = nn.Linear(2, 32)
    val l2 = nn.Linear(32, 2)
    fun forward(x) { return l2(nn.relu(l1(x))) }
}
val x = nn.randn(256, 2)
val y = (x[:, 0] * x[:, 1] > 0).long()
val net = Net()
nn.fit(net, x, y, epochs = 30, lr = 0.01)     // progress goes to the SOS bar
print(nn.accuracy(net, x, y), nn.count_params(net))
```

`with nn.evaluating(net) { }`: eval mode, no gradients. `nn.auto_device()`: "cuda", "mps" or "cpu".

## Writing UpsiL well

- Declare names with `val`/`var` before use; a `val` cannot be reassigned. Imports go at the top level.
- Bodies of `if`/`for`/`while` always need `{ }`; an if-expression needs parentheses and `else`.
- Not in 0.3: inheritance, block lambdas, `?.`, `?:`, nested destructuring (use a named `fun`).
- Run `upsil check FILE` after writing: errors point at `.upl` lines and suggest names.
