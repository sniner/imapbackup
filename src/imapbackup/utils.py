from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


def chunks(items: list[Any], n: int):
    """Yield successive n-sized chunks from items. Reference: https://stackoverflow.com/a/312464"""
    for i in range(0, len(items), n):
        yield items[i : i + n]
