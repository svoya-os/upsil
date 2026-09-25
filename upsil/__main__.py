# SPDX-License-Identifier: Apache-2.0
"""``python -m upsil`` is the same as the ``upsil`` command."""

import sys

from .cli import main

sys.exit(main())
