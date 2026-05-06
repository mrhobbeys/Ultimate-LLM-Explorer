from .base import Adapter, IngestContext
from .chatgpt import ChatGPTAdapter
from .claude import ClaudeAdapter
from .detector import detect, iter_sources
from .gemini import GeminiAdapter

ADAPTERS: dict[str, Adapter] = {
    "chatgpt": ChatGPTAdapter(),
    "claude": ClaudeAdapter(),
    "gemini": GeminiAdapter(),
}

__all__ = [
    "ADAPTERS",
    "Adapter",
    "ChatGPTAdapter",
    "ClaudeAdapter",
    "GeminiAdapter",
    "IngestContext",
    "detect",
    "iter_sources",
]
