"""
LiveAdapterFactory - constructs the correct LiveSessionPort from environment config.

─────────────────────
WHAT THIS MODULE DOES
─────────────────────
Single function: create_live_adapter().

Reads two environment variables from AppConfig:
  LLM_PRIMARY_PROVIDER  - which provider to use first ("openai" | "gemini")
  LLM_FALLBACK_PROVIDER - backup provider, or "none" to disable ("openai" | "gemini" | "none")

Returns a LiveSessionPort that the WebSocket layer and orchestration service can
use without knowing which concrete adapter is running underneath.

If a fallback is configured, the return value is a FallbackLiveAdapter wrapping
both. If no fallback, the primary adapter is returned directly (no wrapper overhead).

─────────────────────
ADDING A NEW PROVIDER
─────────────────────
1. Implement LiveSessionPort in truefit_infra/llm/your_adapter.py
2. Add a case to _make_adapter() below
3. Add the provider name to the AppConfig docstring
4. That's it - no other files need to change.
"""

from __future__ import annotations

from src.truefit_core.application.ports import LiveSessionPort
from src.truefit_core.common.utils import logger
from src.truefit_infra.config import AppConfig
from src.truefit_infra.llm.fallback_adapter import FallbackLiveAdapter


_PROVIDER_NONE = "none"


def _make_adapter(provider: str) -> LiveSessionPort:
    """
    Instantiates a concrete LiveSessionPort for the given provider name.

    Imports are done inside the match so that provider libraries that aren't
    installed don't cause import errors at startup. If we only have Gemini
    credentials, the OpenAI SDK doesn't need to be installed/imported.
    """
    match provider.strip().lower():
        case "gemini":
            from src.truefit_infra.llm.gemini_live import GeminiLiveAdapter
            return GeminiLiveAdapter()

        case "openai":
            from src.truefit_infra.llm.openai_realtime import OpenAIRealtimeAdapter
            return OpenAIRealtimeAdapter()

        case _:
            raise ValueError(
                f"Unknown LLM provider: {provider!r}. "
                f"Valid values are 'openai', 'gemini', or 'none' (fallback only)."
            )

# ─────────────────────
# PUBLIC FACTORY METHOD
# ─────────────────────

def create_live_adapter() -> LiveSessionPort:
    """
    Reads LLM_PRIMARY_PROVIDER and LLM_FALLBACK_PROVIDER from AppConfig and
    returns the correctly-wired LiveSessionPort.

    Possible outcomes:
      primary=gemini,  fallback=none   → GeminiLiveAdapter (no wrapper)
      primary=openai,  fallback=none   → OpenAIRealtimeAdapter (no wrapper)
      primary=gemini,  fallback=openai → FallbackLiveAdapter(Gemini → OpenAI)
      primary=openai,  fallback=gemini → FallbackLiveAdapter(OpenAI → Gemini)

    Raises:
      ValueError  - if a provider name is unrecognised or primary == fallback
      RuntimeError - if a required API key is missing (raised inside the adapter)
    """
    primary_name: str = getattr(AppConfig, "LLM_PRIMARY_PROVIDER", "openai")
    fallback_name: str = getattr(AppConfig, "LLM_FALLBACK_PROVIDER", "none")

    primary_name = primary_name.strip().lower()
    fallback_name = fallback_name.strip().lower()

    logger.info(
        f"[LiveAdapterFactory] primary={primary_name!r} fallback={fallback_name!r}"
    )

    # Validate before constructing to make sure primary and fallback aren't the same (would cause weird infinite recursion bugs in FallbackLiveAdapter)
    if fallback_name != _PROVIDER_NONE and fallback_name == primary_name:
        raise ValueError(
            f"LLM_FALLBACK_PROVIDER ({fallback_name!r}) cannot be the same as "
            f"LLM_PRIMARY_PROVIDER ({primary_name!r}). "
            f"Set LLM_FALLBACK_PROVIDER=none to disable fallback."
        )

    primary = _make_adapter(primary_name)

    if fallback_name == _PROVIDER_NONE:
        logger.info(
            f"[LiveAdapterFactory] No fallback configured — "
            f"returning {type(primary).__name__} directly"
        )
        return primary

    fallback = _make_adapter(fallback_name)
    adapter = FallbackLiveAdapter(primary=primary, fallback=fallback)

    logger.info(
        f"[LiveAdapterFactory] Returning FallbackLiveAdapter "
        f"({type(primary).__name__} → {type(fallback).__name__})"
    )
    return adapter