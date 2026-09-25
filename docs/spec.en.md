# UpsiL 0.2 language specification

[Русская версия](spec.md) · [Tutorial (Russian)](tutorial.md) · [README](../README.en.md)

> **Status: v0.2 is an early version.** This document describes only what is implemented and
> covered by tests (`python3 -m unittest discover -s tests`). The code examples here are
> tested too: every block compiles, and the output shown is the real output. If `upsil`
> behaves differently from this text, that is a bug; please report it.

## Contents

1. [Overview](#1-overview)
2. [Lexical structure](#2-lexical-structure)
3. [Grammar (EBNF)](#3-grammar-ebnf)
4. [Expressions](#4-expressions)
5. [Statements](#5-statements)
6. [Functions](#6-functions)
7. [Scopes](#7-scopes)
8. [Classes and models](#8-classes-and-models)
9. [AI: models, prompts, search](#9-ai-models-prompts-search)
10. [Imports](#10-imports)
11. [Built-in functions](#11-built-in-functions)
12. [Modules](#12-modules)
13. [Compiling, running and errors](#13-compiling-running-and-errors)
14. [Not in v0.2](#14-not-in-v02)

## 1. Overview

UpsiL is a small language for scripts that work with language models, document search and
neural networks. The syntax is close to Kotlin (`fun`, `val`/`var`, `for (i in 0..n)`), and a
program compiles to a Python module: the compiler builds a Python syntax tree (the `ast`
module) and runs it. Therefore:

- typing at run time is dynamic, as in Python; type annotations are recorded, and
  `upsil check` reports only obvious literal mismatches;
- any Python library can be used explicitly: `import py "numpy" as np`;
- `upsil build` shows the readable Python code a program turns into.

A program file has the extension `.upl` and is UTF-8. A program runs from top to bottom;
there is no mandatory `main` function (it is common to declare `fun main()` and call it at the
end of the file).

```upsil
val name = "UpsiL"
fun greet(who) {
    return "Hello, {who}!"
}
print(greet(name))
```
```output
Hello, UpsiL!
```

## 2. Lexical structure

### 2.1. Source text and comments

Source text is UTF-8; a BOM at the start is allowed, and `\r\n` and `\r` line breaks count
as `\n`.

Comments: `//` to the end of the line, and `/* ... */`, which may nest. A `/* */` comment
that contains a line break acts as a line break.

```upsil
// line comment
/* block /* nested */ comment */
print(1) // after code
```
```output
1
```

### 2.2. End of a statement

A line break ends a statement. A line break does **not** end a statement:

1. inside round `( )` and square `[ ]` brackets;
2. inside the braces of a dict literal `{ }` (inside a code block `{ }`, on the contrary,
   line breaks separate statements);
3. when a line ends with an operator that needs a right operand: `+ - * / % @ ** == != <
   <= > >= = += -= *= /= %= .. ..= => -> , : .` or with the word `and`, `or`, `not`, `in`;
4. when the next line starts with a dot `.` (a chain of calls).

A line break is also allowed before the `{` that opens a block, and before `else`. A `;` can
be used instead of a line break. After the `}` of a compound statement (`fun`, `if`, `while`,
`for`, `class`, `model`) the next statement may follow on the same line.

```upsil
val total = 1 +
    2 +
    3
val words = ["one",
             "two"]
val text = "  Hello, World  "
    .strip()
    .lower()
print(total, words, text); print("done")
val x = 5
-3
print(x)
```
```output
6 ["one", "two"] hello, world
done
5
```

In the last example `-3` is a separate statement: the line break after `val x = 5` ended the
declaration.

### 2.3. Names

A name starts with a letter or `_` and consists of letters, digits and `_`. Letters may be any
Unicode letters (`val имя = 1`); names are NFKC-normalised, as in Python. Case matters.

Reserved, and so not usable as names:

- UpsiL keywords (2.4);
- Python keywords that are not UpsiL keywords:
  `False None True assert async await def del elif except finally from global is lambda
  nonlocal pass raise try with yield`, because the program compiles to Python;
- `self` and `super` (they cannot be declared);
- names that start with `_upsil` (the compiler's own names).

### 2.4. Keywords

Always keywords:

```text
if else while for return break continue
fun val var class import as
and or not in
true false null
```

Contextual words are special in one place only, and ordinary names everywhere else (so
`val model = 1` is fine):

| Word | Special meaning |
|---|---|
| `model` | `model Name { ... }` declares a model (section 8.2) |
| `graph` | `graph forward(x) { ... }`, a method inside a `model` |
| `llm` | `llm m = ...` declares an AI model (9.1) |
| `vector_store` | `vector_store db = ...` declares a store (9.3) |
| `py` | `import py "numpy"` imports a Python module |
| `json` | `[m] => "..." -> json` asks for a JSON answer |

### 2.5. Numbers

- Integers: `42`, `1_000_000`, `0xFF`, `0b1010`, `0o755`. `_` separates digit groups.
- Floats: `3.14`, `1e-3`, `2.5E+2`. The dot must be between digits, so `0..5` is a range,
  not a number.
- A minus before a number is the unary operator.

### 2.6. Strings

A string is written in double quotes `"..."` and fits on one line. UpsiL has no single-quoted
strings.

Escape sequences:

| Written | Character |
|---|---|
| `\n` `\t` `\r` `\0` | line feed, tab, carriage return, NUL |
| `\"` `\'` `\\` | double quote, apostrophe, backslash |
| `\{` `\}` | braces |
| `A`, `\u{1F600}` | a Unicode character by code (4, or 1–6 hex digits) |

Any other `\x` sequence is a compile error.

**Interpolation.** `{expression}` inside a string inserts the value of the expression, shown
the way `print` shows it (section 4.9). Inside the braces is an ordinary UpsiL expression: the
compiler parses and checks it (unknown names are compile errors), and it is never run as text.
Strings may be used inside: `"{d["key"]}"`. A format may follow a colon, as in Python:
`{x:.2f}`, `{name:<10}`; with a format, the value is formatted by Python
(`format(x, ".2f")`).

To write a brace, escape it: `\{` and `\}`. A lone `}` is fine as it is. Empty `{}` is an
error.

```upsil
val name = "Max"
val pi = 3.14159
print("Hi, {name}! {1 + 2} {[1, "a"]} {pi:.2f}")
print("JSON: \{\"a\": 1\}")
```
```output
Hi, Max! 3 [1, "a"] 3.14
JSON: {"a": 1}
```

Values that reach a string at run time are inserted as they are: braces in data are just
characters.

**Multi-line strings** `"""..."""` are handy for prompts. Inside them `"` needs no escape;
interpolation and escape sequences work. If a line break follows the opening `"""` directly,
the string is dedented: that line break is dropped, the line with the closing `"""` is dropped
if it holds only spaces, and the indentation common to the other lines is removed (decided by
the non-blank lines and by the indentation of the closing quotes). Otherwise the text is taken
as it is.

```upsil
fun prompt(doc) {
    return """
        Summarize the text in three points.
          Text: "{doc}"
        """
}
print(prompt("..."))
```
```output
Summarize the text in three points.
  Text: "..."
```

### 2.7. Operators and punctuation

```text
+  -  *  /  %  **  @
== != <  <= >  >=
=  += -= *= /= %=
.. ..=  =>  ->  .  ,  :  ;  ?
( ) [ ] { }
```

`&&`, `||`, `!`, `#` and `'` are errors with a hint (`and`, `or`, `not`, `//`, `"`).
`?` is only allowed after a type (`int?`).

## 3. Grammar (EBNF)

Notation: `{ x }` is zero or more repetitions, `[ x ]` is optional, `|` is a choice. `NAME`,
`NUMBER`, `STRING` and `NEWLINE` are the tokens of section 2.

```ebnf
program       = { separator } { statement { separator } } ;
separator     = NEWLINE | ";" ;

statement     = var_decl | resource_decl | fun_decl | class_decl | model_decl
              | if_stmt | while_stmt | for_stmt
              | "return" [ expression ] | "break" | "continue"
              | import_stmt | assignment | expression ;
(* Simple statements (all except fun, class, model, if, while, for) must end with a
   separator, "}" or the end of the file. *)

block         = "{" { separator } { statement { separator } } "}" ;

var_decl      = ( "val" | "var" ) NAME [ ":" type ] [ "=" expression ] ;
              (* a val needs a value, except for class fields *)
resource_decl = ( "llm" | "vector_store" ) NAME [ "=" expression ] ;
type          = NAME { "." NAME } [ "[" type { "," type } "]" ] [ "?" ] ;

fun_decl      = "fun" NAME "(" [ params ] ")" [ "->" type ] block ;
params        = param { "," param } [ "," ] ;
param         = NAME [ ":" type ] [ "=" expression ] ;

class_decl    = "class" NAME "{" { separator } { var_decl | fun_decl | separator } "}" ;
model_decl    = "model" NAME "{" { separator } { var_decl | fun_decl | graph_decl | separator } "}" ;
graph_decl    = "graph" NAME "(" [ params ] ")" [ "->" type ] block ;

if_stmt       = "if" expression block [ "else" ( if_stmt | block ) ] ;
while_stmt    = "while" expression block ;
for_stmt      = "for" "(" loop_target "in" expression ")" block
              | "for" loop_target "in" expression block ;
loop_target   = NAME { "," NAME } | "(" NAME { "," NAME } ")" ;

import_stmt   = "import" NAME [ "." NAME ] [ "as" NAME ]
              | "import" "py" STRING [ "as" NAME ] ;

assignment    = target ( "=" | "+=" | "-=" | "*=" | "/=" | "%=" ) expression ;
target        = NAME | postfix "." NAME | postfix "[" subscripts "]" ;

expression    = or_expr ;
or_expr       = and_expr { "or" and_expr } ;
and_expr      = not_expr { "and" not_expr } ;
not_expr      = "not" not_expr | comparison ;
comparison    = range_expr [ comp_op range_expr ] ;          (* no chains *)
comp_op       = "==" | "!=" | "<" | "<=" | ">" | ">=" | "in" | "not" "in" ;
range_expr    = additive [ ( ".." | "..=" ) additive ] ;
additive      = term { ( "+" | "-" ) term } ;
term          = unary { ( "*" | "/" | "%" | "@" ) unary } ;
unary         = ( "-" | "+" ) unary | power ;
power         = postfix [ "**" unary ] ;                      (* right-associative *)
postfix       = primary { call | "[" subscripts "]" | "." NAME } ;
call          = "(" [ argument { "," argument } [ "," ] ] ")" ;
argument      = [ NAME "=" ] expression ;                     (* named after positional *)
subscripts    = subscript { "," subscript } [ "," ] ;
subscript     = expression | [ expression ] ":" [ expression ] [ ":" [ expression ] ] ;
primary       = NUMBER | STRING | "true" | "false" | "null" | NAME
              | "(" expression ")" | list | dict | prompt ;
list          = "[" [ expression { "," expression } [ "," ] ] "]" ;
dict          = "{" [ expression ":" expression { "," expression ":" expression } [ "," ] ] "}" ;
prompt        = "[" expression [ "," "system" ":" expression ] "]" "=>" expression [ "->" "json" ] ;
```

The right side of a prompt (after `=>`) is a whole expression: `[m] => "a" + b` sends the model
`"a" + b`. To use the answer inside a bigger expression, put the prompt in parentheses:
`([m] => "Yes or no?") == "yes"`.

## 4. Expressions

### 4.1. Precedence and associativity

From weakest to strongest:

| Level | Operators | Associativity |
|---|---|---|
| 1 | `or` | left |
| 2 | `and` | left |
| 3 | `not x` | prefix |
| 4 | `== != < <= > >= in` `not in` | none (chains are errors) |
| 5 | `..` `..=` | none |
| 6 | `+ -` | left |
| 7 | `* / % @` | left |
| 8 | `-x` `+x` | prefix |
| 9 | `**` | right; binds tighter than a unary minus on its left: `-2 ** 2 == -4` |
| 10 | `f(x)` `a[i]` `a[i:j]` `a.b` | postfix |

```upsil
print((1 + 2) * 3, 1 + 2 * 3, 2 ** 3 ** 2, -2 ** 2, 10 - 4 - 3)
print(not 1 == 2, true or false and false, 3 in 0..5)
```
```output
9 7 512 -4 3
true true true
```

Chained comparisons are compile errors:

```upsil-error
val x = 5
print(0 < x < 10)
```
```output
example.upl:2:13: error: comparisons cannot be chained: write a < b and b < c
  2 | print(0 < x < 10)
    |             ^
```

### 4.2. Literals

`42`, `3.14`, `"string"`, `true`, `false`, `null`, a list `[1, 2, 3]`, a dict
`{"key": "value"}`. Lists, dicts, calls and parameter lists allow a comma after the last
element. An empty `{}` is an empty dict.

### 4.3. Arithmetic

- `+ - *` as usual; `+` joins strings and lists. `+` does not join a string and a number: use
  interpolation or `str(x)`.
- `/` is always true division: `7 / 2 == 3.5`, `4 / 2 == 2.0`.
- There is no integer-division operator, because `//` starts a comment: write `div(a, b)`
  (rounds down).
- `%` is the remainder, with the sign of the divisor (as in Python): `-7 % 3 == 2`.
- `**` is the power; `@` is matrix multiplication (for tensors and arrays).

```upsil
print(7 / 2, div(7, 2), -7 % 3, 2 ** 10, "ab" + "cd", [1] + [2])
```
```output
3.5 3 2 1024 abcd [1, 2]
```

### 4.4. Comparisons

`== != < <= > >=` compare values; `in` and `not in` test membership (in a string, list, dict,
range). Comparing with `null` (`x == null`, `x != null`) tests whether a value is empty.

### 4.5. Logic and truth

`and` and `or` are lazy and return one of their operands (as in Python):
`null or "default"` gives `"default"`. `not x` gives `true` or `false`.

False values: `false`, `null`, `0`, `0.0`, `""`, `[]`, `{}`; all other values are true.

```upsil
val name = null
print(name or "guest", 0 and 5, not "")
```
```output
guest 0 true
```

### 4.6. Ranges

`a..b` is the integers from `a` up to but **not including** `b`; `a..=b` includes `b`. A range
can be iterated with `for`, tested with `in`, turned into a list with `list(0..3)`. If
`a >= b`, `a..b` is empty.

```upsil
print(list(0..3), list(1..=3), 5 in 1..5, list(3..0))
```
```output
[0, 1, 2] [1, 2, 3] false []
```

### 4.7. Calls, indexes, slices, attributes

- Call: `f(1, 2)`, named arguments `f(1, sep = "-")`; a positional argument after a named one,
  and a repeated name, are compile errors.
- Index: `xs[0]`, `xs[-1]` (from the end), `d["key"]`; several indexes separated by commas
  (`t[0, 1]`) are passed as a tuple, which suits tensors.
- Slice: `xs[1:3]`, `xs[:2]`, `xs[::2]`.
- Attribute: `obj.name`, method: `s.strip()`.

```upsil
val xs = [10, 20, 30, 40]
print(xs[0], xs[-1], xs[1:3], xs[::2], "hello"[0:3])
print(sorted([3, 1, 2], reverse = true), ", ".join(["a", "b"]))
```
```output
10 40 [20, 30] [10, 30] hel
[3, 2, 1] a, b
```

### 4.8. Prompts

`[m] => text` is an expression whose value is the model's answer. See section 9.2.

### 4.9. How values become text

`print`, `str(x)` and interpolation `"{x}"` show values like this: `true`, `false`, `null`;
numbers as in Python (`3.0`, `0.1`); strings without quotes, but in double quotes inside lists
and dicts; lists `[1, 2]`; dicts `{"a": 1}`; ranges `0..3`; objects of UpsiL classes
`Name(field=value, ...)`. Other objects (tensors, for example) are shown the way Python shows
them.

## 5. Statements

### 5.1. `val` and `var`

`val` declares an immutable variable (assigning it again is a compile error), `var` a mutable
one. A `val` needs a value; a `var x` without a value starts as `null`. A type may be given:
`val n: int = 1`, `var names: list[str]`, `var t: int?`. Types are recorded and end up in the
annotations of the generated Python, but they are not checked at run time; `upsil check`
reports only obvious literal mismatches (`val n: int = "one"`). The types it knows: `int`,
`float` (accepts integers too), `str` (or `string`), `bool`, `list`, `dict`.

`val` forbids only a new assignment: the contents of a list or dict in a `val` can change
(`xs.append(1)`, `d["k"] = 2`).

```upsil-error
val x = 1
x = 2
```
```output
example.upl:2:1: error: cannot reassign val 'x' (declared at line 1); declare it with var
  2 | x = 2
    | ^
```

### 5.2. Assignment

`x = expression`, `obj.field = ...`, `xs[i] = ...`, `xs[1:3] = [...]`, and the compound forms
`+= -= *= /= %=`. Only declared variables (`var`), fields and elements can be assigned.
Assignment is a statement, not an expression: `a = b = 1` is not allowed.

### 5.3. `if`

```upsil
fun size(n) {
    if n > 10 {
        return "big"
    } else if n > 1 {
        return "medium"
    } else {
        return "small"
    }
}
print(size(50), size(5), size(0))
```
```output
big medium small
```

The condition may be written in parentheses (`if (x > 1) { ... }`); braces are required.

### 5.4. `while`

`while condition { ... }` repeats the block while the condition is true.

### 5.5. `for`

A loop goes over any sequence: a range, list, string, dict (its keys), and also the results of
`enumerate`, `zip`, `d.items()`. Two equivalent forms, with and without parentheses; a pair can
be split into two variables right away:

```upsil
for (i in 0..3) { print(i, end = " ") }
print()
for ch in "ab" { print(ch) }
for (k, v) in {"a": 1, "b": 2}.items() { print("{k}={v}") }
for i, word in enumerate(["x", "y"]) { print(i, word) }
```
```output
0 1 2 
a
b
a=1
b=2
0 x
1 y
```

Loop variables are visible only in the loop body and cannot be changed.

### 5.6. `break` and `continue`

`break` leaves the nearest loop, `continue` goes to its next step. Outside a loop (including a
nested function inside a loop) they are compile errors.

### 5.7. `return`

`return expression` returns a value from a function; `return` without a value (or the end of
the function) returns `null`. `return` outside a function is a compile error. The expression
must start on the same line as `return`.

## 6. Functions

```upsil
fun greet(name: str, greeting = "Hello", punct = "!") -> str {
    return "{greeting}, {name}{punct}"
}
print(greet("Ann"))
print(greet("Bob", punct = "?"))
print(greet(greeting = "Hi", name = "Eve"))
```
```output
Hello, Ann!
Hello, Bob?
Hi, Eve!
```

- Parameters are immutable (like `val`). Parameter and result types are optional.
- Default values are evaluated **at every call** and may use earlier parameters:
  `fun area(w, h = w)`. A parameter without a default cannot follow one with a default.
- For a direct call of an UpsiL function the compiler checks the number of arguments and the
  names of named arguments.
- Functions can be nested and see the variables of enclosing functions (closures); a `var` of
  an enclosing function can be changed.
- A function may call functions declared further down the file, and itself.

```upsil
fun counter() {
    var n = 0
    fun next_value() {
        n += 1
        return n
    }
    return next_value
}
val c = counter()
c()
print(c(), c())
```
```output
2 3
```

**Limitation of v0.2.** A closure captures the variable, not its value (as in Python):
functions created in a loop body see the last value of the loop variable.

## 7. Scopes

- A block `{ }` is a scope. A name is visible from its declaration to the end of the block;
  using it earlier in the same function is a compile error.
- A function body sees every name of the blocks the function is declared in, including names
  declared further down: that is why functions can call each other in any order. At the top
  level of a file code runs from top to bottom, and calling a function before its declaration
  is a compile error.
- Declaring a name twice in one block is an error. Declaring a name that is visible from an
  enclosing block of the same function (shadowing it) is an error too. Inside a function the
  names of the top level and the parameters of other functions can be reused; sibling blocks
  may declare the same names.
- Built-in functions (section 11) can be shadowed by your own declarations.
- `class`, `model` and `import` are only allowed at the top level.

The compiler finds these errors before running and reports all of them at once:

```upsil-error
val limit = 10
fun check(n) {
    if n > lmit {
        print("too many")
    }
    return result
}
```
```output
example.upl:3:12: error: undefined name 'lmit'; did you mean 'limit'?
  3 |     if n > lmit {
    |            ^^^^
example.upl:6:12: error: undefined name 'result'
  6 |     return result
    |            ^^^^^^
```

## 8. Classes and models

### 8.1. `class`

A class body holds only fields (`val`/`var`) and methods (`fun`).

- A field **without a value** becomes a constructor parameter (in declaration order); a field
  with a value gets it when an object is created (evaluated anew for every object; it may use
  fields declared above it).
- Inside methods, fields and methods are available by name (`count += 1`) or through `self`
  (`self.count`). `self` is not written in the parameter list.
- A `val` field cannot change after the object is created.
- There is no inheritance. An object is shown as `Name(field=value, ...)`.

```upsil
class Counter {
    val name: str
    var count = 0

    fun inc(by = 1) {
        count += by
        return self
    }

    fun label() {
        return "{name}: {count}"
    }
}

val c = Counter("clicks")
c.inc().inc(by = 5)
print(c.label(), c.count)
print(c)
```
```output
clicks: 6 6
Counter(name="clicks", count=6)
```

### 8.2. `model`

`model` declares a neural network, a subclass of `torch.nn.Module` (PyTorch is required,
section 9.4). Fields become layers registered in the constructor; fields without a value become
constructor parameters, as in classes. A `forward` method is required; it may be declared with
`graph` (the same as `fun`, but it marks the method as the computation). Inside methods, layers
are called by name: `l1(x)` means `self.l1(x)`.

```upsil
import nn

model Net {
    val hidden: int
    val l1 = nn.Linear(4, hidden)
    val l2 = nn.Linear(hidden, 2)

    graph forward(x) {
        return l2(nn.relu(l1(x)))
    }
}
```

This becomes the following Python (`upsil build`):

```python
class Net(_upsil_nn.Module):

    def __init__(self, hidden: int):
        super().__init__()
        self.hidden = hidden
        self.l1 = nn.Linear(4, self.hidden)
        self.l2 = nn.Linear(self.hidden, 2)

    def forward(self, x):
        return self.l2(nn.relu(self.l1(x)))
```

Without PyTorch the program stops at the `model` line with "PyTorch is not installed...".

## 9. AI: models, prompts, search

### 9.1. Models: `llm`

A model is an `llm.Model` object that talks to a server with an OpenAI-compatible API
(`/v1/chat/completions`). Declare it as an ordinary variable or in resource form:

```upsil
import llm

val a = llm.Model("qwen3.5-4b")        // a model with an explicit name
llm b = llm.Model(temperature = 0.2)   // the same in resource form
llm c                                  // the default model
```

`llm name = expression` is a `val` that also checks at run time that the value is a model;
`llm name` without a value creates `llm.Model()`. Creating a model does not contact the
server: the first request goes out with the first question.

The server address is the first one found of:

1. `llm.Model(url = "...")`;
2. the `UPSIL_LLM_URL` environment variable;
3. `[llm] url` in `~/.config/upsil/config.toml` (or in the file named by `UPSIL_CONFIG`;
   `XDG_CONFIG_HOME` is respected);
4. `http://127.0.0.1:8080/v1`, the local server of SOS (`sos models serve`).

The model name: the argument of `llm.Model("name")`, else `UPSIL_LLM_MODEL`, else `[llm] model`
in the settings file, else the first model the server lists (`/v1/models`). An API key is
optional: `UPSIL_LLM_KEY` or `OPENAI_API_KEY` (for cloud servers). The time limit is `timeout`
(seconds, 120 by default, or `[llm] timeout`).

```toml
# ~/.config/upsil/config.toml
[llm]
url = "http://127.0.0.1:8080/v1"
model = "qwen3.5-4b"
timeout = 120

[rag]
embed_model = "bge-m3"
backend = "auto"
```

If the server does not answer, the program stops with a clear error:

```text
error: The local model is not responding (127.0.0.1:8080). On SOS: sos models serve
```

Model methods: `ask`, `chat`, `stream`, `embed`, `models` (section 12). Reasoning blocks
(`<think>...</think>`) that some local models print are removed from answers.

### 9.2. The prompt operator `=>`

```upsil
import llm

llm m = llm.Model()
val doc = "UpsiL is a language for AI scripts."
val short = [m] => "Summarize in one sentence: {doc}"
val terse = [m, system: "Answer with one word"] => "Capital of France?"
val data = [m] => "Return JSON with fields name and age for: Ann, 30 years" -> json
print(short, terse, data["name"])
```

- `[m] => text` sends model `m` one user message and returns the answer (a string). The text
  can be any expression; if it is not a string, it is turned into text as `print` does.
- `[m, system: s] => text` adds the system prompt `s`.
- `-> json` asks for a JSON answer: the system prompt gets an instruction to answer with JSON
  only, and `response_format` is used when the server supports it. The answer is parsed (a
  ```json fence and chatter around it are tolerated) and returned as a dict or list; if it is
  not JSON, that is a run-time error.
- `m` can be any object with an `ask(text, system, json)` method, for example your own class.
- Interpolation in the prompt text inserts data as text: variable contents are never run or
  treated as a template.

### 9.3. Document search: `vector_store`

```upsil
import rag

vector_store db = rag.VectorStore()
db.add("Paris is the capital of France.", {"topic": "geography"})
db.add("The Moon goes around the Earth.")
for (hit in db.search("what goes around the Earth?", k = 1)) {
    print(hit.text)
}
```

`vector_store db` without a value creates `rag.VectorStore()`; the form with `=` checks that
the value is a store.

Search works one of two ways:

- **embeddings** (`backend = "embeddings"`): text vectors come from the model server
  (`POST /v1/embeddings`); similarity is cosine, computed in pure Python;
- **by words** (`backend = "bm25"`): BM25 with a light normalisation of Russian and English
  word endings.

By default (`backend = "auto"`) the store tries embeddings at the first add; if the server has
none (llama.cpp started without `--embeddings`, for example) or does not answer, it says so
once on stderr and searches by words from then on. It does the same if embeddings disappear
later. Choose explicitly with `rag.VectorStore(backend = "bm25")`; the embedding model with
`rag.VectorStore("bge-m3")` or `[rag] embed_model`.

`search` returns a list of hits, best first; each has `text`, `score`, `meta` and `id`
(`hit.text` or `hit["text"]`). Searching by words finds only documents that contain at least
one word of the query. `add_dir` adds the files of a folder (`*.md` by default, recursively,
skipping hidden folders), split into fragments of about 1000 characters; `meta` gets `source`
(the path inside the folder) and `chunk`. `save(path)` and `rag.VectorStore.load(path)` store
the index as JSON. The whole store lives in memory: it is meant for notes and documents, not
for millions of fragments.

### 9.4. Neural networks: `nn`

`import nn` gives access to PyTorch: `nn.X` is looked up in `torch.nn`, then in
`torch.nn.functional`, then in `torch` (`nn.Linear`, `nn.relu`, `nn.tensor`, `nn.optim.Adam`,
`nn.manual_seed`, ...); `nn.torch` is the `torch` module itself; `nn.available()` tells whether
PyTorch is installed. PyTorch is imported on first use; install it with `pip install torch` or
`uv tool install 'upsil[nn]'`. A complete example:
[examples/neural_net.upl](../examples/neural_net.upl).

## 10. Imports

```upsil
import llm                       // an UpsiL module
import nn.functional as F        // part of a module under a name
import py "numpy" as np          // a Python module
import py "os.path"              // binds the name os
```

UpsiL modules: `llm`, `rag`, `nn`, `fs`, `http`, `json`, `ui`, `sys`, `math`, `time`,
`random` (section 12). `import x.y as z` binds `z` to `x.y`; deeper imports are not allowed.
`import py "name"` brings in any Python module (without `as`, the first part of the dotted name
is bound, as in Python). Imports are only allowed at the top level of a file. v0.2 cannot import
other `.upl` files; a Python module next to the script is available through `import py`.

## 11. Built-in functions

Available without an import:

| Function | What it does |
|---|---|
| `print(x, ..., sep = " ", end = "\n")` | prints values as described in 4.9; output appears immediately if `end` has no line break |
| `input(prompt = "")` | a line from the keyboard; `null` at the end of input (Ctrl-D) |
| `str(x)` | the text of a value as `print` shows it; `isinstance(s, str)` works |
| `div(a, b)` | integer division rounding down |
| `error(message)` | stops the program with the error `message` |
| `int float bool len range list dict set tuple min max sum abs round sorted reversed enumerate zip map filter any all chr ord format isinstance divmod pow iter next hash` | as in Python |

Other Python functions (`open`, `eval`, `getattr`...) are not UpsiL built-ins; if needed, get
them with `import py "builtins"`.

## 12. Modules

**llm**: models (9.1, 9.2).
`llm.Model(name = null, url = null, api_key = null, timeout = null, temperature = null,
max_tokens = null, system = null)`. Methods: `ask(prompt, system = null, json = false,
temperature = null, max_tokens = null)`, the answer to one question; `chat(messages, ...)`, the
answer to a conversation, where `messages` is a list of `{"role": ..., "content": ...}` (roles
`system`, `user`, `assistant`); `stream(prompt_or_messages, ...)`, the answer in pieces, for a
`for` loop; `embed(texts, model = null)`, vectors; `models()`, the server's models. Fields
`name`, `url`. Functions `llm.models()`, `llm.default_url()`. While the server loads a model
(HTTP 503), the request is retried within `timeout`.

**rag**: the document store (9.3).
`rag.VectorStore(model = null, backend = "auto", url = null, chunk_size = 1000)`; methods
`add(text, meta = null)` (returns the `id`), `add_dir(path, glob = "*.md")` (returns the
number of fragments), `search(query, k = 3)`, `context(query, k = 3)` (the texts found, as one
string for a prompt), `save(path)`; `rag.VectorStore.load(path)`; `len(db)`; field `backend`.

**nn**: PyTorch (9.4).

**fs**: files (text is UTF-8): `read(path)`, `write(path, text)`, `append(path, text)`,
`lines(path)`, `exists(path)`, `is_file(path)`, `is_dir(path)`, `list(path = ".", glob = "*")`
(sorted paths relative to `path`; `"**/*.md"` includes subfolders), `mkdir(path)` (with
parents), `remove(path)` (a file), `join(parts...)`, `dirname(path)`, `basename(path)`,
`home()`, `cwd()`.

**http**: `get(url, headers = null, timeout = 30)` (text), `get_json(url, ...)`,
`post(url, body = "", ...)`, `post_json(url, data, ...)` (sends JSON, returns parsed JSON or
text). Network and HTTP errors stop the program with a clear message. Proxies from the
environment are used, except for local addresses.

**json**: `parse(text)`, `stringify(value, indent = null)`, `read(path)`,
`write(path, value, indent = 2)`.

**ui**: a tkinter chat window: `ui.Window(title = "UpsiL", width = 600, height = 700,
echo = true)`; methods `add_message(text)` (callable from any thread), `on_submit(handler)`
(the handler gets the text and runs in a background thread), `show()`, `close()`. Needs
`python3-tk` and a graphical session; without them the error says so.

**sys**: `args` (the arguments after the file name), `script` (the file name),
`env(name, default = null)`, `exit(code = 0)`, `platform`, `version` (the UpsiL version).

**math**: everything from Python's `math` module: `sqrt`, `floor`, `ceil`, `log`, `sin`, `pi`,
`e`, `inf`, `gcd`...

**time**: `now()` (seconds since 1970), `monotonic()`, `sleep(seconds)`, `today()`
(`YYYY-MM-DD`), `format(fmt = "%Y-%m-%d %H:%M:%S", at = null)`.

**random**: `seed(x)`, `random()`, `randint(a, b)` (both ends included), `uniform(a, b)`,
`choice(xs)`, `sample(xs, k)`, `shuffle(xs)`. Not for passwords.

## 13. Compiling, running and errors

### 13.1. How the compiler works

Text → tokens → UpsiL tree → checks (names, `val`, `break`, `return`, argument counts...) →
Python tree (`ast`) with line and column numbers from the `.upl` file →
`compile(..., "file.upl", "exec")` → run. Program text is never executed as a string of Python
code.

### 13.2. Commands

| Command | What it does |
|---|---|
| `upsil run FILE [ARGS...]` | compiles and runs; the arguments go to `sys.args`; `upsil FILE.upl` does the same |
| `upsil run -` | reads the program from standard input |
| `upsil build FILE [-o OUT]` | prints the generated Python or writes it to `OUT` (never next to the source by itself, never over it) |
| `upsil check FILE...` | looks for errors without running, including literal type mismatches |
| `upsil repl` | interactive mode |
| `upsil version`, `upsil help` | version and help |

`python -m upsil` works the same way. The script's folder is added to Python's import path.

Exit codes: `0` success, `1` run-time error, `2` compile error, `64` usage error (no such file,
unknown command). `sys.exit(n)` ends the program with code `n`.

### 13.3. Error messages

Messages are in Russian if `UPSIL_LANG`, `LC_ALL`, `LC_MESSAGES` or `LANG` (in this order; the
first one set) starts with `ru`, and in English otherwise. A compile error:

```text
hello.upl:12:5: error: unexpected ')' — expected an expression
  12 | print(1 + )
     |           ^
```

A run-time error shows only the lines of the UpsiL program (no Python internals), with the
exact spot when Python 3.11 or newer knows it:

```upsil
fun main() {
    val x = 0
    print(1 / x)
}
main()
```
```output
Runtime error (most recent call last):
  example.upl:5, in <program>
    main()
  example.upl:3, in main
    print(1 / x)
          ^^^^^
ZeroDivisionError: division by zero
```

When the same call repeats many times in a row (deep recursion), it is shown three times and
then summarised as "the same call repeated N more times". `UPSIL_TRACEBACK=python` shows the
full Python traceback.

### 13.4. REPL

`upsil repl` runs input right away and shows the values of expressions (strings in quotes).
Input continues while a bracket is open or a line ends with an operator; an empty line ends the
input. Names can be declared again. Exit with Ctrl-D or `:q`.

## 14. Not in v0.2

Deliberately left for later: exception handling (`try`/`catch`), anonymous functions, `if` as
an expression, tuple literals and unpacking in assignments, class inheritance, static type
checking, importing other `.upl` files, async code, a code formatter (`fmt`), a language server
(LSP), compilation to machine code (the LLVM prototype of v0.1 is kept in git history).
