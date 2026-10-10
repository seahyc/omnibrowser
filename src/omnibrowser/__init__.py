"""
OmniBrowser - Multi-profile browser automation for AI agents.

Works with Claude, GPT, Kimi K2, DeepSeek, Ollama.
Supports Chrome, Edge, Arc, Brave, Dia.
"""

__version__ = "0.1.0"

# Lazy imports to avoid requiring aiohttp for CLI-only usage
def __getattr__(name):
    if name in ("ChromeAdapter", "ChromeProfile", "ChromeInstance", "CDPClient"):
        from omnibrowser.adapters.chrome import (
            ChromeAdapter,
            ChromeProfile,
            ChromeInstance,
            CDPClient,
        )
        return locals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "ChromeAdapter",
    "ChromeProfile",
    "ChromeInstance",
    "CDPClient",
]
