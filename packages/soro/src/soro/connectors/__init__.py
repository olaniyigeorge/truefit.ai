"""
Connectors: turn an existing system into tools.

    soro.connectors.functions(save_note, end_call)       # Python functions
    soro.connectors.openapi("https://api.example/openapi.json")
    soro.connectors.mcp("python my_server.py")

Each returns a Connector (async tools() and aclose()), which Agent consumes.
openapi and mcp import their libraries only when used, so the base install
stays dependency-free.
"""

from soro.connectors.base import Connector, ToolPair, registry_from_pairs
from soro.connectors.functions import FunctionConnector, functions, spec_from_function, tool
from soro.connectors.mcp import MCPConnector, mcp
from soro.connectors.openapi import OpenAPIConnector, openapi

__all__ = [
    "Connector",
    "FunctionConnector",
    "MCPConnector",
    "OpenAPIConnector",
    "ToolPair",
    "functions",
    "mcp",
    "openapi",
    "registry_from_pairs",
    "spec_from_function",
    "tool",
]
