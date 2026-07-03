"""Oracle: a stateful, free-to-run Discord cog that simulates a compromised
Windows server as a two-mode text adventure.

Mode one is the GUI/desktop (log in, read the ticket, talk to your boss and
coworkers). Mode two is a real command line on the box, where the filesystem
remembers every ``move``/``del`` and permissions and network behave like the
real thing. NPCs remember your conversations; progress is tracked as objectives,
XP, and analyst ranks. The whole game runs offline for free; an optional LLM
backend (local Ollama or the Anthropic API) only enriches character dialogue.

Core modules (``state``, ``filesystem``, ``shell``, ``world``, ``network``,
``progression``, ``narrative``, ``engine``) have no Discord dependency and are
unit-testable on their own. Only ``cog`` and ``bot`` import discord.py.
"""

__all__ = ["__version__"]
__version__ = "0.1.0"
