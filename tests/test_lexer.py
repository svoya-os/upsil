# SPDX-License-Identifier: Apache-2.0
import unittest

from support import UpsilTestCase, lang

from upsil.errors import CompileError
from upsil.lexer import InterpToken, tokenize


def kinds(src):
    return [(t.kind, t.value) for t in tokenize(src) if t.kind != "STRING"]


def string_parts(src):
    toks = [t for t in tokenize(src) if t.kind == "STRING"]
    assert len(toks) == 1, toks
    out = []
    for p in toks[0].value:
        if isinstance(p, InterpToken):
            out.append(("{", [t.value for t in p.tokens if t.kind != "EOF"], p.spec))
        else:
            out.append(p)
    return out


def lex_error(src):
    with lang("en"):
        try:
            tokenize(src)
        except CompileError as e:
            d = e.diagnostics[0]
            return d.message, d.span.line, d.span.col, d.incomplete
    raise AssertionError("no error")


class TokensTest(UpsilTestCase):
    def test_simple_line_with_positions(self):
        toks = tokenize("val x = 42")
        self.assertEqual([(t.kind, t.value) for t in toks],
                         [("KW", "val"), ("NAME", "x"), ("OP", "="), ("INT", 42), ("NEWLINE", "\n"), ("EOF", None)])
        self.assertEqual((toks[1].span.line, toks[1].span.col, toks[1].span.end_col), (1, 5, 6))
        self.assertEqual((toks[3].span.col, toks[3].span.end_col), (9, 11))

    def test_positions_on_later_lines(self):
        toks = tokenize("a\n  bb")
        bb = [t for t in toks if t.value == "bb"][0]
        self.assertEqual((bb.span.line, bb.span.col), (2, 3))

    def test_numbers(self):
        self.assertEqual(kinds("1_000 0x1F 0b101 0o17 3.14 1e-3 2.5E+2")[:-2],
                         [("INT", 1000), ("INT", 31), ("INT", 5), ("INT", 15), ("FLOAT", 3.14),
                          ("FLOAT", 0.001), ("FLOAT", 250.0)])

    def test_range_is_not_a_float(self):
        self.assertEqual(kinds("1..2 0..=n")[:-2],
                         [("INT", 1), ("OP", ".."), ("INT", 2), ("INT", 0), ("OP", "..="), ("NAME", "n")])

    def test_bad_numbers(self):
        for src in ("x = 1_", "x = 12abc", "x = 1__0", "x = 0x"):
            msg, line, col, _ = lex_error(src)
            self.assertIn("invalid number", msg)
            self.assertEqual((line, col), (1, 5))

    def test_keywords_and_contextual_words(self):
        self.assertEqual(kinds("fun model graph llm vector_store json py self")[:-2],
                         [("KW", "fun"), ("NAME", "model"), ("NAME", "graph"), ("NAME", "llm"),
                          ("NAME", "vector_store"), ("NAME", "json"), ("NAME", "py"), ("NAME", "self")])

    def test_unicode_names(self):
        self.assertEqual(kinds("val имя = 1")[:4], [("KW", "val"), ("NAME", "имя"), ("OP", "="), ("INT", 1)])
        # NFKC like Python: the ligature "ﬁ" is the same name as "fi"
        self.assertEqual(kinds("ﬁle")[0], ("NAME", "file"))

    def test_operators_longest_first(self):
        self.assertEqual([v for k, v in kinds("a..=b => c -> d ** e <= f != g += 1")[:-2]],
                         ["a", "..=", "b", "=>", "c", "->", "d", "**", "e", "<=", "f", "!=", "g", "+=", 1])


class StringTest(UpsilTestCase):
    def test_escapes(self):
        self.assertEqual(string_parts(r'"a\nb\t\"q\" \\ \{x\} \u0041 \u{1F600}"'),
                         ['a\nb\t"q" \\ {x} A \U0001F600'])

    def test_bad_escape(self):
        msg, line, col, _ = lex_error(r'x = "a\qb"')
        self.assertIn("unknown escape '\\q'", msg)
        self.assertEqual((line, col), (1, 7))

    def test_unterminated(self):
        msg, line, col, incomplete = lex_error('x = "abc')
        self.assertIn("unterminated string", msg)
        self.assertEqual((line, col, incomplete), (1, 5, False))

    def test_line_break_inside_regular_string(self):
        msg, *_ = lex_error('x = "ab\ncd"')
        self.assertIn("line break", msg)

    def test_interpolation(self):
        self.assertEqual(string_parts('"Hi {name}, {a + b}!"'),
                         ["Hi ", ("{", ["name"], None), ", ", ("{", ["a", "+", "b"], None), "!"])

    def test_interpolation_with_nested_string_and_spec(self):
        self.assertEqual(string_parts('"{d["k"]} {pi:.2f}"'),
                         [("{", ["d", "[", ["k"], "]"], None), " ", ("{", ["pi"], ".2f")])

    def test_interpolation_positions(self):
        tok = [t for t in tokenize('x = "ab {name}"') if t.kind == "STRING"][0]
        interp = tok.value[1]
        self.assertEqual((interp.span.col, interp.span.end_col), (9, 15))
        self.assertEqual(interp.tokens[0].span.col, 10)

    def test_empty_interpolation(self):
        msg, line, col, _ = lex_error('x = "a{}"')
        self.assertIn("empty { }", msg)
        self.assertEqual(col, 7)

    def test_escaped_braces_are_literal(self):
        self.assertEqual(string_parts(r'"\{not code\}"'), ["{not code}"])

    def test_lone_closing_brace_is_literal(self):
        self.assertEqual(string_parts('"a } b"'), ["a } b"])

    def test_triple_quoted_verbatim_on_one_line(self):
        self.assertEqual(string_parts('"""say "hi" {x}"""'), ['say "hi" ', ("{", ["x"], None)])

    def test_triple_quoted_dedent(self):
        src = 'fun f() {\n    val p = """\n        Summarize:\n          {doc}\n\n        Done\n        """\n}'
        self.assertEqual(string_parts(src), ["Summarize:\n  ", ("{", ["doc"], None), "\n\nDone"])

    def test_triple_quoted_closing_quotes_limit_the_dedent(self):
        src = 'val p = """\n    a\n      b\n  """'
        self.assertEqual(string_parts(src), ["  a\n    b"])

    def test_escaped_whitespace_is_not_indentation(self):
        src = 'val p = """\n  \\tx\n  y\n  """'
        self.assertEqual(string_parts(src), ["\tx\ny"])

    def test_unterminated_triple_is_incomplete(self):
        msg, line, col, incomplete = lex_error('val p = """\nabc')
        self.assertIn("unterminated string", msg)
        self.assertTrue(incomplete)


class CommentsAndNewlinesTest(UpsilTestCase):
    def test_comments(self):
        self.assertEqual(kinds("a // line\n/* block /* nested */ still */ b"),
                         [("NAME", "a"), ("NEWLINE", "\n"), ("NAME", "b"), ("NEWLINE", "\n"), ("EOF", None)])

    def test_block_comment_with_line_break_ends_statement(self):
        self.assertEqual([k for k, _ in kinds("a /* x\n y */ b")], ["NAME", "NEWLINE", "NAME", "NEWLINE", "EOF"])

    def test_unterminated_block_comment(self):
        msg, line, col, incomplete = lex_error("a /* never")
        self.assertIn("unterminated comment", msg)
        self.assertEqual((line, col, incomplete), (1, 3, True))

    def test_newline_ends_statement(self):
        self.assertEqual([k for k, _ in kinds("val x = 5\n-3")],
                         ["KW", "NAME", "OP", "INT", "NEWLINE", "OP", "INT", "NEWLINE", "EOF"])

    def test_no_newline_inside_parens_and_brackets(self):
        self.assertNotIn("NEWLINE", [k for k, _ in kinds("f(1,\n2)")][:-2])
        self.assertNotIn("NEWLINE", [k for k, _ in kinds("[1\n,2\n]")][:-2])

    def test_newlines_inside_braces_reach_the_parser(self):
        self.assertIn("NEWLINE", [k for k, _ in kinds("{\n a: 1\n}")][:-2])

    def test_trailing_operator_continues(self):
        for op in ("+", "*", "==", "and", "or", "not", "in", "=", ",", ".", "=>", "..", ":"):
            toks = [k for k, _ in kinds(f"a {op}\n b")]
            self.assertEqual(toks.count("NEWLINE"), 1, op)

    def test_leading_dot_continues(self):
        self.assertEqual([v for _, v in kinds("s\n  // comment\n  .strip()\n  .lower()")][:-2],
                         ["s", ".", "strip", "(", ")", ".", "lower", "(", ")"])

    def test_blank_lines_collapse(self):
        self.assertEqual([k for k, _ in kinds("\n\na\n\n\nb\n\n")], ["NAME", "NEWLINE", "NAME", "NEWLINE", "EOF"])


class ErrorsTest(UpsilTestCase):
    def test_hints_for_other_languages(self):
        self.assertIn("use 'and' instead of '&&'", lex_error("a && b")[0])
        self.assertIn("use 'or' instead of '||'", lex_error("a || b")[0])
        self.assertIn("use 'not' instead of '!'", lex_error("!a")[0])
        self.assertIn("double quotes", lex_error("x = 'a'")[0])
        self.assertIn("comments start with //", lex_error("# hi")[0])

    def test_unexpected_character(self):
        msg, line, col, _ = lex_error("a\nb $ c")
        self.assertEqual((msg, line, col), ("unexpected character '$'", 2, 3))

    def test_brackets(self):
        self.assertIn("unmatched ')'", lex_error("a)")[0])
        msg, line, col, _ = lex_error("(\n]")
        self.assertIn("']' does not match '(' opened at 1:1", msg)
        msg, line, col, incomplete = lex_error("foo(1,\n2")
        self.assertEqual((msg, line, col, incomplete), ("'(' is never closed", 1, 4, True))

    def test_russian_messages(self):
        with lang("ru"):
            with self.assertRaises(CompileError) as cm:
                tokenize("a && b")
            text = cm.exception.format()
        self.assertIn("<input>:1:3: ошибка: используйте 'and' вместо '&&'", text)


if __name__ == "__main__":
    unittest.main()
