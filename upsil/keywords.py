# SPDX-License-Identifier: Apache-2.0
"""The single list of UpsiL words.

The lexer and checker use these tuples, and ``tools/gen_syntax.py`` builds the
editor grammars (VS Code, GNOME Text Editor, Kate) from them, so a keyword is
added in exactly one place. A test checks that the generated files are in sync.
"""

# Reserved everywhere.
CONTROL = ("if", "else", "while", "for", "return", "break", "continue")
DECLARATION = ("fun", "val", "var", "class", "import", "as")
OPERATOR_WORDS = ("and", "or", "not", "in")
CONSTANTS = ("true", "false", "null")

HARD_KEYWORDS = CONTROL + DECLARATION + OPERATOR_WORDS + CONSTANTS

# Keywords only in one position, ordinary names everywhere else:
#   model Net { ... }            graph forward(x) { ... }   (inside a model)
#   llm m = llm.Model()          vector_store db = rag.VectorStore()
#   import py "numpy" as np      [m] => "..." -> json
CONTEXTUAL = ("model", "graph", "llm", "vector_store", "py", "json")

# Names that can be read but never declared.
SPECIAL_NAMES = ("self", "super")

# Global functions available without an import.
BUILTINS = (
    "print", "input", "str", "int", "float", "bool", "len", "range",
    "list", "dict", "set", "tuple", "min", "max", "sum", "abs", "round",
    "sorted", "reversed", "enumerate", "zip", "map", "filter", "any", "all",
    "chr", "ord", "format", "isinstance", "divmod", "pow", "iter", "next",
    "hash", "div", "error",
)

# Builtins that UpsiL implements itself (upsil.runtime.prelude); the rest are
# the Python builtins of the same name.
PRELUDE_BUILTINS = ("print", "input", "str", "div", "error")

# Runtime modules for `import x`.
MODULES = ("llm", "rag", "nn", "fs", "http", "json", "ui", "sys", "math", "time", "random")

# Python keywords that are not UpsiL keywords: they cannot be used as names,
# because the program is compiled to Python.
PYTHON_ONLY_KEYWORDS = (
    "False", "None", "True", "assert", "async", "await", "def", "del", "elif",
    "except", "finally", "from", "global", "is", "lambda", "nonlocal", "pass",
    "raise", "try", "with", "yield",
)

# Operators, longest first (the lexer tries them in this order).
OPERATORS = (
    "..=", "..", "**", "=>", "->", "==", "!=", "<=", ">=", "+=", "-=", "*=", "/=", "%=",
    "+", "-", "*", "/", "%", "@", "<", ">", "=", "(", ")", "[", "]", "{", "}",
    ",", ":", ";", ".", "?",
)
