# SPDX-License-Identifier: Apache-2.0
"""random: pseudo-random numbers (not for passwords or keys).

    import random
    random.seed(42)
    print(random.randint(1, 6), random.choice(["a", "b"]), random.random())
"""

from __future__ import annotations

import random as _random
from typing import Any, List

__all__ = ["seed", "random", "randint", "uniform", "choice", "sample", "shuffle"]

seed = _random.seed
random = _random.random          # a float in [0, 1)
randint = _random.randint        # both ends included
uniform = _random.uniform
choice = _random.choice
sample = _random.sample


def shuffle(items: List[Any]) -> None:
    """Shuffle a list in place."""
    _random.shuffle(items)
