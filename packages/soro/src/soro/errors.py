"""Errors raised by the Soro SDK."""


class SoroError(Exception):
    """Base class for every error Soro raises on purpose."""


class CapabilityNotSupported(SoroError):
    """Raised when an adapter is asked for something it cannot do (for example images).

    Check LiveSessionPort.capabilities first to avoid it.
    """
