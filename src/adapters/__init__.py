"""Platform adapter registry (deliverable #12).

    from adapters import get_adapter
    adapter = get_adapter("esp32")
    cmd = adapter.build_cmd(".")        # -> ['idf.py', '-C', '.', 'build']

The conductor picks an adapter from board.yml `meta.platform` and executes the
argv it returns. ESP32 is supported; the rest are experimental scaffolds.
"""
from .base import PlatformAdapter
from .esp32 import Esp32Adapter
from .others import Rp2040Adapter, Stm32Adapter, ZephyrAdapter

__all__ = ["PlatformAdapter", "Esp32Adapter", "Stm32Adapter", "Rp2040Adapter",
           "ZephyrAdapter", "get_adapter", "list_adapters"]

_ADAPTERS = {a.name: a for a in (
    Esp32Adapter(), Stm32Adapter(), Rp2040Adapter(), ZephyrAdapter(),
)}


def get_adapter(platform):
    try:
        return _ADAPTERS[platform]
    except KeyError:
        known = ", ".join(sorted(_ADAPTERS))
        raise ValueError("unknown platform '" + str(platform)
                         + "' (known: " + known + ")")


def list_adapters():
    return {name: a.supported for name, a in _ADAPTERS.items()}
