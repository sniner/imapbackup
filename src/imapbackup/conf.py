import logging
import pathlib
import yaml

from typing import Any, Union, List

log = logging.getLogger(__name__)


def load(path:Union[pathlib.Path,str]) -> dict:
    with open(path) as f:
        cd = yaml.safe_load(f)
    return [{"name":name, **content} for name,content in cd.items()]


def find(configs:List[dict], key:str, value:str, default:dict=None) -> dict:
    return next((c for c in configs if c.get(key, "").lower()==value), default)


def bool_opt(data:dict, key:Any, default:bool=False) -> bool:
    if key in data:
        value = data[key]
        if isinstance(value, bool):
            return value
        else:
            value = str(value).strip().lower()
            if value in ("1", "on", "yes", "true"):
                return True
            elif value in ("0", "off", "no", "false"):
                return False
            else:
                log.warning("Unmatched value for option '%s': %s", key, value)
                return default
    else:
        return default

