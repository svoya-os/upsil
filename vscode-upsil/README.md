# UpsiL for VS Code

Syntax highlighting for [UpsiL](https://github.com/svoya-os/upsil) 0.2 (`.upl` files): keywords,
strings with `{...}` interpolation, triple-quoted prompts, the prompt operator `[m] => "..."`,
`model`/`graph` blocks, comments and numbers.

Подсветка синтаксиса [UpsiL](https://github.com/svoya-os/upsil) 0.2 (файлы `.upl`).

The grammar is generated from the language's keyword list by `tools/gen_syntax.py` in the main
repository; edit that script, not `syntaxes/upsil.tmLanguage.json`.

Build a package: `npx @vscode/vsce package` (inside `vscode-upsil/`). Licensed under Apache-2.0.
