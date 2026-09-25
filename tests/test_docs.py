# SPDX-License-Identifier: Apache-2.0
"""The code in the documentation is checked like the code in examples/.

In README*.md and docs/*.md:

* every ```upsil block must compile;
* an ```upsil block followed by an ```output block must print exactly that
  (a run-time error is compared as `upsil run` shows it on stderr);
* an ```upsil-error block must fail to compile with exactly the message in
  the ```output block that follows it.

The file name in messages is "example.upl"; the language is English for
*.en.md files and Russian otherwise.
"""

import contextlib
import io
import re
import sys
import unittest

from support import ROOT, UpsilTestCase, env

from upsil.compiler import compile_source
from upsil.errors import CompileError

DOCS = sorted([*ROOT.glob("README*.md"), *(ROOT / "docs").glob("*.md")])
FENCE = re.compile(r"^```([\w-]*)[^\n]*\n(.*?)^```\s*$", re.M | re.S)


def blocks(text):
    """(kind, code, output-or-None, line) for each upsil block."""
    found = list(FENCE.finditer(text))
    out = []
    for i, m in enumerate(found):
        kind = m.group(1)
        if kind not in ("upsil", "upsil-error"):
            continue
        output = None
        if i + 1 < len(found) and found[i + 1].group(1) == "output":
            between = text[m.end():found[i + 1].start()]
            if not between.strip():
                output = found[i + 1].group(2)
        out.append((kind, m.group(2), output, text.count("\n", 0, m.start()) + 1))
    return out


def run(code):
    from upsil.tracebacks import format_runtime_error
    program = compile_source(code, "example.upl")
    out = io.StringIO()
    saved_stdin = sys.stdin
    sys.stdin = io.StringIO("")
    try:
        with contextlib.redirect_stdout(out):
            exec(program.code, {"__name__": "__main__"})
    except Exception as exc:  # shown like `upsil run` would show it
        return out.getvalue() + format_runtime_error(exc) + "\n"
    finally:
        sys.stdin = saved_stdin
    return out.getvalue()


def drop_carets(text):
    return "\n".join(line for line in text.split("\n") if not re.fullmatch(r"\s*\^+\s*", line))


class DocsTest(UpsilTestCase):
    def test_docs_exist(self):
        names = {p.relative_to(ROOT).as_posix() for p in DOCS}
        for required in ("README.md", "README.en.md", "docs/spec.md", "docs/spec.en.md", "docs/tutorial.md"):
            self.assertIn(required, names)

    def test_code_blocks(self):
        total = 0
        for path in DOCS:
            language = "en" if path.name.endswith(".en.md") else "ru"
            for kind, code, output, line in blocks(path.read_text(encoding="utf-8")):
                total += 1
                where = f"{path.relative_to(ROOT)}:{line}"
                with self.subTest(block=where), env(UPSIL_LANG=language, UPSIL_CONFIG="/nonexistent",
                                                    UPSIL_LLM_URL="http://127.0.0.1:9/v1"):
                    if kind == "upsil-error":
                        with self.assertRaises(CompileError, msg=where) as cm:
                            compile_source(code, "example.upl")
                        if output is not None:
                            self.assertEqual(cm.exception.format() + "\n", output, where)
                        continue
                    if output is None:
                        compile_source(code, "example.upl")
                        continue
                    got = run(code)
                    if sys.version_info < (3, 11):
                        self.assertEqual(drop_carets(got), drop_carets(output), where)
                    else:
                        self.assertEqual(got, output, where)
        self.assertGreater(total, 40)


if __name__ == "__main__":
    unittest.main()
