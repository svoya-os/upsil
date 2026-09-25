#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run an UpsiL program with microtorch standing in for PyTorch (development aid).

    python3 tests/run_microtorch.py examples/neural_net.upl [args...]
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.dirname(HERE))

import microtorch  # noqa: E402

microtorch.install()
from upsil.cli import main  # noqa: E402

sys.exit(main(["run", *sys.argv[1:]]))
