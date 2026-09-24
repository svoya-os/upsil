"""UpsiL lexer: turns source text into a token stream.

Unrecognised characters and unterminated strings raise LexerError with a
line/column, instead of being silently dropped from the stream.
"""
import re
from typing import List, NamedTuple


class Token(NamedTuple):
    type: str
    value: str
    line: int
    column: int


class LexerError(Exception):
    """The source contains something UpsiL cannot tokenise."""


# Order matters: a longer operator must precede any operator that prefixes it,
# so that '=>' is not read as '=' followed by '>'.
_TOKEN_SPEC = [
    ('COMMENT',  r'//[^\n]*'),
    ('NUMBER',   r'\d+(?:\.\d+)?'),
    ('ID',       r'[A-Za-z_][A-Za-z0-9_.]*'),
    ('STRING',   r'"(?:\.|[^"\\n])*"'),
    ('RAG_OP',   r'=>'),
    ('ARROW',    r'->'),
    ('EQEQ',     r'=='),
    ('OP_NE',    r'!='),
    ('OP_GE',    r'>='),
    ('OP_LE',    r'<='),
    ('ASSIGN',   r'='),
    ('RANGE',    r'\.\.'),
    ('OP',       r'[+\-*/%@><!]'),
    ('PUNC',     r'[(){}\[\]:,]'),
    ('NEWLINE',  r'\n'),
    ('SKIP',     r'[ \t\r]+'),
    ('MISMATCH', r'.'),
]

_TOK_REGEX = re.compile(
    '|'.join('(?P<%s>%s)' % pair for pair in _TOKEN_SPEC),
    re.DOTALL,
)

KEYWORDS = {
    'fun', 'val', 'var', 'tensor', 'prob', 'if', 'else', 'return',
    'distributed', 'consensus', 'model', 'graph', 'import',
    'vector_store', 'llm', 'for', 'while', 'in', 'and', 'or', 'not',
    'true', 'false', 'gpu_kernel', 'malloc', 'free', 'class',
}

# Multi-character comparisons are surfaced to the parser as plain OP tokens so
# that every binary operator travels through one code path.
_SURFACED_AS_OP = {'OP_NE', 'OP_GE', 'OP_LE'}


def lex(code: str) -> List[Token]:
    tokens: List[Token] = []
    line_num = 1
    line_start = 0

    for mo in _TOK_REGEX.finditer(code):
        kind = mo.lastgroup
        value = mo.group()
        column = mo.start() - line_start + 1

        if kind == 'NEWLINE':
            line_start = mo.end()
            line_num += 1
            continue
        if kind in ('SKIP', 'COMMENT'):
            continue
        if kind == 'MISMATCH':
            if value == '"':
                raise LexerError(
                    f"Unterminated string literal at line {line_num}, column {column}"
                )
            raise LexerError(
                f"Unexpected character {value!r} at line {line_num}, column {column}"
            )
        if kind == 'ID' and value in KEYWORDS:
            kind = value.upper()
        elif kind in _SURFACED_AS_OP:
            kind = 'OP'

        tokens.append(Token(kind, value, line_num, column))

    return tokens
