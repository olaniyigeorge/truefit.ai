"""Provider adapters. Each imports its SDK lazily, so install only the extras you use."""

from soro.adapters.composed import ComposedLiveAdapter, create_composed_adapter
from soro.adapters.factory import create_live_adapter
from soro.adapters.fallback import FallbackLiveAdapter

__all__ = ["ComposedLiveAdapter", "FallbackLiveAdapter", "create_composed_adapter", "create_live_adapter"]
