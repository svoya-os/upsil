---
name: upsil
description: Write, run and fix programs in UpsiL (упсиль), the SOS language for AI scripts (.upl files) — prompts to a local LLM, JSON answers of a given shape, decisions with probabilities, search over notes, PyTorch networks, CSV data.
aliases: упсил, upsil
---
# UpsiL

UpsiL compiles to readable Python. Files: `.upl`; Kotlin-like syntax.

- Run: `sos run main.upl ARGS` (progress in the SOS bar) or `upsil run main.upl ARGS`.
- Check: `upsil check main.upl`. Tests: `upsil test` runs `fun test_...()` in `test_*.upl`.
- New project: `sos new NAME --template upsil`. Local model: `sos models serve` (found automatically).
- PyTorch for `nn`: `uv add torch` in the project; `sos run` uses its `.venv`.
- Docs and examples: /usr/share/doc/upsil.

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
try { print(10 / n) } catch (e: ZeroDivisionError) { print("ноль") } finally { print("ok") }
assert len(evens) == 5, "evens = {evens}"
class Point { val x: float; val y: float; fun norm() { return (x * x + y * y) ** 0.5 } }
print(Point(3, 4).norm(), div(7, 2), statistics.mean([1, 2]))   // div: integer division; / is float
```

`true`/`false`/`null`, `and`/`or`/`not`, `//` comments; `throw "..."` fails.
Modules: `llm rag nn csv json fs re http sys math time random ui`; arguments: `sys.args`.

## Models

```upsil
import llm
llm m = llm.Model(temperature = 0.2)   // or llm.Model("qwen3.5-4b")
val text = "UpsiL — язык для ИИ-скриптов."
val short = [m] => "Перескажи одним предложением: {text}"
val word = [m, system: "Одним словом"] => "Столица Франции?"
val shape = {"label": ["pos", "neg", "neu"], "score": float, "note?": str}
try {
    val a = [m] => "Оцени тональность: {text}" -> json(shape)
    print(a.label, a.score)      // JSON answers are records: a.label == a["label"]
} catch (e: llm.FormatError) {
    print("не тот JSON:", e.reply)
}
val answers = m.ask_all(["Тема: {t}" for t in ["кошки", "GPU"]], schema = shape, errors = "null")
val team = [m] => "Кто ответит? {text}" -> choice(["billing", "tech"])   // team.value, team.p
val spam = [m] => "Это спам? {text}" -> yes                             // probability of yes
```

A wrong JSON shape is asked again once, then `llm.FormatError`; other failures are `llm.Error`.
Decisions (`-> choice(...)`, `-> yes`, `-> score(0..=3)`) give probabilities in one model step: act when
`p` is high, else ask a human; `m.decide(text, {"k": llm.Yes("?")})` asks several at once.

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
print(nn.accuracy(net, x, y))
```

`with nn.evaluating(net) { }`: eval mode, no gradients.

## Writing UpsiL well

- Declare names with `val`/`var` first; a `val` cannot be reassigned; imports only at the top.
- Bodies of `if`/`for`/`while` always need `{ }`; an if-expression needs parentheses and `else`.
- Not yet: inheritance, block lambdas, `?.`, `?:`, nested destructuring (use a named `fun`).
- Run `upsil check FILE` after writing.
