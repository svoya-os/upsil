# SPDX-License-Identifier: Apache-2.0
"""The editor grammars are generated from upsil/keywords.py and must stay in sync."""

import importlib.util
import json
import keyword
import re
import unittest
import xml.etree.ElementTree as ET

from support import ROOT, UpsilTestCase

from upsil import keywords as kw
from upsil.lexer import KEYWORDS


def load_generator():
    spec = importlib.util.spec_from_file_location("gen_syntax", ROOT / "tools" / "gen_syntax.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SyntaxFilesTest(UpsilTestCase):
    @classmethod
    def setUpClass(cls):
        cls.gen = load_generator()

    def test_generated_files_are_up_to_date(self):
        self.assertEqual(self.gen.outdated(), [], "run: python3 tools/gen_syntax.py")

    def test_files_parse(self):
        ET.parse(ROOT / "editor" / "upsil.lang")
        ET.parse(ROOT / "editor" / "upsil.xml")
        json.loads((ROOT / "vscode-upsil" / "syntaxes" / "upsil.tmLanguage.json").read_text(encoding="utf-8"))
        json.loads((ROOT / "vscode-upsil" / "language-configuration.json").read_text(encoding="utf-8"))

    def test_every_word_is_in_every_file(self):
        words = (kw.HARD_KEYWORDS + ("model", "graph", "llm", "vector_store") + kw.SPECIAL_NAMES + kw.BUILTINS)
        for rel in self.gen.OUTPUTS:
            text = (ROOT / rel).read_text(encoding="utf-8")
            for word in words:
                with self.subTest(file=rel, word=word):
                    self.assertRegex(text, rf"(?<![\w]){re.escape(word)}(?![\w])")

    def test_textmate_regexes_compile(self):
        grammar = json.loads((ROOT / "vscode-upsil" / "syntaxes" / "upsil.tmLanguage.json").read_text(encoding="utf-8"))
        found = 0

        def walk(node):
            nonlocal found
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ("match", "begin", "end") and isinstance(value, str):
                        # Oniguruma's \p{L} / \p{N} have no equivalent in Python's re; the rest is shared
                        re.compile(value.replace(r"\p{L}", "a-zA-Z").replace(r"\p{N}", "0-9"))
                        found += 1
                    else:
                        walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(grammar)
        self.assertGreater(found, 20)
        self.assertEqual(grammar["scopeName"], "source.upsil")

    def test_lexer_uses_the_same_list(self):
        self.assertEqual(KEYWORDS, frozenset(kw.HARD_KEYWORDS))

    def test_python_keywords_are_reserved(self):
        self.assertEqual(set(keyword.kwlist) - set(kw.HARD_KEYWORDS), set(kw.PYTHON_ONLY_KEYWORDS))

    def test_vscode_package(self):
        pkg = json.loads((ROOT / "vscode-upsil" / "package.json").read_text(encoding="utf-8"))
        self.assertEqual(pkg["publisher"], "svoya-os")
        self.assertEqual(pkg["license"], "Apache-2.0")
        self.assertNotIn("ultimate", pkg["description"].lower())
        self.assertTrue((ROOT / "vscode-upsil" / pkg["icon"]).is_file())
        for lang in pkg["contributes"]["languages"]:
            for icon in lang["icon"].values():
                self.assertTrue((ROOT / "vscode-upsil" / icon).is_file(), icon)
        for grammar in pkg["contributes"]["grammars"]:
            self.assertTrue((ROOT / "vscode-upsil" / grammar["path"]).is_file())
        self.assertEqual(list((ROOT / "vscode-upsil").glob("*.vsix")), [])


if __name__ == "__main__":
    unittest.main()
