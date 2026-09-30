"""
Builds the app's live model adapter from AppConfig, using the Soro SDK.

All the provider logic (adapters, fallback, failover) lives in Soro. This wrapper
only maps the app's settings onto Soro's explicit arguments.

Settings read from AppConfig:
  LLM_PRIMARY_PROVIDER    "gemini" | "openai"           (blank means gemini)
  LLM_FALLBACK_PROVIDER   "gemini" | "openai" | "none"  (blank means none)
  GEMINI_API_KEY, GEMINI_LIVE_MODEL, OPENAI_API_KEY, OPENAI_REALTIME_MODEL
"""

from __future__ import annotations

from soro import LiveSessionPort
from soro import create_live_adapter as soro_create_live_adapter

from src.truefit_infra.config import AppConfig


def create_live_adapter() -> LiveSessionPort:
    return soro_create_live_adapter(
        getattr(AppConfig, "LLM_PRIMARY_PROVIDER", None),
        getattr(AppConfig, "LLM_FALLBACK_PROVIDER", None),
        gemini_api_key=getattr(AppConfig, "GEMINI_API_KEY", None),
        gemini_model=getattr(AppConfig, "GEMINI_LIVE_MODEL", None),
        openai_api_key=getattr(AppConfig, "OPENAI_API_KEY", None),
        openai_model=getattr(AppConfig, "OPENAI_REALTIME_MODEL", None),
    )
