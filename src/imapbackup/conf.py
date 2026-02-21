from __future__ import annotations

import logging
import pathlib
from typing import Any

import yaml

log = logging.getLogger(__name__)


def load(path: pathlib.Path | str) -> list[dict]:
    with open(path, encoding="utf-8-sig") as f:
        cd = yaml.safe_load(f)
    return [{"name": name, **content} for name, content in cd.items()]


def find(configs: list[dict], key: str, value: str, default: dict | None = None) -> dict | None:
    _value = value.casefold()
    return next((c for c in configs if c.get(key, "").casefold() == _value), default)


def bool_opt(data: dict, key: Any, default: bool = False) -> bool:
    if key in data:
        value = data[key]
        if isinstance(value, bool):
            return value
        else:
            value = str(value).strip().casefold()
            if value in ("1", "on", "yes", "true"):
                return True
            elif value in ("0", "off", "no", "false"):
                return False
            else:
                log.warning("Unmatched value for option '%s': %s", key, value)
                return default
    else:
        return default
