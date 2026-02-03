from __future__ import annotations

import threading
import time
from collections import OrderedDict
from collections.abc import Callable

_CACHE_MAX_ITEMS = 512
_CACHE_TTL_SECONDS = 5.0

_lock = threading.Lock()
_cache: OrderedDict[str, tuple[float, list[dict]]] = OrderedDict()


def get_cached_suggestions(cache_key: str, loader: Callable[[], list[dict]]) -> list[dict]:
    """Return cached suggestions for a cache key or compute and store them."""
    if not cache_key:
        return loader()

    now = time.monotonic()
    with _lock:
        entry = _cache.get(cache_key)
        if entry is not None:
            timestamp, value = entry
            if now - timestamp <= _CACHE_TTL_SECONDS:
                _cache.move_to_end(cache_key)
                return value
            _cache.pop(cache_key, None)

    value = loader()
    with _lock:
        _cache[cache_key] = (now, value)
        _cache.move_to_end(cache_key)
        while len(_cache) > _CACHE_MAX_ITEMS:
            _cache.popitem(last=False)
    return value


def invalidate_suggestions_cache() -> None:
    """Clear all cached suggestion results."""
    with _lock:
        _cache.clear()
