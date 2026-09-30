"""
Build a LiveSessionPort from plain arguments.

Nothing here reads global application config: the caller passes provider names
and credentials in. (Each adapter can still fall back to its provider's usual
environment variable, see the adapter docstrings.)

Adding a provider: implement LiveSessionPort in soro/adapters/<name>.py and add a
case to _make_adapter(). No other file changes.
"""

from __future__ import annotations

import logging

from soro.adapters.fallback import FallbackLiveAdapter
from soro.ports import LiveSessionPort

logger = logging.getLogger("soro.factory")

PROVIDERS = ("gemini", "openai")
_NONE = "none"


def _make_adapter(
    provider: str,
    *,
    gemini_api_key: str | None,
    gemini_model: str | None,
    gemini_voice: str | None,
    openai_api_key: str | None,
    openai_model: str | None,
    openai_voice: str | None,
) -> LiveSessionPort:
    """Provider libraries are imported here, so a provider you do not use need not be installed."""
    match provider.strip().lower():
        case "gemini":
            from soro.adapters.gemini import GeminiLiveAdapter

            kwargs = {"voice": gemini_voice} if gemini_voice else {}
            return GeminiLiveAdapter(api_key=gemini_api_key, model=gemini_model, **kwargs)
        case "openai":
            from soro.adapters.openai import OpenAIRealtimeAdapter

            kwargs = {"voice": openai_voice} if openai_voice else {}
            return OpenAIRealtimeAdapter(api_key=openai_api_key, model=openai_model, **kwargs)
        case _:
            raise ValueError(
                f"Unknown provider: {provider!r}. Valid values are {', '.join(PROVIDERS)} "
                f"(or 'none' for the fallback)."
            )


def create_live_adapter(
    primary: str | None = "gemini",
    fallback: str | None = "none",
    *,
    gemini_api_key: str | None = None,
    gemini_model: str | None = None,
    gemini_voice: str | None = None,
    openai_api_key: str | None = None,
    openai_model: str | None = None,
    openai_voice: str | None = None,
) -> LiveSessionPort:
    """
    primary / fallback: "gemini" or "openai"; fallback may also be "none".
    Blank or None values mean the defaults ("gemini" and "none").

    With a fallback the result is a FallbackLiveAdapter: it opens the primary and,
    if that fails to open or fails before producing any output, continues on the
    fallback. Without one it is the primary adapter itself.

    Raises ValueError for an unknown provider or when primary == fallback, and
    RuntimeError if a provider's API key is missing.
    """
    primary_name = (primary or "").strip().lower() or "gemini"
    fallback_name = (fallback or "").strip().lower() or _NONE
    if fallback_name != _NONE and fallback_name == primary_name:
        raise ValueError(
            f"fallback ({fallback_name!r}) cannot be the same as primary ({primary_name!r}). "
            f"Use 'none' to disable the fallback."
        )
    opts = dict(
        gemini_api_key=gemini_api_key,
        gemini_model=gemini_model,
        gemini_voice=gemini_voice,
        openai_api_key=openai_api_key,
        openai_model=openai_model,
        openai_voice=openai_voice,
    )
    logger.info("primary=%r fallback=%r", primary_name, fallback_name)
    main = _make_adapter(primary_name, **opts)
    if fallback_name == _NONE:
        return main
    return FallbackLiveAdapter(primary=main, fallback=_make_adapter(fallback_name, **opts))
