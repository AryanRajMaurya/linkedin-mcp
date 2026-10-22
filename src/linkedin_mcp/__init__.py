"""linkedin-mcp — a Model Context Protocol server for LinkedIn.

Lets any MCP-capable agent read a LinkedIn profile, check a draft post and
publish it, through the official LinkedIn API.

The quality gate lives inside the server, so an agent cannot publish
something that reads as though nobody wrote it.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
