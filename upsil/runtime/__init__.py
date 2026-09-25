# SPDX-License-Identifier: Apache-2.0
"""The UpsiL runtime.

``prelude`` holds the helpers that compiled programs use (``print``, string
display, the prompt operator...). The other modules are what ``import x``
gives an UpsiL program: llm, rag, nn, fs, http, json, ui, sys, math, time,
random. They only use the Python standard library; ``nn`` imports PyTorch
lazily, ``ui`` imports tkinter lazily.
"""
